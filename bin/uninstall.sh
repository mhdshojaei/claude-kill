#!/bin/zsh
# Uninstall Claude ↔ Istanbul kill switch from this Mac.
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:A:h}"
LABEL="com.claude-istanbul-killswitch"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
SUDOERS_PATH="/etc/sudoers.d/claude-killswitch-ls"
STATE_DIR="${HOME}/Library/Application Support/claude-istanbul-killswitch"

print "=== Uninstall ==="
uid="$(/usr/bin/id -u)"
/bin/launchctl bootout "gui/${uid}" "${PLIST_DST}" 2>/dev/null || true
/bin/rm -f "${PLIST_DST}"
print "✓ LaunchAgent removed"

if [[ -f "${SUDOERS_PATH}" ]]; then
  print -n "حذف sudoers (${SUDOERS_PATH})؟ [y/N] "
  read -r ans || true
  if [[ "${ans}" == "y" || "${ans}" == "Y" ]]; then
    /usr/bin/sudo rm -f "${SUDOERS_PATH}"
    print "✓ sudoers removed"
  fi
fi

print -n "حذف state/log؟ [y/N] "
read -r ans || true
if [[ "${ans}" == "y" || "${ans}" == "Y" ]]; then
  /bin/rm -rf "${STATE_DIR}"
  /bin/rm -f "${HOME}/Library/Logs/claude-istanbul-killswitch.log" \
    "${HOME}/Library/Logs/claude-istanbul-killswitch.stdout.log" \
    "${HOME}/Library/Logs/claude-istanbul-killswitch.stderr.log"
  print "✓ state/log removed"
fi

print ""
print "اگر Rule Group در Little Snitch ساختی، دستی از Rules پاکش کن."
print "ریپو اینجا ماند: ${ROOT_DIR}"
