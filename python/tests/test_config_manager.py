import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from config_manager import (
    ConfigDeployer,
    ConfigRenderer,
    DeployStatus,
    DeviceSimulator,
    Inventory,
    validate_config,
)

INVENTORY_PATH = Path(__file__).parent.parent / "inventory" / "devices.yaml"


@pytest.fixture
def inventory():
    return Inventory.from_yaml(INVENTORY_PATH)


@pytest.fixture
def renderer():
    return ConfigRenderer()


def test_inventory_loads_all_devices(inventory):
    assert len(inventory) == 4
    assert inventory.get("edge-router-01") is not None


def test_inventory_filter_by_role(inventory):
    edges = inventory.filter(role="edge")
    assert {d.hostname for d in edges} == {"edge-router-01", "edge-router-02"}


def test_inventory_filter_by_site(inventory):
    sjc = inventory.filter(site="sjc1")
    assert len(sjc) == 3


def test_render_cisco_ios(inventory, renderer):
    device = inventory.get("edge-router-01")
    config = renderer.render(device)
    assert "hostname edge-router-01" in config
    assert "interface GigabitEthernet0/0" in config
    assert "router bgp 65001" in config


def test_render_arista_eos(inventory, renderer):
    device = inventory.get("core-router-01")
    config = renderer.render(device)
    assert "hostname core-router-01" in config
    assert "interface Ethernet1" in config


def test_render_juniper_junos(inventory, renderer):
    device = inventory.get("leaf-switch-01")
    config = renderer.render(device)
    assert "host-name leaf-switch-01;" in config
    assert "local-as 65010;" in config


def test_validator_rejects_default_snmp_community():
    bad_config = "hostname foo\nsnmp-server community public RO\n"
    result = validate_config("foo", bad_config)
    assert not result.is_valid
    assert any("SNMP" in i.message for i in result.issues)


def test_validator_rejects_hostname_mismatch():
    bad_config = "hostname wrong-name\n"
    result = validate_config("edge-router-01", bad_config)
    assert not result.is_valid


def test_validator_accepts_clean_config(inventory, renderer):
    device = inventory.get("edge-router-01")
    config = renderer.render(device)
    result = validate_config(device.hostname, config)
    assert result.is_valid


def test_deployer_plan_shows_diff_for_unconfigured_device(inventory):
    transport = DeviceSimulator()
    deployer = ConfigDeployer(inventory, transport)
    device = inventory.get("edge-router-01")
    result = deployer.plan(device)
    assert result.status == DeployStatus.DRY_RUN
    assert "+hostname edge-router-01" in result.diff


def test_deployer_apply_pushes_config_and_reports_success(inventory):
    transport = DeviceSimulator()
    deployer = ConfigDeployer(inventory, transport)
    device = inventory.get("edge-router-01")

    result = deployer.apply(device)
    assert result.status == DeployStatus.SUCCESS

    # second apply should be a no-op since running config now matches intended
    result2 = deployer.apply(device)
    assert result2.status == DeployStatus.NO_CHANGE


def test_deployer_dry_run_does_not_push(inventory):
    transport = DeviceSimulator()
    deployer = ConfigDeployer(inventory, transport)
    device = inventory.get("edge-router-01")

    result = deployer.apply(device, dry_run=True)
    assert result.status == DeployStatus.DRY_RUN
    assert transport.get_running_config(device) == ""


def test_deployer_rolls_back_on_push_failure(inventory):
    transport = DeviceSimulator()
    device = inventory.get("edge-router-01")
    transport.seed(device.hostname, "hostname edge-router-01\n! old config\n")
    transport.simulate_failure_for(device.hostname)

    deployer = ConfigDeployer(inventory, transport)
    result = deployer.apply(device)

    assert result.status == DeployStatus.ROLLED_BACK
    assert transport.get_running_config(device) == "hostname edge-router-01\n! old config\n"


def test_apply_fleet_halts_after_failure_budget_exceeded(inventory):
    transport = DeviceSimulator()
    devices = inventory.all()
    transport.simulate_failure_for(devices[0].hostname)
    transport.simulate_failure_for(devices[1].hostname)

    deployer = ConfigDeployer(inventory, transport)
    results = deployer.apply_fleet(devices, max_failures=0)

    # should halt after the first failure (budget of 0)
    assert len(results) == 1
    assert results[0].status == DeployStatus.ROLLED_BACK
