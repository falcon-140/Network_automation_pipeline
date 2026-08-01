// Command healthcheck polls the network device fleet on an interval and
// exposes fleet health as JSON (/status) and Prometheus metrics (/metrics),
// so it can be scraped by Prometheus/Grafana or queried by on-call tooling.
package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"
)

func envOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envDurationOrDefault(key string, def time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return def
}

func main() {
	inventorySource := envOrDefault("INVENTORY_SOURCE", "file") // "file" or "api"
	inventoryFile := envOrDefault("INVENTORY_FILE", "devices.json")
	apiBaseURL := envOrDefault("CONFIG_API_URL", "http://localhost:8000")
	checkerMode := envOrDefault("CHECKER_MODE", "simulated") // "simulated" or "tcp"
	pollInterval := envDurationOrDefault("POLL_INTERVAL", 15*time.Second)
	listenAddr := envOrDefault("LISTEN_ADDR", ":9200")

	var devices []Device
	var err error
	if inventorySource == "api" {
		devices, err = LoadInventoryFromAPI(apiBaseURL)
	} else {
		devices, err = LoadInventoryFromFile(inventoryFile)
	}
	if err != nil {
		log.Fatalf("failed to load inventory: %v", err)
	}
	log.Printf("loaded %d devices from inventory source=%s", len(devices), inventorySource)

	var checker Checker
	if checkerMode == "tcp" {
		checker = NewTCPChecker(22, 2*time.Second)
	} else {
		checker = NewSimulatedChecker()
	}

	store := NewMetricsStore()
	for _, d := range devices {
		store.RegisterDevice(d)
	}

	// Initial synchronous pass so /status and /metrics have data immediately
	// on startup rather than returning empty results for the first interval.
	pollOnce(devices, checker, store)

	go func() {
		ticker := time.NewTicker(pollInterval)
		defer ticker.Stop()
		for range ticker.C {
			pollOnce(devices, checker, store)
		}
	}()

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ok\n"))
	})
	mux.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) {
		snap := store.Snapshot()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(snap)
	})
	mux.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		w.Write([]byte(store.RenderPrometheus()))
	})

	log.Printf("healthcheck service listening on %s (poll_interval=%s, checker=%s)",
		listenAddr, pollInterval, checkerMode)
	log.Fatal(http.ListenAndServe(listenAddr, mux))
}

func pollOnce(devices []Device, checker Checker, store *MetricsStore) {
	for _, d := range devices {
		result := checker.Check(d)
		store.Record(result)
		if !result.Reachable {
			log.Printf("WARN device down: hostname=%s error=%s", d.Hostname, result.Error)
		}
	}
}

// unused helper kept for CLI ergonomics if a fixed port override is desired later.
func mustAtoi(s string) int {
	n, err := strconv.Atoi(s)
	if err != nil {
		return 0
	}
	return n
}
