#!/usr/bin/env python3
"""
macOS System Monitor - Local Web Server
Uses only native macOS tools: sysctl, vm_stat, top, powermetrics, smckit
Run: python3 server.py
Then open: http://localhost:5001
"""

import subprocess
import json
import re
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# ── Helpers ──────────────────────────────────────────────────────────────────

def run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def run_shell(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


# ── CPU ───────────────────────────────────────────────────────────────────────

def get_cpu():
    """Use top -l 2 (two samples so first is discarded) for accurate CPU%."""
    out = run_shell("top -l 2 -n 0 -s 1 2>/dev/null | grep 'CPU usage' | tail -1")
    # e.g. "CPU usage: 12.34% user, 5.67% sys, 82.00% idle"
    user = sys = idle = 0.0
    m = re.search(r'([\d.]+)%\s+user', out)
    if m: user = float(m.group(1))
    m = re.search(r'([\d.]+)%\s+sys', out)
    if m: sys = float(m.group(1))
    m = re.search(r'([\d.]+)%\s+idle', out)
    if m: idle = float(m.group(1))
    total = round(user + sys, 1)

    # Core count
    cores = int(run_shell("sysctl -n hw.logicalcpu") or "0")
    phys  = int(run_shell("sysctl -n hw.physicalcpu") or "0")

    # CPU model
    brand = run_shell("sysctl -n machdep.cpu.brand_string")
    if not brand:
        brand = run_shell("sysctl -n hw.model")

    return {
        "total": total,
        "user": round(user, 1),
        "sys": round(sys, 1),
        "idle": round(idle, 1),
        "cores_logical": cores,
        "cores_physical": phys,
        "brand": brand,
    }


# ── Memory ───────────────────────────────────────────────────────────────────

def get_memory():
    """Parse vm_stat and sysctl for memory stats."""
    page_size = int(run_shell("sysctl -n hw.pagesize") or "4096")
    total_bytes = int(run_shell("sysctl -n hw.memsize") or "0")

    vmstat = run_shell("vm_stat")
    def pages(key):
        m = re.search(rf'{key}:\s+(\d+)', vmstat)
        return int(m.group(1)) * page_size if m else 0

    free      = pages("Pages free")
    active    = pages("Pages active")
    inactive  = pages("Pages inactive")
    wired     = pages("Pages wired down")
    compressed= pages("Pages stored in compressor")
    # speculative = pages("Pages speculative")

    used = active + wired + compressed
    gb = 1024**3

    # Memory pressure via memory_pressure tool (fast, no sudo)
    pressure_out = run_shell("memory_pressure 2>/dev/null | head -5")
    pressure_pct = None
    m = re.search(r'System-wide memory free percentage:\s*([\d.]+)%', pressure_out)
    if m:
        pressure_pct = round(100 - float(m.group(1)), 1)

    # Swap
    swap_out = run_shell("sysctl -n vm.swapusage")
    swap_total = swap_used = swap_free = 0.0
    m = re.search(r'total = ([\d.]+)M', swap_out)
    if m: swap_total = float(m.group(1))
    m = re.search(r'used = ([\d.]+)M', swap_out)
    if m: swap_used = float(m.group(1))
    m = re.search(r'free = ([\d.]+)M', swap_out)
    if m: swap_free = float(m.group(1))

    return {
        "total_gb":      round(total_bytes / gb, 2),
        "used_gb":       round(used / gb, 2),
        "free_gb":       round(free / gb, 2),
        "active_gb":     round(active / gb, 2),
        "inactive_gb":   round(inactive / gb, 2),
        "wired_gb":      round(wired / gb, 2),
        "compressed_gb": round(compressed / gb, 2),
        "used_pct":      round(used / total_bytes * 100, 1) if total_bytes else 0,
        "pressure_pct":  pressure_pct,
        "swap_total_mb": swap_total,
        "swap_used_mb":  swap_used,
        "swap_free_mb":  swap_free,
    }


# ── Thermals & Fans ──────────────────────────────────────────────────────────

def get_thermals():
    """
    Multi-source thermal reader for macOS.

    Layer 1 — powermetrics (sudo):
      Parses CPU/GPU/ANE power (mW) and thermal pressure from cpu_power+thermal samplers.
      On Intel Macs (like MacBookPro18,x) powermetrics does NOT expose die temperatures,
      only power draw — so we display that instead.

    Layer 2 — smctemp (brew install smctemp):
      Lightweight SMC reader that outputs CPU temp directly. No sudo needed.

    Layer 3 — osx-cpu-temp (brew install osx-cpu-temp):
      Another simple SMC tool: outputs a single line like "58.2°C".

    Layer 4 — istats gem (gem install iStats):
      Ruby gem that reads SMC sensors comprehensively.

    Fans are read via smctemp -l, istats, or powermetrics.
    """
    sensors = {}
    fans = []
    source_parts = []
    note = ""

    # ── Layer 1: powermetrics for power draw + thermal pressure ──────────────
    pm = run_shell(
        "sudo -n powermetrics --samplers cpu_power,thermal -n 1 -i 1000 2>/dev/null",
        timeout=12
    )
    if pm:
        for line in pm.splitlines():
            line = line.strip()

            # Power readings: "CPU Power: 1768 mW"
            m = re.match(r'(CPU|GPU|ANE|Combined[^:]*)\s+Power\s*:\s*([\d.]+)\s*mW', line, re.IGNORECASE)
            if m:
                key = m.group(1).strip() + " Power (mW)"
                sensors[key] = float(m.group(2))
                continue

            # Thermal pressure: "Current pressure level: Nominal"
            m = re.match(r'Current pressure level:\s*(\w+)', line, re.IGNORECASE)
            if m:
                sensors["Thermal Pressure"] = m.group(1)
                continue
            # Older format: "Thermal pressure: Nominal"
            m = re.match(r'Thermal pressure:\s*(\w+)', line, re.IGNORECASE)
            if m:
                sensors["Thermal Pressure"] = m.group(1)
                continue

            # Die temps if present (Apple Silicon / newer Intel firmwares)
            m = re.match(r'(.+?(?:die temperature|temperature))\s*:\s*([\d.]+)\s*C', line, re.IGNORECASE)
            if m:
                sensors[m.group(1).strip()] = float(m.group(2))
                continue

            # Fan lines: "Fan: 1842 rpm" / "Fan 0: 1842 rpm"
            mf = re.match(r'Fan\s*(\d*)\s*:\s*([\d.]+)\s*rpm', line, re.IGNORECASE)
            if mf:
                fan_id = int(mf.group(1)) if mf.group(1).strip() else len(fans)
                fans.append({"id": fan_id, "rpm": float(mf.group(2))})

        if sensors:
            source_parts.append("powermetrics")

    # ── Layer 2: smctemp ─────────────────────────────────────────────────────
    smctemp = run_shell("smctemp 2>/dev/null", timeout=4)
    if smctemp:
        # Default output: just a number like "58.2"
        m = re.search(r'([\d.]+)', smctemp)
        if m:
            sensors["CPU Temp"] = float(m.group(1))
            source_parts.append("smctemp")

        # smctemp -l lists all sensors and fans
        smctemp_l = run_shell("smctemp -l 2>/dev/null", timeout=4)
        for line in smctemp_l.splitlines():
            # "TC0P  58.2  CPU 0 Proximity"
            m = re.match(r'(\w+)\s+([\d.]+)\s+(.+)', line)
            if m:
                key_code = m.group(1)
                val = float(m.group(2))
                label = m.group(3).strip()
                if "fan" in label.lower() or key_code.startswith("F"):
                    fans.append({"id": len(fans), "rpm": val, "name": label})
                elif val > 0:
                    sensors[label or key_code] = val

    # ── Layer 3: osx-cpu-temp ────────────────────────────────────────────────
    if "CPU Temp" not in sensors:
        oct_out = run_shell("osx-cpu-temp 2>/dev/null", timeout=4)
        if oct_out:
            m = re.search(r'([\d.]+)\s*[°C]', oct_out)
            if m:
                sensors["CPU Temp"] = float(m.group(1))
                source_parts.append("osx-cpu-temp")

    # ── Layer 4: istats gem ──────────────────────────────────────────────────
    if "CPU Temp" not in sensors:
        istats = run_shell("istats all 2>/dev/null", timeout=6)
        if istats and "°C" in istats:
            for line in istats.splitlines():
                m = re.search(r'^(.+?):\s+([\d.]+)\s*°C', line)
                if m:
                    sensors[m.group(1).strip()] = float(m.group(2))
                mf = re.search(r'^(.+?fan.+?):\s+([\d.]+)\s*RPM', line, re.IGNORECASE)
                if mf and not any(f.get("name") == mf.group(1).strip() for f in fans):
                    fans.append({"id": len(fans), "name": mf.group(1).strip(), "rpm": float(mf.group(2))})
            if any(isinstance(v, float) for v in sensors.values()):
                source_parts.append("istats")

    # ── Build note if nothing useful found ───────────────────────────────────
    has_temp = any(isinstance(v, float) for v in sensors.values())
    if not has_temp and not fans:
        note = (
            "No temperature sensors found. "
            "Install one of these for CPU temp: "
            "brew install smctemp  |  brew install osx-cpu-temp  |  gem install iStats"
        )

    source = ", ".join(source_parts) if source_parts else "unavailable"
    return {"sensors": sensors, "fans": fans, "source": source, "note": note}


# ── Disk ─────────────────────────────────────────────────────────────────────

def get_disk():
    out = run_shell("df -H / 2>/dev/null")
    lines = out.splitlines()
    if len(lines) < 2:
        return {}
    parts = lines[1].split()
    # Filesystem Size Used Avail Capacity Mounted
    return {
        "filesystem": parts[0] if len(parts) > 0 else "",
        "size":       parts[1] if len(parts) > 1 else "",
        "used":       parts[2] if len(parts) > 2 else "",
        "avail":      parts[3] if len(parts) > 3 else "",
        "capacity":   parts[4] if len(parts) > 4 else "",
    }


# ── Network ──────────────────────────────────────────────────────────────────

_prev_net = {}

# Prefixes to always skip — virtual/tunnel/internal interfaces
_SKIP_PREFIXES = (
    "lo", "utun", "awdl", "llw", "bridge", "p2p",
    "gif", "stf", "XHC", "ap1", "anpi", "vmnet",
)

def get_network():
    global _prev_net
    import time

    # Use `route get default` to find the primary active interface
    default_iface = run_shell("route get default 2>/dev/null | awk '/interface:/{print $2}'")

    out = run_shell("netstat -ib 2>/dev/null")
    ifaces = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 10:
            continue
        name = parts[0]

        # Skip virtual/tunnel interfaces
        if any(name.startswith(p) for p in _SKIP_PREFIXES):
            continue

        try:
            ibytes = int(parts[6])
            obytes = int(parts[9])
        except (ValueError, IndexError):
            continue

        # Only keep interfaces that have ever moved data
        if ibytes == 0 and obytes == 0:
            continue

        # Deduplicate (netstat lists an interface once per address)
        if name not in ifaces:
            ifaces[name] = {"in": ibytes, "out": obytes}

    # If we found a default route interface, keep only that one.
    # Otherwise keep all interfaces that passed the filters above.
    if default_iface and default_iface in ifaces:
        ifaces = {default_iface: ifaces[default_iface]}

    now = time.time()
    rates = {}
    for name, cur in ifaces.items():
        if name in _prev_net:
            dt = now - _prev_net[name]["t"]
            if dt > 0:
                rates[name] = {
                    "in_kbps":  round((cur["in"]  - _prev_net[name]["in"])  / dt / 1024, 1),
                    "out_kbps": round((cur["out"] - _prev_net[name]["out"]) / dt / 1024, 1),
                }
        _prev_net[name] = {"in": cur["in"], "out": cur["out"], "t": now}

    return rates


# ── Uptime & Load ────────────────────────────────────────────────────────────

def get_system():
    uptime = run_shell("uptime")
    load_m = re.search(r'load averages?:\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)', uptime)
    load = [float(load_m.group(i)) for i in (1,2,3)] if load_m else [0,0,0]

    uptime_m = re.search(r'up\s+(.*?),\s+\d+ user', uptime)
    up_str = uptime_m.group(1).strip() if uptime_m else ""

    hostname = run_shell("hostname -s")
    macos_ver = run_shell("sw_vers -productVersion")
    macos_name = run_shell("sw_vers -productName")

    return {
        "hostname": hostname,
        "macos": f"{macos_name} {macos_ver}",
        "uptime": up_str,
        "load_1":  load[0],
        "load_5":  load[1],
        "load_15": load[2],
    }


# ── HTTP Handler ─────────────────────────────────────────────────────────────

DASHBOARD_HTML = open(
    os.path.join(os.path.dirname(__file__), "index.html"), "r"
).read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress default logging

    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/" or path == "/index.html":
            body = DASHBOARD_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/api/metrics":
            try:
                data = {
                    "cpu":     get_cpu(),
                    "memory":  get_memory(),
                    "thermals":get_thermals(),
                    "disk":    get_disk(),
                    "network": get_network(),
                    "system":  get_system(),
                }
                self.send_json(data)
            except Exception as e:
                self.send_json({"error": str(e)})

        else:
            self.send_response(404)
            self.end_headers()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    PORT = 5001
    print(f"\n  Canary — macOS System Monitor")
    print(f"  ─────────────────────────────────────────")
    print(f"  Server running at  http://localhost:{PORT}")
    print(f"  Press Ctrl+C to stop\n")
    if os.geteuid() != 0:
        print("  ⚠  Not running as root — thermal/fan data may be unavailable.")
        print("     For full sensor data, restart with: sudo python3 server.py\n")
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")