# Network Automation Pipeline

Config management, deployment orchestration, health monitoring, and observability
for a distributed network device fleet — built in **Python** (config engine + REST API)
and **Go** (health-check/monitoring service), with **GitHub Actions** CI/CD, **AWS**
backup/alerting, and a **Prometheus + Grafana** observability stack.

Conceptually analogous to an internal config-management / release-engineering system:
source-controlled intended state → render → validate → diff → roll out with a failure
budget → back up → monitor drift and reachability continuously.

```
                    ┌─────────────────────┐
  inventory.yaml ──▶│  Python Config Mgr   │──REST──▶  GitHub Actions
  (source of truth) │  render/validate/    │           (CI + deploy)
                     │  diff/deploy/rollback│                │
                     └──────────┬───────────┘                ▼
                                │ /devices                 AWS S3 (config
                                ▼                           backups) +
                     ┌─────────────────────┐               CloudWatch
                     │  Go Health Checker   │               (drift alarm)
                     │  poll / metrics      │
                     └──────────┬───────────┘
                                │ /metrics (Prometheus format)
                                ▼
                     Prometheus ──▶ Grafana dashboard + alerts
```

## Repo layout

```
python/
  config_manager/
    inventory.py      # device inventory model + YAML loader
    templates.py       # Jinja2 rendering, per-platform templates
    templates/*.j2      # cisco_ios / arista_eos / juniper_junos
    validator.py        # policy checks before anything is pushed
    deployer.py          # plan/diff/apply/rollback, fleet rollout w/ failure budget
    api.py                # FastAPI: /devices, /devices/{h}/plan, /deploy, /deploy/summary
  inventory/devices.yaml   # sample 4-device fleet (source of truth)
  tests/                    # 14 pytest cases
  Dockerfile

go/healthcheck/
  main.go              # polling loop + HTTP server
  checker.go            # Checker interface: TCPChecker (real) / SimulatedChecker (CI)
  metrics.go             # thread-safe store + hand-rolled Prometheus exposition
  inventory.go            # load device list from file or the Python API
  devices.json             # static inventory for local/CI runs
  checker_test.go           # 6 Go test cases
  Dockerfile

.github/workflows/
  ci.yml               # lint + test Python & Go, validate every rendered config
  deploy.yml            # PR: dry-run plan posted as diff. main: deploy + backup + drift metric

aws/
  backup_configs_to_s3.py    # versioned config backups (audit trail / DR)
  publish_drift_metric.py     # publishes FleetDriftedDevices to CloudWatch
  infrastructure.yaml          # CloudFormation: S3 bucket, SNS topic, drift alarm

observability/
  prometheus.yml        # scrape config
  alert_rules.yml         # device-down, high failure rate, high latency alerts
  grafana-dashboard.json   # fleet health dashboard

docker-compose.yml     # config-api + healthcheck + prometheus + grafana, one command
```

## Quickstart (local)

**Python config API**
```bash
cd python
pip install -r requirements.txt
uvicorn config_manager.api:app --reload
# GET  http://localhost:8000/devices
# GET  http://localhost:8000/devices/edge-router-01/plan
# POST http://localhost:8000/deploy   {"dry_run": true}
```

**Go health checker**
```bash
cd go/healthcheck
go run . 
# GET http://localhost:9200/status    (JSON fleet health)
# GET http://localhost:9200/metrics   (Prometheus format)
```

**Full stack (API + health checker + Prometheus + Grafana)**
```bash
docker compose up --build
# Grafana:    http://localhost:3000  (admin/admin)
# Prometheus: http://localhost:9090
```

## Running the tests

```bash
# Python — 14 tests
cd python && pip install -r requirements.txt && pytest tests/ -v

# Go — 6 tests
cd go/healthcheck && go test ./... -v -race -cover
```

Both suites are wired into `.github/workflows/ci.yml` and run on every PR, along
with a step that renders and validates the intended config for **every** device in
inventory so a bad template or policy violation fails the build before merge.

## Design decisions worth calling out

- **Pluggable transport, not a live-device dependency.** The Python `DeviceDeployer`
  talks to a `DeviceTransport` protocol; the Go checker talks to a `Checker` interface.
  Both ship a simulated implementation so the entire pipeline — render, validate, diff,
  push, rollback, poll, alert — is exercised in CI without lab hardware, and swapping in
  a real `netmiko`/`napalm` transport or TCP/SSH probe in production is a one-line change.
- **Fail-safe rollout.** `apply_fleet()` takes a `max_failures` budget and halts the
  rolling deployment once it's exceeded, and any push failure triggers an automatic
  rollback to the previously-known-good config rather than leaving a device half-configured.
- **Validation runs before anything touches a device.** The `validator` catches default
  SNMP communities, malformed IPs, and rendering mistakes (e.g. hostname mismatch) as a
  pre-deployment gate, both locally and as a required CI check.
- **Dependency-light Go service.** Prometheus exposition is hand-rolled instead of pulling
  in `client_golang`, so the health checker builds with only the standard library.
- **Two services, one source of truth.** The Go checker can load its device list from a
  static file (CI/local) or fetch it live from the Python API's `/devices` endpoint
  (production), so the fleet definition isn't duplicated and drifted between languages.

## What's simulated vs. what's real

This repo is fully runnable and tested end-to-end, but it doesn't have real network
hardware behind it. Anywhere that matters, there's a clearly-marked simulation boundary:
`DeviceSimulator` (Python) and `SimulatedChecker` (Go) stand in for actual SSH/API pushes
and reachability probes. Swapping either for a real backend (netmiko/napalm, or the
existing `TCPChecker`) doesn't change any of the surrounding pipeline logic — that's the
point of the abstraction.
# Network_automation_pipeline
