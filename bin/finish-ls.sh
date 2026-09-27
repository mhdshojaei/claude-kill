#!/bin/zsh
set -euo pipefail
ROOT_DIR="${0:A:h:h}"
LS_CLI="/Applications/Little Snitch.app/Contents/Components/littlesnitch"
GROUP="Claude Kill Switch"

print "=== Finish Little Snitch integration ==="
if ! /usr/bin/sudo -n "${LS_CLI}" rulegroup >/dev/null 2>&1; then
  print "ERROR: CLI هنوز مجاز نیست." >&2
  print "Little Snitch → Settings (⌘,) → Security → Allow access via Terminal را روشن کن." >&2
  exit 1
fi

print "گروه‌های فعلی:"
/usr/bin/sudo -n "${LS_CLI}" rulegroup

if ! /usr/bin/sudo -n "${LS_CLI}" rulegroup 2>&1 | /usr/bin/grep -F "${GROUP}" >/dev/null; then
  print ""
  print "گروه «${GROUP}» پیدا نشد."
  print "1) Rules → ＋ → Local Rule Group… نام دقیقاً: ${GROUP}"
  print "2) File → Import Rules… → ${ROOT_DIR}/little-snitch/Claude Kill Switch.lsrules"
  print "3) گروه را Disabled بگذار"
  print "بعد دوباره این اسکریپت را اجرا کن."
  /usr/bin/open -R "${ROOT_DIR}/little-snitch/Claude Kill Switch.lsrules"
  exit 2
fi

# Toggle test
/usr/bin/sudo -n "${LS_CLI}" rulegroup --enable "${GROUP}"
/usr/bin/sudo -n "${LS_CLI}" rulegroup --disable "${GROUP}"
/usr/bin/sed -i '' 's/^USE_LITTLE_SNITCH=.*/USE_LITTLE_SNITCH=1/' "${ROOT_DIR}/config.env"
print "✓ USE_LITTLE_SNITCH=1"
"${ROOT_DIR}/bin/enforce.sh" || true
"${ROOT_DIR}/bin/status.sh"
print "تمام."
