"""
deployer.py
Orchestrates rendering -> validation -> diff -> push -> verify -> rollback
across a fleet of devices, with a pluggable transport so the same pipeline
can run against a live SSH/API backend (netmiko/napalm) in production or a
DeviceSimulator in CI/local dev.
"""
from __future__ import annotations

import difflib
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .inventory import Device, Inventory
from .templates import ConfigRenderer, TemplateRenderError
from .validator import ValidationResult, validate_config

logger = logging.getLogger("config_manager.deployer")


class DeployStatus(str, Enum):
    SUCCESS = "success"
    NO_CHANGE = "no_change"
    VALIDATION_FAILED = "validation_failed"
    PUSH_FAILED = "push_failed"
    ROLLED_BACK = "rolled_back"
    DRY_RUN = "dry_run"


@dataclass
class DeployResult:
    hostname: str
    status: DeployStatus
    diff: str = ""
    validation: ValidationResult | None = None
    error: str | None = None
    duration_ms: int = 0


class DeviceTransport(Protocol):
    """Abstraction over how config actually reaches a device."""

    def get_running_config(self, device: Device) -> str: ...
    def push_config(self, device: Device, config: str) -> None: ...


class DeviceSimulator:
    """
    In-memory device backend used for CI/local dev/tests so the pipeline
    is fully runnable without lab hardware. Swap for a NetmikoTransport /
    NapalmTransport in production.
    """

    def __init__(self):
        self._running_configs: dict[str, str] = {}
        self._fail_hosts: dict[str, int] = {}   # hostname -> remaining failures to simulate

    def seed(self, hostname: str, config: str) -> None:
        self._running_configs[hostname] = config

    def simulate_failure_for(self, hostname: str, times: int = 1) -> None:
        """Simulate a transient push failure: the next `times` push_config calls
        for this host raise, after which pushes succeed again (mirrors a real
        blip rather than a permanently unreachable device, so rollback pushes
        can still succeed)."""
        self._fail_hosts[hostname] = times

    def get_running_config(self, device: Device) -> str:
        return self._running_configs.get(device.hostname, "")

    def push_config(self, device: Device, config: str) -> None:
        remaining = self._fail_hosts.get(device.hostname, 0)
        if remaining > 0:
            self._fail_hosts[device.hostname] = remaining - 1
            raise ConnectionError(f"Simulated push failure for {device.hostname}")
        time.sleep(0.01)  # simulate network latency
        self._running_configs[device.hostname] = config


class ConfigDeployer:
    def __init__(self, inventory: Inventory, transport: DeviceTransport, renderer: ConfigRenderer | None = None):
        self.inventory = inventory
        self.transport = transport
        self.renderer = renderer or ConfigRenderer()

    def _diff(self, old: str, new: str) -> str:
        return "\n".join(
            difflib.unified_diff(
                old.splitlines(), new.splitlines(),
                fromfile="running-config", tofile="intended-config", lineterm=""
            )
        )

    def plan(self, device: Device) -> DeployResult:
        """Render + validate + diff, without touching the device."""
        start = time.monotonic()
        try:
            rendered = self.renderer.render(device)
        except TemplateRenderError as exc:
            return DeployResult(device.hostname, DeployStatus.VALIDATION_FAILED, error=str(exc))

        validation = validate_config(device.hostname, rendered)
        if not validation.is_valid:
            return DeployResult(device.hostname, DeployStatus.VALIDATION_FAILED, validation=validation)

        current = self.transport.get_running_config(device)
        diff = self._diff(current, rendered)
        status = DeployStatus.NO_CHANGE if not diff else DeployStatus.DRY_RUN
        duration_ms = int((time.monotonic() - start) * 1000)
        return DeployResult(device.hostname, status, diff=diff, validation=validation, duration_ms=duration_ms)

    def apply(self, device: Device, dry_run: bool = False) -> DeployResult:
        """Full pipeline: render -> validate -> diff -> (push unless dry_run) -> rollback on failure."""
        plan_result = self.plan(device)
        if plan_result.status in (DeployStatus.VALIDATION_FAILED, DeployStatus.NO_CHANGE):
            return plan_result
        if dry_run:
            return plan_result

        start = time.monotonic()
        previous_config = self.transport.get_running_config(device)
        rendered = self.renderer.render(device)

        try:
            logger.info("Pushing config to %s", device.hostname)
            self.transport.push_config(device, rendered)
        except Exception as exc:
            logger.error("Push failed for %s: %s — rolling back", device.hostname, exc)
            try:
                self.transport.push_config(device, previous_config)
                status = DeployStatus.ROLLED_BACK
            except Exception as rollback_exc:
                logger.critical("ROLLBACK FAILED for %s: %s", device.hostname, rollback_exc)
                status = DeployStatus.PUSH_FAILED
            duration_ms = int((time.monotonic() - start) * 1000)
            return DeployResult(device.hostname, status, diff=plan_result.diff, error=str(exc), duration_ms=duration_ms)

        duration_ms = int((time.monotonic() - start) * 1000)
        return DeployResult(device.hostname, DeployStatus.SUCCESS, diff=plan_result.diff, duration_ms=duration_ms)

    def apply_fleet(self, devices: list[Device], dry_run: bool = False, max_failures: int = 0) -> list[DeployResult]:
        """
        Rolling deployment across a set of devices. Stops early if the number
        of failures in this batch exceeds max_failures (a canary-style guardrail).
        """
        results: list[DeployResult] = []
        failures = 0
        for device in devices:
            result = self.apply(device, dry_run=dry_run)
            results.append(result)
            if result.status in (DeployStatus.PUSH_FAILED, DeployStatus.ROLLED_BACK):
                failures += 1
                if failures > max_failures:
                    logger.error(
                        "Failure budget exceeded (%s > %s) — halting fleet rollout after %s/%s devices",
                        failures, max_failures, len(results), len(devices),
                    )
                    break
        return results
