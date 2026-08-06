#!/bin/zsh
# Install Claude ↔ Istanbul kill switch on this Mac.
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:A:h}"
LABEL="com.claude-istanbul-killswitch"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LS_CLI="/Applications/Little Snitch.app/Contents/Components/littlesnitch"
LSRULES="${ROOT_DIR}/little-snitch/Claude Kill Switch.lsrules"
SUDOERS_PATH="/etc/sudoers.d/claude-killswitch-ls"

print "=== Claude Istanbul Kill Switch · install ==="
print "Root: ${ROOT_DIR}"
print ""

chmod +x "${ROOT_DIR}/bin/"*.sh

# --- config ---
if [[ ! -f "${ROOT_DIR}/config.env" ]]; then
  cp "${ROOT_DIR}/config.env.example" "${ROOT_DIR}/config.env"
  print "Created config.env from example."
fi

print "تونل‌های WireGuard:"
/usr/sbin/scutil --nc list 2>/dev/null | /usr/bin/grep -i wireguard || print "(هیچ تونلی دیده نشد)"
print ""
current="$(/usr/bin/grep -E '^WG_TUNNEL_NAME=' "${ROOT_DIR}/config.env" | /usr/bin/sed 's/^WG_TUNNEL_NAME=//;s/^\"//;s/\"$//')"
print -n "نام تونل WireGuard [${current}]: "
read -r tunnel || true
tunnel="${tunnel:-$current}"
if [[ -z "${tunnel}" || "${tunnel}" == "CHANGE_ME" ]]; then
  print "ERROR: یک نام تونل معتبر بده." >&2
  exit 1
fi
/usr/bin/sed -i '' "s/^WG_TUNNEL_NAME=.*/WG_TUNNEL_NAME=\"${tunnel}\"/" "${ROOT_DIR}/config.env"
print "WG_TUNNEL_NAME=${tunnel}"

# --- LaunchAgent ---
mkdir -p "${HOME}/Library/LaunchAgents" "${HOME}/Library/Logs" \
  "${HOME}/Library/Application Support/claude-istanbul-killswitch"

enforce_path="${ROOT_DIR}/bin/enforce.sh"
interval=10
cat > "${PLIST_DST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>${enforce_path}</string>
  </array>
  <key>StartInterval</key>
  <integer>${interval}</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${HOME}/Library/Logs/claude-istanbul-killswitch.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME}/Library/Logs/claude-istanbul-killswitch.stderr.log</string>
</dict>
</plist>
EOF

uid="$(/usr/bin/id -u)"
/bin/launchctl bootout "gui/${uid}" "${PLIST_DST}" 2>/dev/null || true
/bin/launchctl bootstrap "gui/${uid}" "${PLIST_DST}"
/bin/launchctl kickstart -k "gui/${uid}/${LABEL}"
print "✓ LaunchAgent ثبت شد (${LABEL}, every ${interval}s)"

# --- Little Snitch guidance ---
print ""
print "—— Little Snitch (پیشنهادی) ——"
if [[ -x "${LS_CLI}" ]]; then
  /usr/bin/open -a "Little Snitch" 2>/dev/null || true
  [[ -f "${LSRULES}" ]] && /usr/bin/open -R "${LSRULES}" 2>/dev/null || true
  print "1) Settings → Security → Allow access via Terminal"
  print "2) Rules → ＋ → Local Rule Group… نام: Claude Kill Switch"
  print "3) File → Import Rules… → ${LSRULES}"
  print "4) گروه را Disabled بگذار"
  print ""
  print -n "sudoers محدود برای littlesnitch نصب شود؟ [Y/n] "
  read -r ans || true
  ans="${ans:-Y}"
  if [[ "${ans}" == "Y" || "${ans}" == "y" ]]; then
    tmp="$(/usr/bin/mktemp)"
    # Escape spaces for sudoers
    ls_escaped="${LS_CLI// /\\ }"
    print -- "$(/usr/bin/whoami) ALL=(root) NOPASSWD: ${ls_escaped}" > "${tmp}"
    /usr/bin/sudo cp "${tmp}" "${SUDOERS_PATH}"
    /usr/bin/sudo chmod 440 "${SUDOERS_PATH}"
    /usr/bin/sudo visudo -cf "${SUDOERS_PATH}"
    /bin/rm -f "${tmp}"
    if /usr/bin/sudo -n "${LS_CLI}" rulegroup >/dev/null 2>&1; then
      print "✓ sudo -n برای littlesnitch اوکی است"
      /usr/bin/sed -i '' 's/^USE_LITTLE_SNITCH=.*/USE_LITTLE_SNITCH=1/' "${ROOT_DIR}/config.env"
      print "✓ USE_LITTLE_SNITCH=1"
      print -n "گروه «Claude Kill Switch» را در LS ساختی؟ تست enable/disable؟ [y/N] "
      read -r gans || true
      if [[ "${gans}" == "y" || "${gans}" == "Y" ]]; then
        /usr/bin/sudo -n "${LS_CLI}" rulegroup --enable "Claude Kill Switch"
        /usr/bin/sudo -n "${LS_CLI}" rulegroup --disable "Claude Kill Switch"
        print "✓ toggle اوکی"
      fi
    else
      print "⚠ هنوز CLI مجاز نیست یا گروه ساخته نشده — بعد از تنظیم LS:"
      print "   sed -i '' 's/^USE_LITTLE_SNITCH=.*/USE_LITTLE_SNITCH=1/' config.env"
    fi
  fi
else
  print "Little Snitch نصب نیست — فقط بستن Claude فعال است."
fi

print ""
"${ROOT_DIR}/bin/enforce.sh" || true
print "state=$(/bin/cat "${HOME}/Library/Application Support/claude-istanbul-killswitch/state" 2>/dev/null || print unknown)"
print ""
print "تمام. وضعیت: ${ROOT_DIR}/bin/status.sh"
print "لاگ:     tail -f ~/Library/Logs/claude-istanbul-killswitch.log"
