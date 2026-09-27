"""
Claude Kill Switch - Windows Core Enforcer & Daemon
Blocks Claude and Brave via Windows Firewall rules and process termination
unless the public exit IP matches allowed countries or allowed IPs.
Pure Python standard library - zero external dependencies!
"""
import os
import sys
import time
import json
import re
import urllib.request
import urllib.error
import ipaddress
import subprocess
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT_DIR, "config.env")
APPDATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ClaudeKillSwitch")
STATE_FILE = os.path.join(APPDATA_DIR, "state")
CACHE_FILE = os.path.join(APPDATA_DIR, "last_ok")
LOG_FILE = os.path.join(APPDATA_DIR, "claude-killswitch.log")

FIREWALL_RULE_NAME = "Claude Kill Switch Rule"

def ensure_dirs():
    os.makedirs(APPDATA_DIR, exist_ok=True)

def log(msg):
    ensure_dirs()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {msg}"
    print(entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass

def read_config():
    config = {
        "WG_TUNNEL_NAME": "",
        "REQUIRE_COUNTRIES": "TR,AE",
        "REQUIRE_CITIES": "",
        "ALLOWED_IPS": "",
        "REQUIRE_ASNS": "",
        "QUIT_CLAUDE_WHEN_UNSAFE": "1",
        "QUIT_BRAVE_WHEN_UNSAFE": "1",
        "USE_FIREWALL_BLOCK": "1",
        "CHECK_INTERVAL_SECONDS": "10"
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        config[k.strip()] = v.strip().strip('"').strip("'")
        except Exception as e:
            log(f"Error reading config: {e}")
    return config

def notify_windows(title, message):
    log(f"NOTIFY: {title} — {message}")
    # PowerShell balloon notification or sound alert
    try:
        ps_code = f"""
[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null
$notify = new-object system.windows.forms.notifyicon
$notify.icon = [System.Drawing.SystemIcons]::Information
$notify.visible = $true
$notify.showballoontip(4000, '{title}', '{message}', [system.windows.forms.tooltipicon]::Info)
Start-Sleep -Seconds 1
$notify.dispose()
"""
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_code],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def parse_geo_json(raw):
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except Exception:
        return None

    if isinstance(d, dict):
        if d.get("success") is False:
            return None
        if d.get("status") in (429, "fail", "error") or ("error" in d and not d.get("ip") and not d.get("query")):
            return None

    ip = d.get("ip") or d.get("query") or d.get("ipAddress") or ""
    city = d.get("city") or d.get("cityName") or ""
    country = d.get("countryCode") or d.get("country_code") or d.get("country_iso") or ""
    if not country:
        c = d.get("country") or ""
        country = c if len(str(c)) == 2 else c
    org = d.get("org") or d.get("as") or d.get("organization") or d.get("organization_name") or ""
    if isinstance(org, dict):
        org = org.get("asn") or org.get("name") or org.get("org") or ""
    conn = d.get("connection") if isinstance(d.get("connection"), dict) else {}
    asn_src = str(
        d.get("as") or org or d.get("asn") or
        (("AS" + str(conn["asn"])) if conn.get("asn") else "") or
        conn.get("org") or ""
    )
    asn_m = re.search(r"AS\d+", asn_src, re.I)
    asn = asn_m.group(0).upper() if asn_m else ""
    if not asn and str(d.get("asn", "")).isdigit():
        asn = "AS" + str(d.get("asn"))

    if not ip or not city or not country:
        return None

    return f"{ip}|{city}|{country}|{asn}"

def fetch_exit_geo():
    urls = [
        "https://ipwho.is/",
        "https://get.geojs.io/v1/ip/geo.json",
        "http://ip-api.com/json/?fields=status,message,country,countryCode,city,query,as",
        "https://ipinfo.io/json",
        "https://ipapi.co/json/"
    ]
    for url in urls:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read().decode("utf-8", errors="ignore")
                geo = parse_geo_json(data)
                if geo:
                    return geo
        except Exception:
            continue
    return None

def is_geo_allowed(geo_str, config):
    parts = geo_str.split("|")
    if len(parts) < 4:
        return False
    ip, city, country, asn = parts[0], parts[1], parts[2], parts[3]
    city_lower = city.lower()
    country_upper = country.upper()
    asn_upper = asn.upper()

    allowed_ips = [c.strip() for c in config.get("ALLOWED_IPS", "").split(",") if c.strip()]
    allowed_countries = [c.strip().upper() for c in config.get("REQUIRE_COUNTRIES", "").split(",") if c.strip()]
    allowed_cities = [c.strip().lower() for c in config.get("REQUIRE_CITIES", "").split(",") if c.strip()]
    allowed_asns = [c.strip().upper() for c in config.get("REQUIRE_ASNS", "").split(",") if c.strip()]

    # 1. IP direct whitelist
    if allowed_ips:
        try:
            cur_ip = ipaddress.ip_address(ip)
            for target in allowed_ips:
                try:
                    if "/" in target:
                        if cur_ip in ipaddress.ip_network(target, strict=False):
                            return True
                    else:
                        if cur_ip == ipaddress.ip_address(target):
                            return True
                except Exception:
                    continue
        except Exception:
            pass

    # 2. Country check
    if allowed_countries:
        if country_upper not in allowed_countries:
            return False

    # 3. City check (optional)
    if allowed_cities:
        city_ok = any(req in city_lower or city_lower in req for req in allowed_cities)
        if not city_ok:
            return False

    # 4. ASN check (optional)
    if allowed_asns:
        if asn_upper not in allowed_asns:
            return False

    return True

def set_windows_firewall_block(enable_block):
    """
    Enables or disables outbound blocking rules for Claude and Brave in Windows Defender Firewall.
    Uses netsh advfirewall.
    """
    targets = ["Claude.exe", "brave.exe"]
    for prog in targets:
        rule_name = f"KillSwitch_Block_{prog}"
        if enable_block:
            # Add or enable block rule
            cmd = f'netsh advfirewall firewall show rule name="{rule_name}" >nul 2>&1 || ' \
                  f'netsh advfirewall firewall add rule name="{rule_name}" dir=out action=block program="%ProgramFiles%\\{prog}" enable=yes'
            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # Delete block rule
            cmd = f'netsh advfirewall firewall delete rule name="{rule_name}"'
            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def kill_protected_apps(config):
    apps = []
    if config.get("QUIT_CLAUDE_WHEN_UNSAFE", "1") == "1":
        apps.append("Claude.exe")
    if config.get("QUIT_BRAVE_WHEN_UNSAFE", "1") == "1":
        apps.append("brave.exe")

    for app in apps:
        try:
            subprocess.run(["taskkill", "/F", "/IM", app, "/T"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log(f"Killed process {app}")
        except Exception:
            pass

def mark_safe(geo):
    ensure_dirs()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write("safe")
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        f.write(geo)
    set_windows_firewall_block(False)

def mark_unsafe(config):
    ensure_dirs()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write("unsafe")
    set_windows_firewall_block(True)
    kill_protected_apps(config)

def run_single_check():
    ensure_dirs()
    config = read_config()

    previous_state = "unknown"
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                previous_state = f.read().strip()
        except Exception:
            pass

    geo = fetch_exit_geo()
    if geo:
        if is_geo_allowed(geo, config):
            log(f"SAFE: {geo}")
            mark_safe(geo)
            if previous_state != "safe":
                notify_windows("Claude Kill Switch", f"Safe exit verified ({geo.split('|')[0]}) — Claude allowed")
            return "safe"
        else:
            log(f"UNSAFE: mismatch {geo}")
            mark_unsafe(config)
            if previous_state != "unsafe":
                notify_windows("Claude Kill Switch", "Exit IP not in allowed locations — Claude blocked")
            return "unsafe"
    else:
        # Check failed / ratelimit
        # Check cache freshness
        if os.path.exists(CACHE_FILE):
            age = time.time() - os.path.getmtime(CACHE_FILE)
            if age <= 300:
                with open(CACHE_FILE, "r") as f:
                    cached = f.read().strip()
                log(f"SAFE(cache): geo check unavailable, trusting recent OK ({cached})")
                mark_safe(cached)
                return "safe"

        log("UNSAFE: geo API unavailable and no fresh cache")
        mark_unsafe(config)
        if previous_state != "unsafe":
            notify_windows("Claude Kill Switch", "IP check unavailable — Claude blocked")
        return "unsafe"

def loop_daemon():
    print("Starting Claude Kill Switch Daemon on Windows...")
    while True:
        try:
            run_single_check()
        except Exception as e:
            log(f"Loop error: {e}")
        time.sleep(10)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        res = run_single_check()
        sys.exit(0 if res == "safe" else 1)
    else:
        loop_daemon()
