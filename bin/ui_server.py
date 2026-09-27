#!/usr/bin/env python3
"""
Claude Kill Switch Dashboard & API Server
Runs locally with zero external dependencies (pure Python 3 standard library).
"""
import os
import sys
import json
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import socket

PORT = 54321
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(PROJECT_DIR, "config.env")
IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:
    APPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    STATE_DIR = os.path.join(APPDATA, "ClaudeKillSwitch")
    LOG_FILE = os.path.join(STATE_DIR, "claude-killswitch.log")
else:
    STATE_DIR = os.path.expanduser("~/Library/Application Support/claude-istanbul-killswitch")
    LOG_FILE = os.path.expanduser("~/Library/Logs/claude-istanbul-killswitch.log")

STATE_FILE = os.path.join(STATE_DIR, "state")
CACHE_FILE = os.path.join(STATE_DIR, "last_ok")

def read_config():
    config = {
        "WG_TUNNEL_NAME": "nima3",
        "REQUIRE_COUNTRIES": "TR,AE",
        "REQUIRE_CITIES": "Istanbul,Dubai,Abu Dhabi",
        "ALLOWED_IPS": "",
        "REQUIRE_ASNS": "",
        "QUIT_CLAUDE_WHEN_UNSAFE": "1",
        "QUIT_BRAVE_WHEN_UNSAFE": "1",
        "USE_LITTLE_SNITCH": "1",
        "NOTIFY_ON_CHANGE": "1",
        "CHECK_INTERVAL_SECONDS": "10",
        "LS_RULE_GROUP": "Claude Kill Switch"
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    config[key] = val
    return config

def write_config(new_config):
    existing_lines = []
    keys_written = set()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    updated_lines = []
    for line in existing_lines:
        trimmed = line.strip()
        if trimmed and not trimmed.startswith("#") and "=" in trimmed:
            key = trimmed.split("=", 1)[0].strip()
            if key in new_config:
                updated_lines.append(f'{key}="{new_config[key]}"\n')
                keys_written.add(key)
                continue
        updated_lines.append(line)

    for k, v in new_config.items():
        if k not in keys_written:
            updated_lines.append(f'{k}="{v}"\n')

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.writelines(updated_lines)

def get_live_status():
    config = read_config()
    tunnel_name = config.get("WG_TUNNEL_NAME", "nima3")

    # WireGuard status via scutil
    scutil_res = "Disconnected"
    iface = ""
    try:
        sc = subprocess.run(["/usr/sbin/scutil", "--nc", "status", tunnel_name],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
        if sc.stdout:
            lines = sc.stdout.strip().splitlines()
            if lines:
                scutil_res = lines[0].strip()
            for line in lines:
                if "InterfaceName" in line and ":" in line:
                    iface = line.split(":", 1)[1].strip()
    except Exception as e:
        scutil_res = str(e)

    # State file
    state = "unknown"
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = f.read().strip()
        except Exception:
            pass

    # Last OK cache
    last_ok = ""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                last_ok = f.read().strip()
        except Exception:
            pass

    # Recent log lines
    recent_logs = []
    if os.path.exists(LOG_FILE):
        try:
            p = subprocess.run(["tail", "-n", "20", LOG_FILE],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2)
            if p.stdout:
                recent_logs = [l for l in p.stdout.strip().splitlines() if l.strip()]
        except Exception:
            pass

    # Little snitch group status
    ls_enabled = None
    if config.get("USE_LITTLE_SNITCH") == "1":
        ls_cli = config.get("LS_CLI", "/Applications/Little Snitch.app/Contents/Components/littlesnitch")
        if os.path.exists(ls_cli):
            try:
                res = subprocess.run(["/usr/bin/sudo", "-n", ls_cli, "rulegroup"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2)
                group_name = config.get("LS_RULE_GROUP", "Claude Kill Switch")
                for l in res.stdout.splitlines():
                    if group_name in l:
                        ls_enabled = "enabled" in l
                        break
            except Exception:
                pass

    return {
        "tunnel_name": tunnel_name,
        "wg_connected": scutil_res == "Connected",
        "wg_status": scutil_res,
        "iface": iface,
        "state": state,
        "last_ok": last_ok,
        "config": config,
        "recent_logs": recent_logs,
        "ls_enabled": ls_enabled
    }

def run_enforce_now():
    if IS_WINDOWS:
        win_enforce = os.path.join(PROJECT_DIR, "windows", "enforce_windows.py")
        try:
            res = subprocess.run([sys.executable, win_enforce, "--once"],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
            return {"success": res.returncode == 0, "output": res.stdout + res.stderr}
        except Exception as e:
            return {"success": False, "error": str(e)}
    else:
        enforce_bin = os.path.join(PROJECT_DIR, "bin", "enforce.sh")
        if os.path.exists(enforce_bin):
            try:
                res = subprocess.run([enforce_bin], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
                return {"success": res.returncode == 0, "output": res.stdout + res.stderr}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "enforce.sh not found"}

HTML_PAGE = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Claude Kill Switch Manager</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #3b82f6;
      --accent-hover: #2563eb;
      --safe: #10b981;
      --safe-bg: rgba(16, 185, 129, 0.15);
      --unsafe: #ef4444;
      --unsafe-bg: rgba(239, 68, 68, 0.15);
      --tag-bg: #334155;
    }
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Vazirmatn", "Sahel", sans-serif;
    }
    body {
      background-color: var(--bg);
      color: var(--text);
      padding: 24px 16px;
      display: flex;
      justify-content: center;
      min-height: 100vh;
    }
    .container {
      width: 100%;
      max-width: 820px;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      padding: 18px 24px;
      border-radius: 16px;
    }
    .header-left h1 {
      font-size: 1.35rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .header-left p {
      color: var(--text-muted);
      font-size: 0.85rem;
      margin-top: 4px;
    }
    .status-badge {
      padding: 8px 18px;
      border-radius: 9999px;
      font-weight: 600;
      font-size: 0.95rem;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.3s;
    }
    .status-safe {
      background: var(--safe-bg);
      color: var(--safe);
      border: 1px solid var(--safe);
    }
    .status-unsafe {
      background: var(--unsafe-bg);
      color: var(--unsafe);
      border: 1px solid var(--unsafe);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .card-title {
      font-size: 0.95rem;
      color: var(--text-muted);
      font-weight: 600;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .card-value {
      font-size: 1.25rem;
      font-weight: 700;
      direction: ltr;
      text-align: right;
    }
    .section-title {
      font-size: 1.1rem;
      font-weight: 700;
      margin-bottom: 4px;
    }
    .quick-toggles {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    .btn-toggle {
      background: var(--tag-bg);
      border: 1px solid var(--card-border);
      color: var(--text);
      padding: 8px 16px;
      border-radius: 10px;
      cursor: pointer;
      font-size: 0.9rem;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s;
    }
    .btn-toggle.active {
      background: #1d4ed8;
      border-color: #3b82f6;
      color: #fff;
    }
    .btn-toggle:hover {
      filter: brightness(1.2);
    }
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    label {
      font-size: 0.85rem;
      color: var(--text-muted);
    }
    input[type="text"] {
      background: #0f172a;
      border: 1px solid var(--card-border);
      color: #fff;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 0.9rem;
      direction: ltr;
      outline: none;
      transition: border-color 0.2s;
    }
    input[type="text"]:focus {
      border-color: var(--accent);
    }
    .helper-text {
      font-size: 0.75rem;
      color: var(--text-muted);
    }
    .btn-primary {
      background: var(--accent);
      color: white;
      border: none;
      padding: 12px 20px;
      border-radius: 10px;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.2s;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
    }
    .btn-primary:hover {
      background: var(--accent-hover);
    }
    .btn-secondary {
      background: #334155;
      color: white;
      border: none;
      padding: 10px 16px;
      border-radius: 8px;
      font-size: 0.85rem;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
    }
    .btn-secondary:hover {
      background: #475569;
    }
    .actions-bar {
      display: flex;
      gap: 12px;
      justify-content: flex-end;
    }
    .log-box {
      background: #090d16;
      border: 1px solid #1e293b;
      border-radius: 10px;
      padding: 12px;
      font-family: "SF Mono", Monaco, Menlo, Consolas, monospace;
      font-size: 0.78rem;
      max-height: 180px;
      overflow-y: auto;
      direction: ltr;
      color: #94a3b8;
      line-height: 1.5;
    }
    .log-entry {
      white-space: pre-wrap;
      word-break: break-all;
    }
    .log-entry.safe {
      color: #34d399;
    }
    .log-entry.unsafe {
      color: #f87171;
    }
    .pulse-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: currentColor;
      box-shadow: 0 0 10px currentColor;
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="header-left">
        <h1>🔒 Claude Kill Switch</h1>
        <p>مدیریت هوشمند خروجی امن کلاد و برِیو</p>
      </div>
      <div id="statusBadge" class="status-badge status-unsafe">
        <span class="pulse-dot"></span>
        <span id="statusText">در حال دریافت...</span>
      </div>
    </div>

    <!-- Stats Grid -->
    <div class="grid">
      <div class="card">
        <div class="card-title">WireGuard Tunnel</div>
        <div class="card-value" id="wgStatus">—</div>
        <span class="helper-text" id="wgIface">Interface: —</span>
      </div>
      <div class="card">
        <div class="card-title">IP فعلی / خروجی</div>
        <div class="card-value" id="ipValue" style="font-size: 1.05rem;">—</div>
        <span class="helper-text" id="geoValue">لوکیشن: —</span>
      </div>
      <div class="card">
        <div class="card-title">Little Snitch Block</div>
        <div class="card-value" id="lsStatus" style="font-size: 1.05rem;">—</div>
        <span class="helper-text" id="lsDetail">گروه قوانین شبکه</span>
      </div>
    </div>

    <!-- Quick Location Selection & IP Allowlist -->
    <div class="card">
      <div class="section-title">🌍 لوکیشن‌ها و کشورهای مجاز</div>
      <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 8px;">
        کشورهایی که در صورت اتصال به آن‌ها، کلاینت Claude و Brave مجاز به فعالیت هستند:
      </p>
      <div class="quick-toggles">
        <button type="button" class="btn-toggle" id="btnTR" onclick="toggleCountry('TR')">
          🇹🇷 ترکیه (تمام شهرها)
        </button>
        <button type="button" class="btn-toggle" id="btnAE" onclick="toggleCountry('AE')">
          🇦🇪 امارات (تمام شهرها)
        </button>
        <button type="button" class="btn-toggle" id="btnDE" onclick="toggleCountry('DE')">
          🇩🇪 آلمان (تمام شهرها)
        </button>
        <button type="button" class="btn-toggle" id="btnNL" onclick="toggleCountry('NL')">
          🇳🇱 هلند (تمام شهرها)
        </button>
        <button type="button" class="btn-toggle" id="btnUS" onclick="toggleCountry('US')">
          🇺🇸 آمریکا (تمام شهرها)
        </button>
        <button type="button" class="btn-toggle" id="btnGB" onclick="toggleCountry('GB')">
          🇬🇧 انگلیس (تمام شهرها)
        </button>
      </div>

      <div style="margin-top: 14px; display: flex; flex-direction: column; gap: 12px;">
        <div class="form-group">
          <label>کدهای کشور مجاز (با کاما جدا کنید - هر کشوری بگذارید تمام شهرهایش مجاز خواهد بود):</label>
          <input type="text" id="inputCountries" placeholder="TR,AE">
        </div>
        <div class="form-group">
          <label>محدودسازی به شهرهای خاص (کاملاً اختیاری - اگر خالی باشد همه شهرهای آن کشورها آزاد است):</label>
          <input type="text" id="inputCities" placeholder="خالی بگذارید تا تمام شهرها آزاد باشند">
        </div>
      </div>
    </div>

    <div class="card">
      <div class="section-title">🎯 لیست سفید IPهای اختصاصی (IP Allowlist)</div>
      <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 8px;">
        اگر سرور خصوصی یا IP ثابت دارید، مستقیماً وارد کنید (بدون وابستگی به شهر/کشور، بلافاصله مجاز شناخته می‌شود):
      </p>
      <div class="form-group">
        <label>IPها یا رنج‌های CIDR مجاز (با کاما جدا کنید):</label>
        <input type="text" id="inputAllowedIPs" placeholder="مثال: 185.123.45.67, 194.26.192.0/24">
        <span class="helper-text">اگر خروجی تونل یکی از این IPها باشد، کلاد باز خواهد ماند.</span>
      </div>
    </div>

    <div class="card">
      <div class="section-title">⚙️ تنظیمات تونل و سیستم</div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
        <div class="form-group">
          <label>نام کانکشن WireGuard:</label>
          <input type="text" id="inputTunnelName" placeholder="nima3">
        </div>
        <div class="form-group">
          <label>ASNهای مجاز (اختیاری):</label>
          <input type="text" id="inputAllowedASNs" placeholder="مثال: AS44382">
        </div>
      </div>

      <div class="actions-bar" style="margin-top: 10px;">
        <button class="btn-secondary" onclick="runCheckNow()">⚡ تست و بررسی لحظه‌ای</button>
        <button class="btn-primary" onclick="saveSettings()">💾 ذخیره تنظیمات</button>
      </div>
    </div>

    <!-- Live Logs -->
    <div class="card">
      <div class="card-title">
        <span>📜 آخرین لاگ‌های Kill Switch</span>
        <button class="btn-secondary" style="padding: 4px 10px; font-size: 0.75rem;" onclick="fetchStatus()">بروزرسانی لاگ</button>
      </div>
      <div class="log-box" id="logBox">در حال بارگذاری لاگ...</div>
    </div>
  </div>

  <script>
    let currentConfig = {};
    let formInitialized = false;

    async function fetchStatus() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        currentConfig = data.config || {};
        updateUI(data);
      } catch (err) {
        console.error("Error fetching status:", err);
      }
    }

    function updateUI(data) {
      const isSafe = data.state === 'safe';
      const badge = document.getElementById('statusBadge');
      const statusText = document.getElementById('statusText');
      if (isSafe) {
        badge.className = 'status-badge status-safe';
        statusText.textContent = 'ایمن (SAFE) - کلاد آزاد است';
      } else {
        badge.className = 'status-badge status-unsafe';
        statusText.textContent = 'ناامن (UNSAFE) - کلاد مسدود است';
      }

      document.getElementById('wgStatus').textContent = data.wg_status || 'قطع';
      document.getElementById('wgStatus').style.color = data.wg_connected ? '#34d399' : '#f87171';
      document.getElementById('wgIface').textContent = 'Interface: ' + (data.iface || 'نامشخص');

      // IP info
      if (data.last_ok) {
        const parts = data.last_ok.split('|');
        document.getElementById('ipValue').textContent = parts[0] || '—';
        document.getElementById('geoValue').textContent = (parts[1] || '') + ' (' + (parts[2] || '') + ') - ' + (parts[3] || '');
      } else {
        document.getElementById('ipValue').textContent = '—';
        document.getElementById('geoValue').textContent = 'اطلاعاتی ثبت نشده';
      }

      // Little snitch
      const lsEl = document.getElementById('lsStatus');
      if (data.ls_enabled === true) {
        lsEl.textContent = 'Active Block (قوانین فعال)';
        lsEl.style.color = '#f87171';
      } else if (data.ls_enabled === false) {
        lsEl.textContent = 'Pass-through (غیرفعال/آزاد)';
        lsEl.style.color = '#34d399';
      } else {
        lsEl.textContent = data.config.USE_LITTLE_SNITCH === '1' ? 'نصب شده' : 'خاموش';
      }

      // Populate inputs only on first load so user edits are NEVER overwritten
      if (!formInitialized) {
        document.getElementById('inputCountries').value = data.config.REQUIRE_COUNTRIES || data.config.REQUIRE_COUNTRY || '';
        document.getElementById('inputCities').value = data.config.REQUIRE_CITIES || data.config.REQUIRE_CITY || '';
        document.getElementById('inputAllowedIPs').value = data.config.ALLOWED_IPS || '';
        document.getElementById('inputTunnelName').value = data.config.WG_TUNNEL_NAME || '';
        document.getElementById('inputAllowedASNs').value = data.config.REQUIRE_ASNS || '';
        updateButtonToggles();
        formInitialized = true;
      }

      // Logs
      const logBox = document.getElementById('logBox');
      if (data.recent_logs && data.recent_logs.length) {
        logBox.innerHTML = data.recent_logs.map(line => {
          let cls = 'log-entry';
          if (line.includes('SAFE:')) cls += ' safe';
          if (line.includes('UNSAFE:')) cls += ' unsafe';
          return `<div class="${cls}">${escapeHtml(line)}</div>`;
        }).join('');
        logBox.scrollTop = logBox.scrollHeight;
      }
    }

    function updateButtonToggles() {
      const val = document.getElementById('inputCountries').value || '';
      const activeCountries = val.split(',').map(s => s.trim().toUpperCase());
      document.getElementById('btnTR')?.classList.toggle('active', activeCountries.includes('TR'));
      document.getElementById('btnAE')?.classList.toggle('active', activeCountries.includes('AE'));
      document.getElementById('btnDE')?.classList.toggle('active', activeCountries.includes('DE'));
      document.getElementById('btnNL')?.classList.toggle('active', activeCountries.includes('NL'));
      document.getElementById('btnUS')?.classList.toggle('active', activeCountries.includes('US'));
      document.getElementById('btnGB')?.classList.toggle('active', activeCountries.includes('GB'));
    }

    document.getElementById('inputCountries')?.addEventListener('input', updateButtonToggles);

    function toggleCountry(code) {
      let countries = (document.getElementById('inputCountries').value || '').split(',').map(s => s.trim().toUpperCase()).filter(Boolean);

      if (countries.includes(code)) {
        countries = countries.filter(c => c !== code);
      } else {
        countries.push(code);
      }

      document.getElementById('inputCountries').value = countries.join(',');
      updateButtonToggles();
    }

    async function saveSettings() {
      const saveBtn = document.querySelector('.btn-primary');
      const origText = saveBtn.innerHTML;
      saveBtn.innerHTML = '⏳ در حال ذخیره...';
      saveBtn.disabled = true;

      const payload = {
        REQUIRE_COUNTRIES: document.getElementById('inputCountries').value.trim(),
        REQUIRE_CITIES: document.getElementById('inputCities').value.trim(),
        ALLOWED_IPS: document.getElementById('inputAllowedIPs').value.trim(),
        WG_TUNNEL_NAME: document.getElementById('inputTunnelName').value.trim(),
        REQUIRE_ASNS: document.getElementById('inputAllowedASNs').value.trim()
      };

      try {
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        const resp = await res.json();
        if (resp.success) {
          saveBtn.innerHTML = '✅ ذخیره شد!';
          setTimeout(() => {
            saveBtn.innerHTML = origText;
            saveBtn.disabled = false;
          }, 1500);
          await runCheckNow();
        } else {
          alert('خطا در ذخیره: ' + (resp.error || 'ناشناخته'));
          saveBtn.innerHTML = origText;
          saveBtn.disabled = false;
        }
      } catch (e) {
        alert('خطای ارتباط با سرور: ' + e);
        saveBtn.innerHTML = origText;
        saveBtn.disabled = false;
      }
    }

    async function runCheckNow() {
      try {
        const res = await fetch('/api/enforce', {method: 'POST'});
        const data = await res.json();
        await fetchStatus();
      } catch (e) {
        console.error(e);
      }
    }

    function escapeHtml(text) {
      return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    fetchStatus();
    setInterval(fetchStatus, 3000);
  </script>
</body>
</html>
"""

class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress noisy standard request logging to stderr
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif parsed.path == "/api/status":
            data = get_live_status()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                new_data = json.loads(body)
                current = read_config()
                for k, v in new_data.items():
                    current[k] = v
                write_config(current)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        elif parsed.path == "/api/enforce":
            res = run_enforce_now()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    server = HTTPServer(("127.0.0.1", PORT), RequestHandler)
    print(f"Claude Kill Switch UI running at http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down UI server.")
        server.server_close()

if __name__ == "__main__":
    run_server()
