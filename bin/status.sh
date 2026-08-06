#!/bin/zsh
# Status for Claude Istanbul kill switch
set -euo pipefail
SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:A:h}"
STATE_DIR="${HOME}/Library/Application Support/claude-istanbul-killswitch"
CONFIG_FILE="${ROOT_DIR}/config.env"
LABEL="com.claude-istanbul-killswitch"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  print "Missing ${CONFIG_FILE}"
  exit 1
fi
source "${CONFIG_FILE}"

print "Tunnel: ${WG_TUNNEL_NAME}"
print "scutil: $(/usr/sbin/scutil --nc status "${WG_TUNNEL_NAME}" 2>/dev/null | /usr/bin/head -n 1)"
iface="$(/usr/sbin/scutil --nc status "${WG_TUNNEL_NAME}" 2>/dev/null | /usr/bin/awk -F' : ' '/InterfaceName/ {print $2; exit}')"
print "iface: ${iface:-unknown}"
if [[ -n "${iface}" ]]; then
  print "exit via WG:"
  /usr/bin/curl -4 -sS --max-time 6 --interface "${iface}" "https://ipinfo.io/json" || true
  print
fi
print "USE_LITTLE_SNITCH=${USE_LITTLE_SNITCH}"
print "state file: $(/bin/cat "${STATE_DIR}/state" 2>/dev/null || print 'none')"
if [[ "${USE_LITTLE_SNITCH}" == "1" && -x "${LS_CLI}" ]]; then
  print "Little Snitch groups:"
  /usr/bin/sudo -n "${LS_CLI}" rulegroup 2>&1 || print "  (sudo -n failed — run install.sh sudoers step)"
fi
print "LaunchAgent:"
/bin/launchctl print "gui/$(/usr/bin/id -u)/${LABEL}" 2>&1 | /usr/bin/head -n 25 || true
