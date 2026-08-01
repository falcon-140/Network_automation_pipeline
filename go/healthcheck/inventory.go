package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"time"
)

// Device mirrors the subset of the Python inventory schema the health
// checker cares about. In production this is fetched from the Python
// config-management API's /devices endpoint so both services share a
// single source of truth; for local/CI runs it can be loaded from a
// static JSON file instead.
type Device struct {
	Hostname string `json:"hostname"`
	MgmtIP   string `json:"mgmt_ip"`
	Platform string `json:"platform"`
	Role     string `json:"role"`
	Site     string `json:"site"`
}

// LoadInventoryFromFile reads a JSON array of devices from disk.
func LoadInventoryFromFile(path string) ([]Device, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading inventory file %s: %w", path, err)
	}
	var devices []Device
	if err := json.Unmarshal(data, &devices); err != nil {
		return nil, fmt.Errorf("parsing inventory JSON: %w", err)
	}
	return devices, nil
}

// LoadInventoryFromAPI fetches the live device list from the Python
// config-management API (GET /devices), keeping the two services
// consistent without duplicating inventory data.
func LoadInventoryFromAPI(baseURL string) ([]Device, error) {
	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Get(baseURL + "/devices")
	if err != nil {
		return nil, fmt.Errorf("fetching inventory from API %s: %w", baseURL, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("inventory API returned status %d", resp.StatusCode)
	}

	var devices []Device
	if err := json.NewDecoder(resp.Body).Decode(&devices); err != nil {
		return nil, fmt.Errorf("decoding inventory API response: %w", err)
	}
	return devices, nil
}
