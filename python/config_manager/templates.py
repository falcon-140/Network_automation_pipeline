"""
templates.py
Renders per-platform Jinja2 config templates into device-ready configuration text.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError

from .inventory import Device

TEMPLATE_DIR = Path(__file__).parent / "templates"

_PLATFORM_TEMPLATE_MAP = {
    "cisco_ios": "cisco_ios.j2",
    "arista_eos": "arista_eos.j2",
    "juniper_junos": "juniper_junos.j2",
}


class TemplateRenderError(Exception):
    pass


class ConfigRenderer:
    def __init__(self, template_dir: Path | str = TEMPLATE_DIR):
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            undefined=StrictUndefined,   # fail loudly on missing vars instead of emitting blanks
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, device: Device) -> str:
        template_name = _PLATFORM_TEMPLATE_MAP.get(device.platform)
        if not template_name:
            raise TemplateRenderError(f"No template mapped for platform '{device.platform}'")

        try:
            template = self.env.get_template(template_name)
            rendered = template.render(
                hostname=device.hostname,
                mgmt_ip=device.mgmt_ip,
                role=device.role,
                site=device.site,
                **device.vars,
            )
        except TemplateError as exc:
            raise TemplateRenderError(
                f"Failed to render config for {device.hostname} ({device.platform}): {exc}"
            ) from exc

        return rendered.strip() + "\n"
