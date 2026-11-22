# AGENTS.md — AI Agent Guide for `ios-debloat`

Repository: https://github.com/will702/ios-debloat  
Purpose: Zero-dependency Python 3.9+ TUI & CLI to debloat **iOS, iPadOS, and watchOS (26/27)** via reversible Apple Configuration Profiles (`.mobileconfig`), Declarative Device Management (DDM) JSON, Encrypted DNS telemetry blocking, and optional `pymobiledevice3` USB/Wi-Fi auditing.

---

## Quick Verification & Test Commands

```bash
python3 -m unittest discover -s tests -v
python3 extras/sync_readme.py --check
```

- **Python compatibility:** Target macOS system `python3` (`3.9+`), stdlib-only (`from __future__ import annotations` required in all `.py` files; no runtime dependencies).
- **License boundary:** MIT licensed. `pymobiledevice3` (GPL-3.0) is invoked strictly as an optional external CLI subprocess in `ios_debloat/device.py` — never import it directly.

---

## Safe vs. Mutating CLI Commands for Agents

### Read-Only / Offline Inspection (Always Safe)
- `./debloat --status --json` — returns device info, mode (`unsupervised` / `supervised`), catalog counts, active disabled key count, active DNS, and watchOS checklist progress.
- `./debloat --audit --json` — returns `mode` (`live` when USB + `pymobiledevice3` present, else `offline`), `privacy_checks`, `running_telemetry_daemons`, `removable_stock_apps_installed`, `crash_reports_count`, and `findings`.
- `./debloat --preset telemetry --dry-run` — returns JSON preview of what `.mobileconfig` keys would be applied.
- `./debloat --list` — prints full catalog in preset syntax (`--preset telemetry` / `--preset balanced` filters it).
- `./debloat --export-blocklist domains|adguard|hosts` — prints safe Apple telemetry/ad DNS domains (preserves iCloud, iMessage, APNs, App Store, OS updates).
- `./debloat --watch-checklist` — shows 10 manual watchOS settings with progress stored in `~/.ios-debloat/watch-checklist.json`.

### File Generation / Wireless Delivery (Safe Local Exports)
- `./debloat --preset telemetry --dns adguard --dns-apple-only --out out.mobileconfig` — builds & validates (via `plistlib` + `/usr/bin/plutil -lint`) an XML `.mobileconfig`.
- `./debloat --preset balanced --supervised --export-ddm ./ddm` — emits Apple OS 26.4/27+ DDM JSON declarations.
- `./debloat --preset telemetry --dns adguard --deliver qr` — prints pure-Python terminal QR code and starts local LAN HTTP server (`application/x-apple-aspen-config`).

### Device-Mutating Commands (Require Explicit User Confirmation)
- `./debloat --deliver usb` — pushes `.mobileconfig` (or uninstalls allowlisted removable stock Apple apps) on a connected device via `pymobiledevice3`.
- `./debloat --enable-all --deliver usb` — removes `io.github.ios-debloat.profile.<target>` from device.

---

## Safety Invariants (Do Not Break)

1. **Always reversible:** `PayloadRemovalDisallowed` must remain `False` in `profile_builder.py`.
2. **Unsupervised isolation:** Never emit `supervised=True` restriction keys when `supervised=False`.
3. **Removed OS 27 keys:** Do not re-add `enforcedSoftwareUpdateDelay` or `forceDelayedSoftwareUpdates` (removed in iOS 27.0).
4. **Stock app allowlist:** `uninstall_stock_app()` in `device.py` must strictly enforce `REMOVABLE_STOCK_APP_IDS` from `catalog.py` (never core SSV apps like Settings, Safari, Messages, Phone, or App Store).
5. **No exploit-based partial-restore:** Never add Nugget-style backup partial-restore daemon edits (unsafe / causes data loss on iOS 27).
6. **Never auto-erase:** `supervision.py` only creates local PEM keybags (`0600`) and prints safe manual instructions.

---

## File Map

| File | Responsibility |
| :--- | :--- |
| `debloat` | Executable root CLI/TUI launcher |
| `ios_debloat/catalog.py` | Apple-schema-verified restrictions, DNS presets, telemetry domains, 20 removable stock apps, watchOS checklist, 32 daemon watchlist |
| `ios_debloat/profile_builder.py` | `.mobileconfig` XML builder, DDM JSON exporter, `plutil -lint` validator, OpenSSL signer |
| `ios_debloat/qr.py` | Pure-Python ISO/IEC 18004 QR Code encoder (Versions 1–8, ECC-L) + terminal Unicode renderer |
| `ios_debloat/deliver.py` | `.mobileconfig` export, LAN HTTP QR server, macOS Finder AirDrop reveal |
| `ios_debloat/device.py` | Optional `pymobiledevice3` CLI wrapper + `xcrun devicectl` fallback + real iOS `GetProfileList` reconciliation |
| `ios_debloat/audit.py` | `--status` & `--audit` report builders and formatters |
| `ios_debloat/state.py` | `~/.ios-debloat` snapshots (`--restore`), `last-state.json`, watchOS checklist, user presets/labels |
| `ios_debloat/supervision.py` | Local PEM keybag generator + guided supervision instructions |
| `ios_debloat/tui.py` | Blocking `curses` TUI matching `OleksandrKrupko/mac-os-debloat` |
| `ios_debloat/cli.py` | CLI parser and command dispatcher |
| `extras/sync_readme.py` | Keeps `README.md` catalog counts synchronized with `catalog.py` |
