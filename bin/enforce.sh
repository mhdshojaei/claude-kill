#!/bin/zsh
# Claude ↔ Istanbul kill switch
# Blocks Claude/Brave unless WireGuard is up AND public exit IP is Istanbul.
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:A:h}"
STATE_DIR="${HOME}/Library/Application Support/claude-istanbul-killswitch"
LOG_FILE="${HOME}/Library/Logs/claude-istanbul-killswitch.log"
STATE_FILE="${STATE_DIR}/state"
CACHE_FILE="${STATE_DIR}/last_ok"
CONFIG_FILE="${ROOT_DIR}/config.env"

# How long a successful Istanbul verification remains trusted if geo APIs fail (seconds)
CACHE_TTL_SECONDS="${CACHE_TTL_SECONDS:-300}"

mkdir -p "${STATE_DIR}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  print "Missing config.env — copy config.env.example and run bin/install.sh" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${CONFIG_FILE}"

log() {
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  print -- "[${ts}] $*" >> "${LOG_FILE}"
}

notify() {
  [[ "${NOTIFY_ON_CHANGE}" == "1" ]] || return 0
  local title="$1" body="$2"
  /usr/bin/osascript -e "display notification \"${body}\" with title \"${title}\"" 2>/dev/null || true
}

wg_connected() {
  local wg_status
  wg_status="$(/usr/sbin/scutil --nc status "${WG_TUNNEL_NAME}" 2>/dev/null | /usr/bin/head -n 1 | /usr/bin/tr -d '\r')"
  [[ "${wg_status}" == "Connected" ]]
}

wg_interface() {
  /usr/sbin/scutil --nc status "${WG_TUNNEL_NAME}" 2>/dev/null \
    | /usr/bin/awk -F' : ' '/InterfaceName/ {print $2; exit}'
}

curl_via() {
  local url="$1"
  local iface
  iface="$(wg_interface)"
  # Bypass broken local HTTP proxies (seen as 127.0.0.1:xxxxx failures)
  if [[ -n "${iface}" ]]; then
    /usr/bin/curl -4 -sS --max-time 5 --noproxy '*' --interface "${iface}" "${url}" 2>/dev/null && return 0
  fi
  /usr/bin/curl -4 -sS --max-time 5 --noproxy '*' "${url}" 2>/dev/null || true
}

# Normalize provider JSON → "ip|city|country|asn" or empty on failure/rate-limit
# NOTE: must take JSON as argv — a heredoc would steal stdin from a pipe.
parse_geo() {
  /usr/bin/python3 -c '
import json, re, sys
raw = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
if not raw:
    sys.exit(1)
try:
    d = json.loads(raw)
except Exception:
    sys.exit(1)

if isinstance(d, dict):
    if d.get("success") is False:
        sys.exit(2)
    if d.get("status") in (429, "fail", "error") or ("error" in d and not d.get("ip") and not d.get("query")):
        if d.get("status") == 429 or isinstance(d.get("error"), dict) or d.get("error") is True:
            sys.exit(2)
        if d.get("status") == "fail":
            sys.exit(2)

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
    d.get("as")
    or org
    or d.get("asn")
    or (("AS" + str(conn["asn"])) if conn.get("asn") else "")
    or conn.get("org")
    or ""
)
asn_m = re.search(r"AS\d+", asn_src, re.I)
asn = asn_m.group(0).upper() if asn_m else ""
if not asn and str(d.get("asn", "")).isdigit():
    asn = "AS" + str(d.get("asn"))
if not ip or not city or not country:
    sys.exit(1)
cc = d.get("countryCode") or d.get("country_code") or d.get("country_iso")
if cc and len(str(cc)) == 2:
    country = str(cc)
elif len(str(country)) != 2 and d.get("country") and len(str(d.get("country"))) == 2:
    country = str(d.get("country"))
print(f"{ip}|{city}|{country}|{asn}")
' "$1"
}

# Returns:
#  0 + prints geo  → confirmed Istanbul match
#  1               → confirmed NOT match (or unusable definitive response)
#  2               → check unavailable (rate limit / all providers failed)
exit_check() {
  local body norm rc
  local -a urls=(
    "https://ipwho.is/"
    "https://get.geojs.io/v1/ip/geo.json"
    "http://ip-api.com/json/?fields=status,message,country,countryCode,city,query,as"
    "https://ipinfo.io/json"
    "https://ipapi.co/json/"
  )
  local url
  local saw_ratelimit=0
  for url in "${urls[@]}"; do
    body="$(curl_via "${url}")"
    [[ -n "${body}" ]] || continue
    norm="$(parse_geo "${body}")" && rc=0 || rc=$?
    if [[ "${rc}" -eq 2 ]]; then
      saw_ratelimit=1
      continue
    fi
    if [[ "${rc}" -ne 0 || -z "${norm}" ]]; then
      continue
    fi
    local ip city country asn
    ip="${norm%%|*}"; rest="${norm#*|}"
    city="${rest%%|*}"; rest="${rest#*|}"
    country="${rest%%|*}"; asn="${rest##*|}"

    # normalize city comparisons (İstanbul vs Istanbul)
    local city_n country_n
    city_n="$(print -- "${city}" | /usr/bin/iconv -f UTF-8 -t ASCII//TRANSLIT 2>/dev/null | /usr/bin/tr '[:upper:]' '[:lower:]')"
    city_n="${city_n:-$(print -- "${city}" | /usr/bin/tr '[:upper:]' '[:lower:]')}"
    country_n="$(print -- "${country}" | /usr/bin/tr '[:lower:]' '[:upper:]')"
    local want_city want_country
    want_city="$(print -- "${REQUIRE_CITY}" | /usr/bin/tr '[:upper:]' '[:lower:]')"
    want_country="$(print -- "${REQUIRE_COUNTRY}" | /usr/bin/tr '[:lower:]' '[:upper:]')"

    if [[ "${country_n}" != "${want_country}" ]]; then
      print -- "mismatch:${norm}"
      return 1
    fi
    if [[ "${city_n}" != "${want_city}" && "${city_n}" != "istanbul" && "${city_n}" != "i̇stanbul" ]]; then
      # allow common TR spelling after translit
      if [[ "${city_n}" != *"stanbul"* ]]; then
        print -- "mismatch:${norm}"
        return 1
      fi
    fi
    if [[ -n "${REQUIRE_ASNS}" ]]; then
      local ok_asn=0 allowed
      for allowed in ${(s:,:)REQUIRE_ASNS}; do
        allowed="${allowed// /}"
        allowed="$(print -- "${allowed}" | /usr/bin/tr '[:lower:]' '[:upper:]')"
        if [[ -n "${allowed}" && "${asn}" == "${allowed}" ]]; then
          ok_asn=1
          break
        fi
      done
      if [[ "${ok_asn}" != "1" ]]; then
        print -- "mismatch:${norm}"
        return 1
      fi
    fi
    print -- "${norm}"
    return 0
  done
  [[ "${saw_ratelimit}" == "1" ]] && return 2
  return 2
}

cache_ok_fresh() {
  [[ -f "${CACHE_FILE}" ]] || return 1
  local now mtime age
  now="$(/bin/date +%s)"
  mtime="$(/usr/bin/stat -f %m "${CACHE_FILE}" 2>/dev/null || print 0)"
  age=$(( now - mtime ))
  [[ "${age}" -le "${CACHE_TTL_SECONDS}" ]]
}

quit_app() {
  local app_name="$1"
  local path_match="$2"
  if /usr/bin/pgrep -f "${path_match}" >/dev/null 2>&1; then
    /usr/bin/osascript -e "tell application \"${app_name}\" to quit" 2>/dev/null || true
    /bin/sleep 1
    /usr/bin/pkill -f "${path_match}" 2>/dev/null || true
    log "Quit ${app_name}"
  fi
}

quit_protected_apps() {
  [[ "${QUIT_CLAUDE_WHEN_UNSAFE:-1}" == "1" ]] && quit_app "Claude" "/Applications/Claude.app/"
  [[ "${QUIT_BRAVE_WHEN_UNSAFE:-1}" == "1" ]] && quit_app "Brave Browser" "/Applications/Brave Browser.app/"
}

set_ls_block() {
  local enable="$1"
  [[ "${USE_LITTLE_SNITCH}" == "1" ]] || return 0
  [[ -x "${LS_CLI}" ]] || return 0
  if [[ "${enable}" == "1" ]]; then
    /usr/bin/sudo -n "${LS_CLI}" rulegroup --enable "${LS_RULE_GROUP}" 2>>"${LOG_FILE}" || log "WARN: could not enable LS group ${LS_RULE_GROUP}"
  else
    /usr/bin/sudo -n "${LS_CLI}" rulegroup --disable "${LS_RULE_GROUP}" 2>>"${LOG_FILE}" || log "WARN: could not disable LS group ${LS_RULE_GROUP}"
  fi
}

mark_safe() {
  local geo="$1"
  print -n "safe" > "${STATE_FILE}"
  print -n "${geo}" > "${CACHE_FILE}"
  set_ls_block 0
}

mark_unsafe() {
  print -n "unsafe" > "${STATE_FILE}"
  set_ls_block 1
  quit_protected_apps
}

previous_state="unknown"
[[ -f "${STATE_FILE}" ]] && previous_state="$(/bin/cat "${STATE_FILE}")"

if ! wg_connected; then
  log "UNSAFE: WireGuard '${WG_TUNNEL_NAME}' not connected"
  mark_unsafe
  if [[ "${previous_state}" != "unsafe" ]]; then
    notify "Istanbul Kill Switch" "WireGuard قطع است — Claude/Brave مسدود شدند"
  fi
  exit 0
fi

geo=""
check_rc=0
geo="$(exit_check)" && check_rc=0 || check_rc=$?

if [[ "${check_rc}" -eq 0 ]]; then
  log "SAFE: ${geo}"
  mark_safe "${geo}"
  if [[ "${previous_state}" != "safe" ]]; then
    notify "Istanbul Kill Switch" "خروجی استانبول تأیید شد — Claude/Brave آزادند"
  fi
  exit 0
fi

if [[ "${check_rc}" -eq 2 ]]; then
  # Geo APIs unavailable (e.g. ipinfo 429). Keep last good result briefly while WG is up.
  if cache_ok_fresh; then
    cached="$(/bin/cat "${CACHE_FILE}" 2>/dev/null || true)"
    log "SAFE(cache): geo API unavailable; trusting last OK (${cached})"
    mark_safe "${cached:-cached}"
    exit 0
  fi
  log "UNSAFE: geo API unavailable and no fresh Istanbul cache"
  mark_unsafe
  if [[ "${previous_state}" != "unsafe" ]]; then
    notify "Istanbul Kill Switch" "چک IP موقتاً از کار افتاد — مسدود شد"
  fi
  exit 0
fi

# confirmed mismatch
log "UNSAFE: ${geo}"
mark_unsafe
if [[ "${previous_state}" != "unsafe" ]]; then
  notify "Istanbul Kill Switch" "IP استانبول نیست — Claude/Brave مسدود شدند"
fi
exit 0
