"""
inventory.py
Loads and validates the network device inventory (source of truth for the pipeline).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Device:
    hostname: str
    mgmt_ip: str
    platform: str          # e.g. cisco_ios, arista_eos, juniper_junos
    role: str               # e.g. edge, core, leaf, spine
    site: str
    vars: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.platform not in SUPPORTED_PLATFORMS:
            raise ValueError(
                f"Unsupported platform '{self.platform}' for device '{self.hostname}'. "
                f"Supported: {sorted(SUPPORTED_PLATFORMS)}"
            )


SUPPORTED_PLATFORMS = {"cisco_ios", "arista_eos", "juniper_junos"}


class Inventory:
    """In-memory representation of the device fleet, loaded from YAML."""

    def __init__(self, devices: list[Device]):
        self._devices = {d.hostname: d for d in devices}

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Inventory":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Inventory file not found: {path}")

        data = yaml.safe_load(path.read_text()) or {}
        devices = []
        for entry in data.get("devices", []):
            devices.append(
                Device(
                    hostname=entry["hostname"],
                    mgmt_ip=entry["mgmt_ip"],
                    platform=entry["platform"],
                    role=entry.get("role", "unknown"),
                    site=entry.get("site", "unknown"),
                    vars=entry.get("vars", {}),
                )
            )
        return cls(devices)

    def all(self) -> list[Device]:
        return list(self._devices.values())

    def get(self, hostname: str) -> Optional[Device]:
        return self._devices.get(hostname)

    def filter(self, *, role: str | None = None, site: str | None = None, platform: str | None = None) -> list[Device]:
        result = self.all()
        if role:
            result = [d for d in result if d.role == role]
        if site:
            result = [d for d in result if d.site == site]
        if platform:
            result = [d for d in result if d.platform == platform]
        return result

    def __len__(self) -> int:
        return len(self._devices)
