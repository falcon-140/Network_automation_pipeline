package main

import (
	"fmt"
	"net"
	"time"
)

// CheckResult captures the outcome of a single health probe against a device.
type CheckResult struct {
	Hostname   string
	Reachable  bool
	LatencyMs  float64
	Error      string
	CheckedAt  time.Time
}

// Checker abstracts how reachability is determined, so the same polling
// loop can run against real network gear (TCPChecker) or a deterministic
// SimulatedChecker in tests/CI without lab hardware.
type Checker interface {
	Check(d Device) CheckResult
}

// TCPChecker probes a management port (default 22, SSH) with a dial timeout.
// This is a lightweight, protocol-agnostic reachability signal that works
// across vendors without needing per-platform credentials.
type TCPChecker struct {
	Port    int
	Timeout time.Duration
}

func NewTCPChecker(port int, timeout time.Duration) *TCPChecker {
	if port == 0 {
		port = 22
	}
	if timeout == 0 {
		timeout = 2 * time.Second
	}
	return &TCPChecker{Port: port, Timeout: timeout}
}

func (c *TCPChecker) Check(d Device) CheckResult {
	start := time.Now()
	addr := fmt.Sprintf("%s:%d", d.MgmtIP, c.Port)

	conn, err := net.DialTimeout("tcp", addr, c.Timeout)
	latency := time.Since(start).Seconds() * 1000

	result := CheckResult{
		Hostname:  d.Hostname,
		LatencyMs: latency,
		CheckedAt: time.Now(),
	}
	if err != nil {
		result.Reachable = false
		result.Error = err.Error()
		return result
	}
	defer conn.Close()
	result.Reachable = true
	return result
}

// SimulatedChecker produces deterministic, injectable results so the
// polling loop, metrics aggregation, and API can be exercised in CI
// without any real network devices.
type SimulatedChecker struct {
	// Down lists hostnames that should report as unreachable.
	Down map[string]bool
	// LatencyMs is the simulated latency reported for reachable devices.
	LatencyMs float64
}

func NewSimulatedChecker() *SimulatedChecker {
	return &SimulatedChecker{Down: map[string]bool{}, LatencyMs: 4.2}
}

func (c *SimulatedChecker) Check(d Device) CheckResult {
	result := CheckResult{
		Hostname:  d.Hostname,
		CheckedAt: time.Now(),
	}
	if c.Down[d.Hostname] {
		result.Reachable = false
		result.Error = "simulated: device unreachable"
		return result
	}
	result.Reachable = true
	result.LatencyMs = c.LatencyMs
	return result
}
