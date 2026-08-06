#!/bin/zsh
# Claude ↔ Istanbul kill switch
# Blocks Claude unless WireGuard is up AND public exit IP is Istanbul.
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:A:h}"
STATE_DIR="${HOME}/Library/Application Support/claude-istanbul-killswitch"
LOG_FILE="${HOME}/Library/Logs/claude-istanbul-killswitch.log"
STATE_FILE="${STATE_DIR}/state"
CONFIG_FILE="${ROOT_DIR}/config.env"

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

fetch_exit_json() {
  local iface json
  iface="$(wg_interface)"
  if [[ -n "${iface}" ]]; then
    json="$(/usr/bin/curl -4 -sS --max-time 6 --interface "${iface}" "https://ipinfo.io/json" 2>/dev/null || true)"
    if [[ -n "${json}" ]]; then
      print -- "${json}"
      return 0
    fi
  fi
  /usr/bin/curl -4 -sS --max-time 6 "https://ipinfo.io/json" 2>/dev/null || true
}

json_field() {
  local json="$1" key="$2"
  print -- "${json}" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get(sys.argv[1],"") or "")' "${key}" 2>/dev/null \
    || print -- "${json}" | /usr/bin/sed -n "s/.*\"${key}\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" | /usr/bin/head -n 1
}

exit_is_istanbul() {
  local json ip city country org asn ok_asn
  json="$(fetch_exit_json)"
  [[ -n "${json}" ]] || return 1

  ip="$(json_field "${json}" ip)"
  city="$(json_field "${json}" city)"
  country="$(json_field "${json}" country)"
  org="$(json_field "${json}" org)"
  asn="$(print -- "${org}" | /usr/bin/grep -Eo 'AS[0-9]+' | /usr/bin/head -n 1)"

  [[ "${country}" == "${REQUIRE_COUNTRY}" ]] || return 1
  [[ "${city}" == "${REQUIRE_CITY}" ]] || return 1

  if [[ -n "${REQUIRE_ASNS}" ]]; then
    ok_asn=0
    local allowed
    for allowed in ${(s:,:)REQUIRE_ASNS}; do
      allowed="${allowed// /}"
      if [[ -n "${allowed}" && "${asn}" == "${allowed}" ]]; then
        ok_asn=1
        break
      fi
    done
    [[ "${ok_asn}" == "1" ]] || return 1
  fi

  print -- "${ip}|${city}|${country}|${asn}"
  return 0
}

quit_app() {
  local app_name="$1"   # AppleScript name
  local path_match="$2" # pgrep/pkill path fragment
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

previous_state="unknown"
[[ -f "${STATE_FILE}" ]] && previous_state="$(/bin/cat "${STATE_FILE}")"

if ! wg_connected; then
  log "UNSAFE: WireGuard '${WG_TUNNEL_NAME}' not connected"
  print -n "unsafe" > "${STATE_FILE}"
  set_ls_block 1
  quit_protected_apps
  if [[ "${previous_state}" != "unsafe" ]]; then
    notify "Istanbul Kill Switch" "WireGuard قطع است — Claude/Brave مسدود شدند"
  fi
  exit 0
fi

geo=""
if geo="$(exit_is_istanbul)"; then
  log "SAFE: ${geo}"
  print -n "safe" > "${STATE_FILE}"
  set_ls_block 0
  if [[ "${previous_state}" != "safe" ]]; then
    notify "Istanbul Kill Switch" "خروجی استانبول تأیید شد — Claude/Brave آزادند"
  fi
  exit 0
fi

log "UNSAFE: WG up but exit is not Istanbul (or geo check failed)"
print -n "unsafe" > "${STATE_FILE}"
set_ls_block 1
quit_protected_apps
if [[ "${previous_state}" != "unsafe" ]]; then
  notify "Istanbul Kill Switch" "IP استانبول نیست — Claude/Brave مسدود شدند"
fi
exit 0
