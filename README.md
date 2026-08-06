# Claude ↔ Istanbul Kill Switch

بلاک کامل ترافیک **Claude** روی macOS مگر وقتی:

1. تونل **WireGuard** وصل باشد، و
2. IP خروجی عمومی واقعاً **Istanbul / TR** باشد (نه فقط سرور میانی ایران).

اگر WireGuard قطع باشد، یا VPN بالا باشد ولی خروجی استانبول نباشد → Claude بسته می‌شود و (اختیاری) با **Little Snitch** شبکهٔ آن Deny می‌شود.

> نیازها: macOS · WireGuard.app · (پیشنهادی) Little Snitch 6+ · دسترسی ادمین برای sudoers

---

## نصب سریع روی سیستم جدید

```bash
git clone https://github.com/OWNER/claude-istanbul-killswitch.git
cd claude-istanbul-killswitch
chmod +x bin/*.sh
./bin/install.sh
```

اسکریپت نصب این کارها را می‌کند:

- `config.env` را از نمونه می‌سازد و نام تونل WireGuard را می‌پرسد
- LaunchAgent را هر ۱۰ ثانیه ثبت می‌کند
- راهنمای Little Snitch را نشان می‌دهد
- (اختیاری) sudoers محدود فقط برای باینری `littlesnitch` نصب می‌کند

بعد از نصب:

```bash
./bin/status.sh
tail -f ~/Library/Logs/claude-istanbul-killswitch.log
```

---

## پیش‌نیازها

| ابزار | چرا |
|---|---|
| [WireGuard](https://www.wireguard.com/install/) | تونل VPN |
| [Claude.app](https://claude.ai/download) | اپی که باید محافظت شود |
| [Little Snitch 6+](https://www.obdev.at/products/littlesnitch/) | بلاک سخت شبکه (پیشنهادی) |
| `curl` + `python3` | چک IP (روی macOS معمولاً هست) |

نام تونل WireGuard را از خود اپ یا این دستور بگیر:

```bash
scutil --nc list | grep -i wireguard
```

---

## تنظیمات (`config.env`)

بعد از `install.sh` فایل `config.env` ساخته می‌شود:

| متغیر | معنی | نمونه |
|---|---|---|
| `WG_TUNNEL_NAME` | نام تونل در WireGuard.app | `nima` |
| `REQUIRE_COUNTRY` | کد کشور خروجی | `TR` |
| `REQUIRE_CITY` | شهر خروجی | `Istanbul` |
| `REQUIRE_ASNS` | ASN مجاز (خالی = چک نشود) | `AS44382` |
| `QUIT_CLAUDE_WHEN_UNSAFE` | بستن Claude وقتی unsafe | `1` |
| `USE_LITTLE_SNITCH` | روشن/خاموش کردن Rule Group | `1` |
| `LS_RULE_GROUP` | نام گروه در Little Snitch | `Claude Kill Switch` |

اگر دیتاسنتر عوض شد ولی هنوز استانبول است، `REQUIRE_ASNS` را خالی بگذار یا ASN جدید را بگذار.

---

## Little Snitch (بلاک شبکه)

بدون این هم اسکریپت Claude را می‌بندد؛ با این، حتی یک درخواست شبکه هم رد نمی‌شود.

### ۱) اجازه Command Line

Little Snitch → **Settings (⌘,)** → **Security** → **Allow access via Terminal** را روشن کن.

### ۲) ساخت Rule Group

1. پنجره **Rules** → کنار **Rule Groups** روی **＋** → **Local Rule Group…**
2. نام دقیقاً: `Claude Kill Switch`
3. قوانین Deny را اضافه کن — آسان‌ترین راه:

   **File → Import Rules…** و این فایل را انتخاب کن:

   `little-snitch/Claude Kill Switch.lsrules`

4. گروه را **Disabled** بگذار (اسکریپت وقتی unsafe شد Enable می‌کند).

### ۳) sudo بدون پسورد (برای LaunchAgent)

`install.sh` می‌تواند این را بسازد، یا دستی:

```bash
LS="/Applications/Little Snitch.app/Contents/Components/littlesnitch"
echo "$(whoami) ALL=(root) NOPASSWD: $LS" | sudo tee /etc/sudoers.d/claude-killswitch-ls
sudo chmod 440 /etc/sudoers.d/claude-killswitch-ls
sudo visudo -cf /etc/sudoers.d/claude-killswitch-ls
```

سپس در `config.env`:

```bash
USE_LITTLE_SNITCH=1
```

تست:

```bash
sudo -n "$LS" rulegroup --enable "Claude Kill Switch"
sudo -n "$LS" rulegroup --disable "Claude Kill Switch"
sudo -n "$LS" rulegroup
```

---

## تست صحت

1. WireGuard را **Disconnect** کن → نوتیف «قطع است» · Claude بسته می‌شود · گروه LS روشن می‌شود.
2. دوباره وصل کن با خروجی استانبول → نوتیف «آزاد است» · گروه LS خاموش می‌شود.
3. وضعیت:

```bash
./bin/status.sh
curl -4 https://ipinfo.io/json
```

باید `city: Istanbul` و `country: TR` باشد.

---

## حذف

```bash
./bin/uninstall.sh
```

LaunchAgent، sudoers، و (اختیاری) state/log را برمی‌دارد. Rule Group داخل Little Snitch را دستی پاک کن اگر خواستی.

---

## ساختار پروژه

```
bin/enforce.sh          # منطق اصلی (هر ۱۰ثانیه)
bin/status.sh           # وضعیت فعلی
bin/install.sh          # نصب روی مک جدید
bin/uninstall.sh        # حذف
config.env.example      # نمونه تنظیمات
little-snitch/*.lsrules # قوانین قابل Import
launchd/*.plist.template
```

---

## نکته امنیتی

- پسورد sudo / مک را هیچ‌وقت داخل ریپو یا چت نگذار.
- فایل `/etc/sudoers.d/claude-killswitch-ls` فقط به باینری `littlesnitch` اجازه می‌دهد، نه به کل سیستم.
- لاگ: `~/Library/Logs/claude-istanbul-killswitch.log`

---

## مجوز

MIT — استفاده آزاد برای شخصی‌سازی روی مک خودت.
