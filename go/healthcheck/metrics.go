package main

import (
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"
)

// deviceMetrics tracks the rolling health signal for a single device.
type deviceMetrics struct {
	Up            bool
	LatencyMs     float64
	ChecksTotal   uint64
	FailuresTotal uint64
	LastCheck     time.Time
	LastError     string
}

// MetricsStore is a concurrency-safe registry of per-device health metrics,
// updated by the polling loop and read by both the JSON /status endpoint
// and the Prometheus-format /metrics endpoint.
type MetricsStore struct {
	mu      sync.RWMutex
	devices map[string]*deviceMetrics
	// static labels per device, set once from inventory
	labels map[string]Device
}

func NewMetricsStore() *MetricsStore {
	return &MetricsStore{
		devices: make(map[string]*deviceMetrics),
		labels:  make(map[string]Device),
	}
}

func (m *MetricsStore) RegisterDevice(d Device) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, exists := m.devices[d.Hostname]; !exists {
		m.devices[d.Hostname] = &deviceMetrics{}
	}
	m.labels[d.Hostname] = d
}

func (m *MetricsStore) Record(result CheckResult) {
	m.mu.Lock()
	defer m.mu.Unlock()

	dm, exists := m.devices[result.Hostname]
	if !exists {
		dm = &deviceMetrics{}
		m.devices[result.Hostname] = dm
	}
	dm.ChecksTotal++
	dm.LastCheck = result.CheckedAt
	dm.Up = result.Reachable
	if result.Reachable {
		dm.LatencyMs = result.LatencyMs
		dm.LastError = ""
	} else {
		dm.FailuresTotal++
		dm.LastError = result.Error
	}
}

// Snapshot returns a point-in-time copy safe to serialize without holding the lock.
type Snapshot struct {
	Hostname      string
	Site          string
	Role          string
	Platform      string
	Up            bool
	LatencyMs     float64
	ChecksTotal   uint64
	FailuresTotal uint64
	LastCheck     time.Time
	LastError     string
}

func (m *MetricsStore) Snapshot() []Snapshot {
	m.mu.RLock()
	defer m.mu.RUnlock()

	out := make([]Snapshot, 0, len(m.devices))
	for hostname, dm := range m.devices {
		label := m.labels[hostname]
		out = append(out, Snapshot{
			Hostname:      hostname,
			Site:          label.Site,
			Role:          label.Role,
			Platform:      label.Platform,
			Up:            dm.Up,
			LatencyMs:     dm.LatencyMs,
			ChecksTotal:   dm.ChecksTotal,
			FailuresTotal: dm.FailuresTotal,
			LastCheck:     dm.LastCheck,
			LastError:     dm.LastError,
		})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Hostname < out[j].Hostname })
	return out
}

// RenderPrometheus writes the current state of all devices in Prometheus
// text exposition format (hand-rolled, no external client library needed —
// this is intentionally dependency-free so it builds anywhere with only
// the Go standard library).
func (m *MetricsStore) RenderPrometheus() string {
	snap := m.Snapshot()
	var b strings.Builder

	b.WriteString("# HELP network_device_up Whether the device responded to the last health check (1=up, 0=down)\n")
	b.WriteString("# TYPE network_device_up gauge\n")
	for _, s := range snap {
		up := 0
		if s.Up {
			up = 1
		}
		fmt.Fprintf(&b, "network_device_up{hostname=%q,site=%q,role=%q,platform=%q} %d\n",
			s.Hostname, s.Site, s.Role, s.Platform, up)
	}

	b.WriteString("# HELP network_device_latency_ms Round-trip latency of the last successful health check, in milliseconds\n")
	b.WriteString("# TYPE network_device_latency_ms gauge\n")
	for _, s := range snap {
		fmt.Fprintf(&b, "network_device_latency_ms{hostname=%q,site=%q} %.3f\n", s.Hostname, s.Site, s.LatencyMs)
	}

	b.WriteString("# HELP network_device_checks_total Total number of health checks performed against this device\n")
	b.WriteString("# TYPE network_device_checks_total counter\n")
	for _, s := range snap {
		fmt.Fprintf(&b, "network_device_checks_total{hostname=%q,site=%q} %d\n", s.Hostname, s.Site, s.ChecksTotal)
	}

	b.WriteString("# HELP network_device_failures_total Total number of failed health checks for this device\n")
	b.WriteString("# TYPE network_device_failures_total counter\n")
	for _, s := range snap {
		fmt.Fprintf(&b, "network_device_failures_total{hostname=%q,site=%q} %d\n", s.Hostname, s.Site, s.FailuresTotal)
	}

	return b.String()
}
