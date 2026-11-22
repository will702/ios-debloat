"""Guided supervision helper & local PEM keybag creation (never auto-erases)."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from ios_debloat import device as device_mod
from ios_debloat.state import default_keybag_path


def create_supervision_keybag(
    out_path: Optional[Path] = None,
    *,
    organization: str = "Self-Supervised",
) -> Path:
    """Create a local supervision identity PEM (keybag) with 0600 permissions.

    Uses `pymobiledevice3 profile create-keybag` when installed, or falls back to
    OpenSSL self-signed X.509 certificate + RSA private key PEM.
    """
    dest = Path(out_path or default_keybag_path()).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()

    pmd3 = device_mod.pmd3_path()
    if pmd3 and (shutil.which(pmd3) or Path(pmd3).is_file()):
        try:
            res = subprocess.run(
                [pmd3, "profile", "create-keybag", str(dest), organization],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and dest.is_file():
                dest.chmod(0o600)
                return dest
        except OSError:
            pass

    openssl = shutil.which("openssl") or "/usr/bin/openssl"
    with tempfile.TemporaryDirectory(prefix="ios-debloat-kb-") as tmp:
        tmp_dir = Path(tmp)
        key_file = tmp_dir / "key.pem"
        cert_file = tmp_dir / "cert.pem"
        res = subprocess.run(
            [
                openssl,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key_file),
                "-out",
                str(cert_file),
                "-days",
                "3650",
                "-subj",
                f"/CN={organization}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Failed to generate supervision keybag: {res.stderr.strip() or res.stdout.strip()}")
        combined = key_file.read_text(encoding="utf-8") + cert_file.read_text(encoding="utf-8")
        dest.write_text(combined, encoding="utf-8")
        dest.chmod(0o600)
        return dest


def supervision_guide_text(
    keybag_path: Optional[Path] = None,
    *,
    supervised_count: int = 0,
    currently_supervised: bool = False,
) -> str:
    """Return safe, step-by-step supervision instructions without ever erasing data."""
    kb = keybag_path or default_keybag_path()
    kb_status = f"exists ({kb})" if kb.is_file() else f"not created yet (run `./debloat --create-keybag` -> {kb})"
    status_line = "SUPERVISED" if currently_supervised else "UNSUPERVISED"

    return f"""\
=== Guided Device Supervision (mirrors mac-os-debloat's SIP flow) ===

Current detected mode : {status_line}
Supervision-only keys : {supervised_count} additional Apple Intelligence / Siri / Keyboard / Media keys
Local keybag PEM      : {kb_status}

What Supervision Unlocks
  - Full Apple Intelligence restrictions (Writing Tools, Genmoji, Image Playground,
    Mail/Safari/Notes summaries, Visual Intelligence, Apple Intelligence Report)
  - Deeper Siri & Keyboard locks (Dictation, Definition Lookup, Predictive Text)
  - Stock service disables (News, Game Center, Podcasts, Music, App Clips, AirDrop)
  - Silent zero-tap USB `.mobileconfig` installs using `--keybag`
  - Paired Apple Watch MDM/DDM enrollment & `allowAutomaticAppDownloads=false`

Trade-offs & Safety Notice
  - Apple requires a factory-fresh (erased) iPhone or iPad to enable Supervision.
  - This tool NEVER automatically erases your device. Back up to your Mac first!
  - Supervised devices display a small "This iPhone/iPad is supervised..." notice
    in Settings and on the Lock Screen.
  - To revert completely later: back up -> Erase All Content and Settings -> restore.

Recommended Path (Apple Configurator on Mac — easiest)
  1. Make a full encrypted Finder backup of your iPhone / iPad on your Mac.
  2. Install "Apple Configurator" (free from the Mac App Store).
  3. In Apple Configurator -> Blueprints / Prepare -> Manual Configuration:
     check "Supervise devices" (optionally skip Apple Intelligence & Setup panes).
  4. Erase your iPhone/iPad, complete Prepare in Apple Configurator, then restore
     your Finder backup (Supervision stays intact across restore).
  5. Re-run `./debloat` — supervised keys unlock automatically.

Optional CLI Path (with pymobiledevice3 on a freshly erased device)
  1. Generate a reusable supervision keybag locally:
       ./debloat --create-keybag "Self-Supervised"
  2. On a freshly erased device at the Hello / Setup screen (plugged into USB):
       pymobiledevice3 profile supervise "Self-Supervised" --keybag "{kb}"
  3. Push profiles silently without on-device prompts:
       ./debloat --preset balanced --supervised --keybag "{kb}" --deliver usb
"""
