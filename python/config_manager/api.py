"""
api.py
REST API for the config-management pipeline: inventory browsing, plan (dry-run)
and apply (deploy) endpoints. This is what GitHub Actions / on-call engineers
hit to drive deployments and check fleet health.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .deployer import ConfigDeployer, DeployStatus, DeviceSimulator
from .inventory import Inventory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("config_manager.api")

INVENTORY_PATH = os.environ.get("INVENTORY_PATH", str(Path(__file__).parent.parent / "inventory" / "devices.yaml"))

app = FastAPI(
    title="Network Config Management API",
    description="Deployment and health API for the network automation pipeline",
    version="1.0.0",
)

inventory = Inventory.from_yaml(INVENTORY_PATH)
transport = DeviceSimulator()
deployer = ConfigDeployer(inventory=inventory, transport=transport)


class DeployRequest(BaseModel):
    hostnames: list[str] | None = None   # None = whole fleet
    dry_run: bool = True
    max_failures: int = 0


class DeployResultOut(BaseModel):
    hostname: str
    status: str
    diff: str
    error: str | None = None
    duration_ms: int


@app.get("/health")
def health():
    return {"status": "ok", "devices_in_inventory": len(inventory)}


@app.get("/devices")
def list_devices():
    return [
        {"hostname": d.hostname, "mgmt_ip": d.mgmt_ip, "platform": d.platform, "role": d.role, "site": d.site}
        for d in inventory.all()
    ]


@app.get("/devices/{hostname}/plan")
def plan_device(hostname: str):
    device = inventory.get(hostname)
    if not device:
        raise HTTPException(status_code=404, detail=f"Unknown device: {hostname}")
    result = deployer.plan(device)
    return DeployResultOut(
        hostname=result.hostname, status=result.status.value, diff=result.diff,
        error=result.error, duration_ms=result.duration_ms,
    )


@app.post("/deploy", response_model=list[DeployResultOut])
def deploy(req: DeployRequest):
    if req.hostnames:
        devices = [inventory.get(h) for h in req.hostnames]
        missing = [h for h, d in zip(req.hostnames, devices) if d is None]
        if missing:
            raise HTTPException(status_code=404, detail=f"Unknown devices: {missing}")
    else:
        devices = inventory.all()

    results = deployer.apply_fleet(devices, dry_run=req.dry_run, max_failures=req.max_failures)
    logger.info("Deploy request processed: %s/%s devices attempted", len(results), len(devices))

    return [
        DeployResultOut(
            hostname=r.hostname, status=r.status.value, diff=r.diff,
            error=r.error, duration_ms=r.duration_ms,
        )
        for r in results
    ]


@app.get("/deploy/summary")
def deploy_summary():
    """Quick fleet drift check: how many devices currently differ from intended config."""
    results = [deployer.plan(d) for d in inventory.all()]
    drifted = [r.hostname for r in results if r.status == DeployStatus.DRY_RUN]
    failed = [r.hostname for r in results if r.status == DeployStatus.VALIDATION_FAILED]
    return {
        "total_devices": len(results),
        "in_sync": len(results) - len(drifted) - len(failed),
        "drifted": drifted,
        "validation_failed": failed,
    }
