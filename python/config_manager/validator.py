"""
validator.py
Pre-deployment validation: catches malformed or policy-violating configs
before they are ever pushed to a device (fail fast, fail safe).
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass


@dataclass
class ValidationIssue:
    severity: str   # "error" | "warning"
    message: str


@dataclass
class ValidationResult:
    hostname: str
    issues: list[ValidationIssue]

    @property
    def is_valid(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def __bool__(self) -> bool:
        return self.is_valid


# Simple policy: reject configs that disable management access, leave default
# SNMP communities, or contain an IP address that isn't validly formed.
_BANNED_PATTERNS = [
    (re.compile(r"no ip domain-lookup"), "warning", "Disables DNS resolution device-wide."),
    (re.compile(r"community\s+public\b", re.IGNORECASE), "error", "Default/public SNMP community string detected."),
    (re.compile(r"community\s+private\b", re.IGNORECASE), "error", "Default/private SNMP community string detected."),
    (re.compile(r"shutdown\s*$", re.MULTILINE), "warning", "One or more interfaces are administratively shut down."),
]

_IP_LINE = re.compile(r"(?:ip address|address)\s+([\d.]+)(?:/(\d+)| ([\d.]+))?")


def validate_config(hostname: str, rendered_config: str) -> ValidationResult:
    issues: list[ValidationIssue] = []

    if not rendered_config.strip():
        issues.append(ValidationIssue("error", "Rendered config is empty."))
        return ValidationResult(hostname, issues)

    for pattern, severity, message in _BANNED_PATTERNS:
        if pattern.search(rendered_config):
            issues.append(ValidationIssue(severity, message))

    for match in _IP_LINE.finditer(rendered_config):
        ip = match.group(1)
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            issues.append(ValidationIssue("error", f"Malformed IP address in config: '{ip}'"))

    if f"hostname {hostname}" not in rendered_config and f"host-name {hostname}" not in rendered_config:
        issues.append(ValidationIssue("error", "Rendered config hostname does not match inventory hostname."))

    return ValidationResult(hostname, issues)
