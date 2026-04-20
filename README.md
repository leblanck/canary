# Canary — macOS System Monitor

A lightweight, local-only system performance dashboard for macOS. No Electron, no npm, no cloud — just a small Python server that reads native macOS tools and serves a live-updating web UI to your browser.

![Dashboard preview showing CPU, memory, thermal, fan, disk, and network panels in a dark Gruvbox theme]

---

## Features

- **CPU** — total, user, and system usage with 60-second rolling history chart
- **Memory** — used/free breakdown, wired/active/inactive/compressed stack, swap, and memory pressure
- **Thermal Sensors** — CPU die temperature (or power draw on Intel), thermal pressure level, and temperature history chart
- **Fans** — live RPM readout per fan
- **Disk** — usage and availability for the root volume
- **Network** — live KB/s in and out for your active interface only
- **System Info** — hostname, macOS version, uptime, and load averages

All data is sourced from native macOS tools: `top`, `vm_stat`, `sysctl`, `powermetrics`, `netstat`, `df`, and `route`. Nothing is sent anywhere — the server binds to `127.0.0.1` only.

---

## Requirements

### System
- macOS (tested on macOS Sequoia, Intel MacBookPro18,x)
- Python 3 — ships with macOS, no installation needed

### For temperature sensor data (pick one)

On Intel Macs, `powermetrics` exposes power draw (mW) but not die temperatures directly. A small third-party SMC reader is needed for actual °C readings:

**Option A — `osx-cpu-temp` (recommended, simplest):**
```bash
brew install osx-cpu-temp
```

**Option B — `smctemp`:**
```bash
brew install smctemp
```

**Option C — `iStats` Ruby gem:**
```bash
gem install iStats
```

The server tries each of these in order and uses whichever is available. If none are installed, the thermal panel will still show CPU/GPU power draw (mW) and thermal pressure level from `powermetrics`.

> **Homebrew** — if you don't have it: https://brew.sh

---

## Installation

No installation required. Just clone or download the two files and keep them in the same folder:

```
macos-monitor/
├── server.py
└── index.html
```

---

## Running

### Basic (CPU, memory, disk, network — no thermal/fan data)
```bash
python3 server.py
```

### Full (includes thermal sensors and fan RPM via powermetrics)
```bash
sudo python3 server.py
```

Then open your browser to:
```
http://localhost:5001
```

The dashboard polls for new data every 2 seconds. Press `Ctrl+C` in the terminal to stop the server.

---

## Why sudo?

Fan RPM and thermal pressure data come from `powermetrics`, which is an Apple tool that requires root privileges. The server uses `sudo -n` (non-interactive) so it will never prompt for a password mid-run — you just need to launch the server itself with `sudo`.

If you'd rather not use sudo, install `osx-cpu-temp` or `iStats` (see above) — those tools read SMC data without elevated privileges and the server will fall back to them automatically.

---

## Data Sources

| Panel | Tool | sudo required |
|---|---|---|
| CPU usage | `top` | No |
| Memory | `vm_stat`, `sysctl` | No |
| Memory pressure | `memory_pressure` | No |
| Disk | `df` | No |
| Network | `netstat`, `route` | No |
| Thermal pressure + power | `powermetrics` | Yes |
| CPU temperature | `osx-cpu-temp` / `smctemp` / `iStats` | No |
| Fan RPM | `powermetrics` / `iStats` | Yes / No |
| System info | `sysctl`, `sw_vers`, `uptime` | No |

---

## Troubleshooting

**Thermal panel shows "No temperature sensors found"**
Install one of the SMC reader tools listed above. `brew install osx-cpu-temp` is the quickest fix.

**Thermal panel shows power (mW) but no °C**
This is expected on Intel Macs when running without an SMC tool installed. `powermetrics` on Intel exposes power draw but not die temperatures. Install `osx-cpu-temp` to get °C readings.

**Network panel is empty or showing wrong interface**
The server uses `route get default` to identify your active interface. If you're on a VPN or unusual network configuration this may not resolve correctly. Check which interface is active with:
```bash
route get default | grep interface
```

**Port 5001 already in use**
Change the `PORT` variable near the bottom of `server.py`:
```python
PORT = 5002  # or any available port
```

**"Operation not permitted" when running with sudo**
On some macOS versions, SIP (System Integrity Protection) may block `powermetrics` even with sudo in certain terminal environments. Try running from Terminal.app directly rather than an IDE terminal.

---

## Notes

- The server binds exclusively to `127.0.0.1` — it is not accessible from other devices on your network
- No data is logged, stored, or transmitted anywhere
- The frontend uses [Chart.js](https://www.chartjs.org/) loaded from cdnjs (requires internet on first load); after that, charts render from in-memory data only
- Color theme is [Gruvbox Dark](https://github.com/morhetz/gruvbox)
- Font is [IBM Plex Mono](https://fonts.google.com/specimen/IBM+Plex+Mono) via Google Fonts (requires internet on first load)