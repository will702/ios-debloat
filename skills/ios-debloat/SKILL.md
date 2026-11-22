---
name: ios-debloat
description: >-
  Debloat and privacy-harden iPhone (iOS), iPad (iPadOS), and Apple Watch (watchOS)
  from the terminal without jailbreaking. Generates reversible Apple .mobileconfig
  profiles, OS 26.4/27+ Declarative Device Management (DDM) JSON, Encrypted DNS
  telemetry blockers, terminal QR servers, watchOS checklists, and live USB/Wi-Fi
  daemon audits via pymobiledevice3.
---

# `ios-debloat` Agent Skill

Use this skill when a user wants to:
- Disable iPhone, iPad, or Apple Watch telemetry, personalized ads, Siri Suggestions, or Apple Intelligence bloat
- Audit live running iOS/iPadOS telemetry daemons (`analyticsd`, `adprivacyd`, `promotedcontentd`, `assistantd`, `modelcatalogd`, `privatecloudcomputed`)
- Generate a `.mobileconfig` profile or DDM JSON declaration (`com.apple.applicationaccess`, `com.apple.dnsSettings.managed`, `intelligence.settings`, `siri.settings`)
- Set up split Encrypted DNS blocking for Apple telemetry domains without changing general DNS
- Serve a `.mobileconfig` wirelessly via terminal QR code or push over USB/Wi-Fi with `pymobiledevice3`

## Setup

If `ios-debloat` is not cloned locally yet:

```bash
git clone https://github.com/will702/ios-debloat.git
cd ios-debloat
```

Zero runtime dependencies — uses macOS system `python3` (3.9+). For optional live USB/Wi-Fi auditing and direct profile pushing, install `pymobiledevice3` separately:

```bash
uv tool install --managed-python pymobiledevice3
```

## Safe Read-Only Inspection Workflow

Always start with read-only checks before suggesting or applying changes:

```bash
./debloat --status --json
./debloat --audit --json
./debloat --watch-checklist
```

Inspect what a preset changes before generating a profile:

```bash
./debloat --preset telemetry --dry-run
./debloat --preset balanced --dry-run
```

## Common Actions (Ask User Confirmation Before Mutating Connected Device)

1. **Generate & serve wireless QR profile (unsupervised, zero wipe, 100% reversible):**
   ```bash
   ./debloat --preset telemetry --dns adguard --dns-apple-only --deliver qr
   ```
2. **Export `.mobileconfig` file without starting a server:**
   ```bash
   ./debloat --preset balanced --dns mullvad-base --out ./debloat.mobileconfig
   ```
3. **Export Apple OS 26.4/27+ DDM JSON declarations (supervised MDM):**
   ```bash
   ./debloat --preset balanced --supervised --export-ddm ./ddm-configs
   ```
4. **Push directly over USB (only after user confirmation):**
   ```bash
   ./debloat --preset telemetry --dns adguard --deliver usb
   ```
5. **Revert completely:**
   ```bash
   ./debloat --enable-all --deliver usb   # or remove profile in iOS Settings -> General -> VPN & Device Management
   ```

## Safety Rules

- Never run `--deliver usb` (install/remove profile or uninstall stock apps) without explicit user approval.
- Never attempt exploit-based partial-restore modifications on iOS 27.
- Keep `PayloadRemovalDisallowed = False` on all generated profiles.
