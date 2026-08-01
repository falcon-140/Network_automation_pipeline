#!/usr/bin/env python3
"""
publish_drift_metric.py

Queries the config-management API's /deploy/summary endpoint and publishes
the number of drifted devices as a CloudWatch custom metric
(NetworkAutomationPipeline / FleetDriftedDevices), which the CloudFormation
stack in infrastructure.yaml alarms on.

Usage:
    CONFIG_API_URL=http://localhost:8000 AWS_REGION=us-west-2 \
        python3 publish_drift_metric.py --environment production
"""
from __future__ import annotations

import argparse
import os
import sys

import boto3
import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.environ.get("CONFIG_API_URL", "http://localhost:8000"))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    parser.add_argument("--environment", default=os.environ.get("ENVIRONMENT", "production"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        resp = httpx.get(f"{args.api_url}/deploy/summary", timeout=10)
        resp.raise_for_status()
        summary = resp.json()
    except httpx.HTTPError as exc:
        print(f"ERROR: failed to fetch deploy summary from {args.api_url}: {exc}", file=sys.stderr)
        return 1

    drifted_count = len(summary["drifted"])
    print(f"Fleet drift check: {drifted_count} drifted / {summary['total_devices']} total devices")

    if args.dry_run:
        print("[dry-run] skipping CloudWatch publish")
        return 0

    cloudwatch = boto3.client("cloudwatch", region_name=args.region)
    cloudwatch.put_metric_data(
        Namespace="NetworkAutomationPipeline",
        MetricData=[
            {
                "MetricName": "FleetDriftedDevices",
                "Dimensions": [{"Name": "Environment", "Value": args.environment}],
                "Value": drifted_count,
                "Unit": "Count",
            }
        ],
    )
    print(f"Published FleetDriftedDevices={drifted_count} to CloudWatch (env={args.environment})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
