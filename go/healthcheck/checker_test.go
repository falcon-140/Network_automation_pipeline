package main

import (
	"strings"
	"testing"
)

func TestSimulatedCheckerReportsUpByDefault(t *testing.T) {
	checker := NewSimulatedChecker()
	d := Device{Hostname: "test-01", MgmtIP: "10.0.0.1"}
	result := checker.Check(d)

	if !result.Reachable {
		t.Fatalf("expected device to be reachable, got unreachable: %s", result.Error)
	}
	if result.LatencyMs <= 0 {
		t.Fatalf("expected positive latency, got %f", result.LatencyMs)
	}
}

func TestSimulatedCheckerReportsDownWhenConfigured(t *testing.T) {
	checker := NewSimulatedChecker()
	checker.Down["test-02"] = true
	d := Device{Hostname: "test-02", MgmtIP: "10.0.0.2"}
	result := checker.Check(d)

	if result.Reachable {
		t.Fatalf("expected device to be unreachable")
	}
	if result.Error == "" {
		t.Fatalf("expected an error message for unreachable device")
	}
}

func TestTCPCheckerFailsFastOnUnroutableAddress(t *testing.T) {
	// 192.0.2.0/24 is TEST-NET-1 (RFC 5737), guaranteed non-routable.
	checker := NewTCPChecker(22, 0) // 0 -> default 2s timeout
	d := Device{Hostname: "unreachable-host", MgmtIP: "192.0.2.1"}
	result := checker.Check(d)

	if result.Reachable {
		t.Fatalf("expected TEST-NET-1 address to be unreachable")
	}
}

func TestMetricsStoreRecordsChecksAndFailures(t *testing.T) {
	store := NewMetricsStore()
	d := Device{Hostname: "dev-01", Site: "sjc1", Role: "edge", Platform: "cisco_ios"}
	store.RegisterDevice(d)

	store.Record(CheckResult{Hostname: "dev-01", Reachable: true, LatencyMs: 3.5})
	store.Record(CheckResult{Hostname: "dev-01", Reachable: false, Error: "timeout"})

	snap := store.Snapshot()
	if len(snap) != 1 {
		t.Fatalf("expected 1 device in snapshot, got %d", len(snap))
	}
	s := snap[0]
	if s.ChecksTotal != 2 {
		t.Errorf("expected 2 total checks, got %d", s.ChecksTotal)
	}
	if s.FailuresTotal != 1 {
		t.Errorf("expected 1 failure, got %d", s.FailuresTotal)
	}
	if s.Up {
		t.Errorf("expected most recent state to be down")
	}
}

func TestRenderPrometheusIncludesExpectedMetricNames(t *testing.T) {
	store := NewMetricsStore()
	d := Device{Hostname: "dev-01", Site: "sjc1", Role: "edge", Platform: "cisco_ios"}
	store.RegisterDevice(d)
	store.Record(CheckResult{Hostname: "dev-01", Reachable: true, LatencyMs: 5.0})

	out := store.RenderPrometheus()
	for _, want := range []string{
		"network_device_up",
		"network_device_latency_ms",
		"network_device_checks_total",
		"network_device_failures_total",
		`hostname="dev-01"`,
	} {
		if !strings.Contains(out, want) {
			t.Errorf("expected output to contain %q, got:\n%s", want, out)
		}
	}
}

func TestLoadInventoryFromFile(t *testing.T) {
	devices, err := LoadInventoryFromFile("devices.json")
	if err != nil {
		t.Fatalf("unexpected error loading inventory: %v", err)
	}
	if len(devices) != 4 {
		t.Fatalf("expected 4 devices, got %d", len(devices))
	}
	if devices[0].Hostname != "edge-router-01" {
		t.Errorf("expected first device to be edge-router-01, got %s", devices[0].Hostname)
	}
}
