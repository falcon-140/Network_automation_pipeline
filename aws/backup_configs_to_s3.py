#!/usr/bin/env python3
"""
backup_configs_to_s3.py

Renders the intended config for every device in inventory and uploads it to
S3 as an audit trail / disaster-recovery backup, keyed by timestamp so every
deployment run is independently retrievable:

    s3://<bucket>/configs/<hostname>/<YYYY-MM-DDTHHMMSSZ>.cfg
    s3://<bucket>/configs/<hostname>/latest.cfg

Run from CI (see .github/workflows/deploy.yml) after a successful deploy,
or standalone for a point-in-time config snapshot.

Usage:
    AWS_REGION=us-west-2 CONFIG_BACKUP_BUCKET=my-bucket \
        python3 backup_configs_to_s3.py --inventory ../python/inventory/devices.yaml
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import boto3
from botocore.exceptions import ClientError

from config_manager import Inventory, ConfigRenderer


def upload_config(s3_client, bucket: str, hostname: str, config_text: str, timestamp: str) -> None:
    versioned_key = f"configs/{hostname}/{timestamp}.cfg"
    latest_key = f"configs/{hostname}/latest.cfg"

    for key in (versioned_key, latest_key):
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=config_text.encode("utf-8"),
            ContentType="text/plain",
            Metadata={"hostname": hostname, "generated_at": timestamp},
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", default="../python/inventory/devices.yaml")
    parser.add_argument("--bucket", default=os.environ.get("CONFIG_BACKUP_BUCKET"))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    parser.add_argument("--dry-run", action="store_true", help="Render configs but skip the S3 upload")
    args = parser.parse_args()

    if not args.bucket and not args.dry_run:
        print("ERROR: --bucket or CONFIG_BACKUP_BUCKET env var is required (or pass --dry-run)", file=sys.stderr)
        return 1

    inventory = Inventory.from_yaml(args.inventory)
    renderer = ConfigRenderer()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")

    s3 = None if args.dry_run else boto3.client("s3", region_name=args.region)

    failures = 0
    for device in inventory.all():
        try:
            config_text = renderer.render(device)
        except Exception as exc:
            print(f"FAIL render {device.hostname}: {exc}", file=sys.stderr)
            failures += 1
            continue

        if args.dry_run:
            print(f"[dry-run] would upload {len(config_text)} bytes for {device.hostname}")
            continue

        try:
            upload_config(s3, args.bucket, device.hostname, config_text, timestamp)
            print(f"OK  s3://{args.bucket}/configs/{device.hostname}/{timestamp}.cfg")
        except ClientError as exc:
            print(f"FAIL upload {device.hostname}: {exc}", file=sys.stderr)
            failures += 1

    if failures:
        print(f"\n{failures} device(s) failed to back up", file=sys.stderr)
        return 1

    print(f"\nBacked up {len(inventory)} device configs to s3://{args.bucket}/configs/ (dry_run={args.dry_run})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
