# ios-debloat

[![CI](https://github.com/will702/ios-debloat/actions/workflows/ci.yml/badge.svg)](https://github.com/will702/ios-debloat/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB.svg)](pyproject.toml)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](pyproject.toml)

**Turn off iPhone, iPad, and Apple Watch telemetry, ads, Siri noise, and Apple Intelligence bloat from your terminal — one keystroke, zero hard dependencies, 100% reversible.**

A sibling project to [`OleksandrKrupko/mac-os-debloat`](https://github.com/OleksandrKrupko/mac-os-debloat) adapted for **iOS 26/27, iPadOS 26/27, and watchOS 26/27** using Apple's official Device Management schema ([`apple/device-management`](https://github.com/apple/device-management)) rather than unsafe backup exploits.

- **Zero dependencies (MIT):** runs on macOS's built-in `python3` (3.9+ stdlib only — `curses`, `plistlib`, `http.server`, `uuid`).
- **Dual-mode like SIP on/off:** works **unsupervised** by default (<!-- sync:restrictions_unsupervised -->18<!-- /sync:restrictions_unsupervised --> restrictions + <!-- sync:dns_presets -->6<!-- /sync:dns_presets --> Encrypted DNS blockers, zero wipe); unlock **<!-- sync:restrictions_total -->57<!-- /sync:restrictions_total --> total restrictions** (including <!-- sync:restrictions_supervised -->39<!-- /sync:restrictions_supervised --> supervised-only Apple Intelligence, Siri, Keyboard & stock service controls) plus OS 26.4/27+ **DDM JSON** export when supervised.
- **Wireless or USB delivery:** scan a pure-Python **terminal QR code** with your iPhone/iPad Camera, reveal in Finder for **AirDrop**, or push directly over USB/Wi-Fi with optional [`pymobiledevice3`](https://github.com/doronz88/pymobiledevice3).
- **100% reversible:** every `.mobileconfig` sets `PayloadRemovalDisallowed = False` so you can remove it anytime in *Settings -> General -> VPN & Device Management* (or `--enable-all` / `--restore`).
- **AI-Agent ready:** ships with [`AGENTS.md`](AGENTS.md), [`llms.txt`](llms.txt), structured `--json` outputs (`--status --json`, `--audit --json`, `--dry-run`), and an installable Agent Skill ([`skills/ios-debloat/SKILL.md`](skills/ios-debloat/SKILL.md)).

---

## Install & Quick Start

```bash
git clone https://github.com/will702/ios-debloat.git
cd ios-debloat

./debloat                          # interactive curses TUI (default)
./debloat --preset telemetry --dns adguard --deliver qr
./debloat --preset balanced --dns mullvad-base --dns-apple-only --deliver qr
./debloat --status                 # device, supervision, active profile, DNS & watchOS progress
./debloat --audit                  # live (USB + pymobiledevice3) or offline telemetry audit
```

Or run as a Python module / install locally:

```bash
python3 -m ios_debloat
# or: pipx install git+https://github.com/will702/ios-debloat.git
```

### AI Agent Skill Install

```bash
npx skills add will702/ios-debloat
```

---

## TUI Controls

```text
↑ / ↓ or j / k   move cursor
PgUp / PgDn      jump 10 rows
[ / ]            jump to previous / next section
space            toggle restriction, select DNS radio, or check off watchOS item
enter            apply selected preset/action (choose QR, AirDrop, Export, or USB)
s                toggle supervised mode preview (offline) / view Supervision Guide
r                reload device, profiles, apps & checklist state
q / Esc          quit
```

---

## Presets & Catalog

| Preset / Scope | Total Keys | Unsupervised | What it turns off |
| :--- | :---: | :---: | :--- |
| `--preset telemetry` | <!-- sync:telemetry_total -->8<!-- /sync:telemetry_total --> | <!-- sync:telemetry_unsup -->6<!-- /sync:telemetry_unsup --> | Apple diagnostic & crash submission, Personalized Ads, Limit Ad Tracking, Spotlight web/Siri Suggestions, on-device dictation & translation |
| `--preset balanced` | <!-- sync:balanced_total -->34<!-- /sync:balanced_total --> | <!-- sync:balanced_unsup -->13<!-- /sync:balanced_unsup --> | `telemetry` + Siri, Siri Lock Screen, Siri AI, external cloud AI (ChatGPT), Writing Tools/Genmoji/Playground/summaries (`supervised`), Handoff, roaming fetch |
| `--disable-all` | <!-- sync:restrictions_total -->57<!-- /sync:restrictions_total --> | <!-- sync:restrictions_unsupervised -->18<!-- /sync:restrictions_unsupervised --> | `balanced` + iCloud sync/backup toggles, AirDrop, Podcasts/Music/News/Game Center, plus high-risk Safari & Messages |

- **<!-- sync:dns_presets -->6<!-- /sync:dns_presets --> Encrypted DNS blockers** (`adguard`, `mullvad-base`, `mullvad-all`, `quad9`, `controld`, `nextdns:<id>`, or custom `https://...` / DoT host). Pass `--dns-apple-only` to route *only* safe Apple telemetry/ad domains (`SupplementalMatchDomains`) through the blocker without changing your normal DNS.
- **<!-- sync:stock_apps -->20<!-- /sync:stock_apps --> removable built-in Apple apps** (Tips, Stocks, News, TV, Podcasts, Books, Freeform, Journal, etc.) uninstallable over USB/Wi-Fi via `pymobiledevice3` (core SSV apps like Settings, Safari, Messages, Phone, and App Store are never touched).
- **watchOS support**: <!-- sync:watch_profile_keys -->5<!-- /sync:watch_profile_keys --> Apple-supported profile keys (`allowAssistantWhileLocked`, `forceOnDeviceOnlyDictation`, `forceOnDeviceOnlyTranslation`, `allowAssistantUserGeneratedContent`, `allowAutomaticAppDownloads`) + a persistent **<!-- sync:watch_checklist -->10<!-- /sync:watch_checklist -->-item watchOS Companion Checklist** (`./debloat --target watchos` or `--watch-checklist`).
- **Live Telemetry Daemon Audit**: checks <!-- sync:telemetry_daemons -->32<!-- /sync:telemetry_daemons --> background iOS/iPadOS telemetry, ad, Siri & Apple Intelligence daemons via `pymobiledevice3 processes ps`.

---

## Wireless Delivery (Zero Cable Required)

1. **Terminal QR server** (`./debloat --preset telemetry --dns adguard --deliver qr` or `--serve`):
   - Renders a Unicode QR code in your terminal and starts a one-time tokenized local HTTP server (`Content-Type: application/x-apple-aspen-config`).
   - Scan with your iPhone or iPad Camera -> tap Safari banner -> *Settings -> Profile Downloaded -> Install*.
2. **AirDrop** (`./debloat --preset telemetry --deliver airdrop`):
   - Exports the `.mobileconfig` and highlights it in macOS Finder for right-click -> *Share -> AirDrop*.
3. **Custom presets & labels**:
   - Export preset template: `./debloat --list > ~/.ios-debloat/presets/mine.txt` (delete lines you want to keep ON), then `./debloat --preset mine`.
   - Append custom restriction keys in `~/.ios-debloat/labels.txt`.

---

## Optional USB / Wi-Fi Control (`pymobiledevice3`)

To enable live `--audit` (process inspection + crash dump count), direct USB/Wi-Fi `.mobileconfig` push/remove, and one-click stock Apple bloat app removal, install [`pymobiledevice3`](https://github.com/doronz88/pymobiledevice3) separately:

```bash
uv tool install --managed-python pymobiledevice3
```

Then plug in your iPhone/iPad once and tap **Trust**:

```bash
./debloat --status
./debloat --audit
./debloat --preset telemetry --dns adguard --deliver usb
./debloat --enable-all --deliver usb         # cleanly removes the profile
```

---

## Apple Intelligence & OS 26.4 / 27+ DDM Export

Apple deprecated several AI/Siri/Keyboard `.mobileconfig` keys in OS 26.4/27.0 in favor of Declarative Device Management (DDM) while keeping them functional in OS 27.2. You can export Apple's exact replacement DDM JSON declarations anytime:

```bash
./debloat --preset balanced --supervised --export-ddm ./ddm-configs
```

---

## Supervised Mode (Optional)

Like `mac-os-debloat`'s SIP toggle, **Supervision** is completely optional and never touches your data automatically. Run `./debloat --supervise-guide` for safe step-by-step instructions (Finder backup + Apple Configurator or `pymobiledevice3 profile supervise`), or `./debloat --create-keybag` to generate a local PEM keybag (`~/.ios-debloat/supervision/keybag.pem`) for silent USB pushes.

---

## AI Agents & Automation

- [`AGENTS.md`](AGENTS.md) — machine-readable CLI rules, safety invariants, and `--json` usage
- [`llms.txt`](llms.txt) — LLM/agent repository index
- [`skills/ios-debloat/SKILL.md`](skills/ios-debloat/SKILL.md) — Agent Skill definition (`npx skills add will702/ios-debloat`)

---

## Testing & Verification

```bash
python3 -m unittest discover -s tests -v
python3 extras/sync_readme.py --check
```

---

License: [MIT](LICENSE)

**Keywords:** iOS debloat, iPadOS debloat, watchOS debloat, Apple Watch debloat, disable Apple Intelligence iPhone, disable Siri telemetry, iOS mobileconfig privacy profile, encrypted DNS Apple telemetry blocker, iOS configuration profile generator, Declarative Device Management JSON, pymobiledevice3 audit, iOS hardening TUI, zero dependency Python CLI.
