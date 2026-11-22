"""Apple .mobileconfig XML profile & Declarative Device Management (DDM) JSON builder."""
from __future__ import annotations

import json
import plistlib
import shutil
import subprocess
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

from ios_debloat.catalog import (
    APPLE_TELEMETRY_DOMAINS,
    SILENCE_NOTIFICATION_BUNDLES,
    build_catalog,
)
from ios_debloat.models import Item, Section

PROFILE_NAMESPACE = uuid.UUID("7f3b5c4a-9e21-4d8e-b3c2-1a5f8e9d0c41")


def profile_identifier(target: str = "all") -> str:
    """Return the deterministic PayloadIdentifier for a target profile."""
    return f"io.github.ios-debloat.profile.{target}"


def _uuid_for(key: str) -> str:
    return str(uuid.uuid5(PROFILE_NAMESPACE, key)).upper()


def _parse_custom_dns(spec: str) -> dict[str, Any]:
    raw = spec.strip()
    if raw.startswith("nextdns:"):
        profile_id = raw.split(":", 1)[1].strip()
        if not profile_id:
            raise ValueError("NextDNS requires a profile ID, e.g. --dns nextdns:abc123")
        return {
            "id": "dns:nextdns",
            "protocol": "HTTPS",
            "url": f"https://dns.nextdns.io/{profile_id}",
            "addresses": [],
        }
    if raw.startswith("https://"):
        return {
            "id": "dns:custom",
            "protocol": "HTTPS",
            "url": raw,
            "addresses": [],
        }
    if raw.startswith("tls://"):
        host = raw[len("tls://") :].strip("/")
        if not host:
            raise ValueError("TLS DNS URI requires a hostname")
        return {
            "id": "dns:custom",
            "protocol": "TLS",
            "name": host,
            "addresses": [],
        }
    if "." in raw and " " not in raw and "/" not in raw:
        return {
            "id": "dns:custom",
            "protocol": "TLS",
            "name": raw,
            "addresses": [],
        }
    raise ValueError(f"Unknown DNS preset or URI: {spec!r}")


def apply_dns_selection(sections: list[Section], dns_spec: Optional[str]) -> Optional[dict[str, Any]]:
    """Select a DNS item in `sections` from a CLI `--dns` string, or read the currently selected DNS."""
    dns_items = [it for sec in sections for it in sec.items if it.kind == "dns"]
    if dns_spec is not None:
        normalized = dns_spec.strip()
        if not normalized.startswith("dns:") and ":" not in normalized and "://" not in normalized and "." not in normalized:
            candidate_id = f"dns:{normalized}"
        else:
            candidate_id = normalized

        matched: Optional[Item] = None
        for it in dns_items:
            if it.id == candidate_id or it.label == normalized:
                matched = it
                break

        if matched is not None and matched.id == "dns:nextdns":
            raise ValueError("NextDNS requires a profile ID, e.g. --dns nextdns:abc123")

        if matched is not None:
            for it in dns_items:
                it.selected = it is matched
            if matched.dns_config is None:
                return None
            cfg = dict(matched.dns_config)
            cfg["id"] = matched.id
            return cfg

        # Custom NextDNS ID, DoH URL, or DoT hostname
        custom_cfg = _parse_custom_dns(normalized)
        for it in dns_items:
            it.selected = it.id == custom_cfg["id"]
        return custom_cfg

    # Read from TUI selection
    for it in dns_items:
        if it.selected:
            if it.dns_config is None:
                return None
            cfg = dict(it.dns_config)
            if "{id}" in str(cfg.get("url", "")):
                raise ValueError("NextDNS requires a profile ID (--dns nextdns:<id>)")
            cfg["id"] = it.id
            return cfg
    return None


def build_mobileconfig(
    sections: list[Section],
    *,
    target: str = "all",
    supervised: bool = False,
    dns_apple_only: bool = False,
    silence_stock_notifications: bool = False,
    dns_override: Optional[dict[str, Any]] = None,
    dns_spec: Optional[str] = None,
) -> tuple[bytes, dict[str, Any]]:
    """Build an Apple XML .mobileconfig profile from the current selection in `sections`.

    Returns `(xml_bytes, summary_dict)`.
    """
    payload_content: list[dict[str, Any]] = []
    applied_restrictions: list[str] = []
    skipped_supervised: list[str] = []

    restrictions_dict: dict[str, Any] = {}
    for sec in sections:
        for it in sec.items:
            if it.kind != "restriction" or not it.payload_key:
                continue
            if it.selected:
                # Feature stays ON / default
                continue
            if it.supervised and not supervised:
                skipped_supervised.append(it.payload_key)
                continue
            restrictions_dict[it.payload_key] = it.debloat_value
            applied_restrictions.append(it.payload_key)

    if restrictions_dict:
        res_payload: dict[str, Any] = {
            "PayloadDescription": "Privacy, telemetry, Siri, and Apple Intelligence restrictions",
            "PayloadDisplayName": "Debloat Restrictions",
            "PayloadIdentifier": f"{profile_identifier(target)}.restrictions",
            "PayloadOrganization": "ios-watchos-ipados-debloat",
            "PayloadType": "com.apple.applicationaccess",
            "PayloadUUID": _uuid_for(f"restrictions:{target}"),
            "PayloadVersion": 1,
        }
        res_payload.update(restrictions_dict)
        payload_content.append(res_payload)

    dns_cfg = dns_override if dns_override is not None else apply_dns_selection(sections, dns_spec)
    dns_id: Optional[str] = None
    if dns_cfg:
        dns_id = str(dns_cfg.get("id", "dns:custom"))
        dns_settings: dict[str, Any] = {
            "DNSProtocol": dns_cfg["protocol"],
            "AllowFailover": True,
        }
        if dns_cfg["protocol"] == "HTTPS":
            dns_settings["ServerURL"] = str(dns_cfg["url"])
        else:
            dns_settings["ServerName"] = str(dns_cfg["name"])
        addresses = list(dns_cfg.get("addresses") or [])
        if addresses:
            dns_settings["ServerAddresses"] = addresses
        if dns_apple_only:
            dns_settings["SupplementalMatchDomains"] = list(APPLE_TELEMETRY_DOMAINS)

        payload_content.append(
            {
                "PayloadDescription": "Encrypted DNS telemetry & ad blocking",
                "PayloadDisplayName": f"Encrypted DNS ({dns_id})",
                "PayloadIdentifier": f"{profile_identifier(target)}.dns",
                "PayloadOrganization": "ios-watchos-ipados-debloat",
                "PayloadType": "com.apple.dnsSettings.managed",
                "PayloadUUID": _uuid_for(f"dns:{target}"),
                "PayloadVersion": 1,
                "DNSSettings": dns_settings,
                "OnDemandRules": [{"Action": "Connect"}],
            }
        )

    notifications_silenced = False
    if silence_stock_notifications and supervised:
        notif_items = [
            {
                "BundleIdentifier": bundle_id,
                "NotificationsEnabled": False,
                "ShowInNotificationCenter": False,
                "ShowInLockScreen": False,
                "AlertType": 0,
                "BadgesEnabled": False,
                "SoundsEnabled": False,
            }
            for bundle_id in SILENCE_NOTIFICATION_BUNDLES
        ]
        payload_content.append(
            {
                "PayloadDescription": "Silence noisy built-in Apple stock app notifications",
                "PayloadDisplayName": "Stock App Notification Rules",
                "PayloadIdentifier": f"{profile_identifier(target)}.notifications",
                "PayloadOrganization": "ios-watchos-ipados-debloat",
                "PayloadType": "com.apple.notificationsettings",
                "PayloadUUID": _uuid_for(f"notifications:{target}"),
                "PayloadVersion": 1,
                "NotificationSettings": notif_items,
            }
        )
        notifications_silenced = True

    mode_label = "Supervised" if supervised else "Unsupervised"
    profile: dict[str, Any] = {
        "PayloadContent": payload_content,
        "PayloadDescription": (
            f"Reversible {mode_label.lower()} privacy & debloat settings for {target}. "
            "Remove anytime in Settings -> General -> VPN & Device Management."
        ),
        "PayloadDisplayName": f"iOS/iPadOS/watchOS Debloat ({mode_label})",
        "PayloadIdentifier": profile_identifier(target),
        "PayloadOrganization": "ios-watchos-ipados-debloat",
        "PayloadRemovalDisallowed": False,
        "PayloadType": "Configuration",
        "PayloadUUID": _uuid_for(f"root:{target}"),
        "PayloadVersion": 1,
    }
    xml_bytes = plistlib.dumps(profile, fmt=plistlib.FMT_XML, sort_keys=True)
    summary = {
        "identifier": profile_identifier(target),
        "target": target,
        "supervised": supervised,
        "restriction_count": len(applied_restrictions),
        "restrictions": applied_restrictions,
        "skipped_supervised": skipped_supervised,
        "dns": dns_id,
        "dns_apple_only": bool(dns_cfg and dns_apple_only),
        "notifications_silenced": notifications_silenced,
        "payload_count": len(payload_content),
    }
    return xml_bytes, summary


def _set_nested(mapping: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cur = mapping
    for key in path[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[path[-1]] = value


def export_ddm_declarations(
    sections: list[Section],
    out_dir: Path,
    *,
    supervised: bool = True,
) -> list[Path]:
    """Export Apple Declarative Device Management (DDM) JSON configs for OS 26.4/27+."""
    out_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, dict[str, Any]] = {}

    for sec in sections:
        for it in sec.items:
            if it.kind != "restriction" or it.selected or not it.ddm_spec:
                continue
            if it.supervised and not supervised:
                continue
            decl_type, key_path, value = it.ddm_spec
            payload = grouped.setdefault(decl_type, {})
            _set_nested(payload, key_path, value)

    written: list[Path] = []
    for decl_type, payload in sorted(grouped.items()):
        doc = {
            "Type": decl_type,
            "Identifier": _uuid_for(f"ddm:id:{decl_type}"),
            "ServerToken": _uuid_for(f"ddm:token:{decl_type}:{json.dumps(payload, sort_keys=True)}"),
            "Payload": payload,
        }
        filename = f"{decl_type}.json"
        dest = out_dir / filename
        dest.write_text(json.dumps(doc, indent=4, sort_keys=False) + "\n", encoding="utf-8")
        written.append(dest)
    return written


def sign_profile(profile_bytes: bytes, cert_path: Path, key_path: Path) -> bytes:
    """Sign a .mobileconfig using OpenSSL S/MIME (DER PKCS#7)."""
    openssl = shutil.which("openssl") or "/usr/bin/openssl"
    with tempfile.TemporaryDirectory(prefix="ios-debloat-sign-") as tmp:
        tmp_dir = Path(tmp)
        in_file = tmp_dir / "unsigned.mobileconfig"
        out_file = tmp_dir / "signed.mobileconfig"
        in_file.write_bytes(profile_bytes)
        res = subprocess.run(
            [
                openssl,
                "smime",
                "-sign",
                "-signer",
                str(cert_path),
                "-inkey",
                str(key_path),
                "-nodetach",
                "-outform",
                "der",
                "-in",
                str(in_file),
                "-out",
                str(out_file),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"openssl smime -sign failed: {res.stderr.strip() or res.stdout.strip()}")
        return out_file.read_bytes()


def validate_profile(
    profile_bytes: bytes,
    *,
    expect_unsupervised: bool = False,
) -> tuple[bool, list[str]]:
    """Validate XML plist structure, safety invariants, and macOS plutil -lint."""
    errors: list[str] = []
    try:
        doc = plistlib.loads(profile_bytes)
    except Exception as exc:
        return False, [f"Invalid XML plist: {exc}"]

    if not isinstance(doc, dict):
        return False, ["Top-level plist object is not a dict"]

    if doc.get("PayloadType") != "Configuration":
        errors.append(f"Expected PayloadType='Configuration', got {doc.get('PayloadType')!r}")
    for required in ("PayloadIdentifier", "PayloadUUID", "PayloadDisplayName"):
        if not doc.get(required):
            errors.append(f"Missing or empty top-level key: {required}")
    if doc.get("PayloadVersion") != 1:
        errors.append(f"Expected PayloadVersion=1, got {doc.get('PayloadVersion')!r}")
    if doc.get("PayloadRemovalDisallowed") is not False:
        errors.append("PayloadRemovalDisallowed must be False to keep profile reversible")

    content = doc.get("PayloadContent")
    if not isinstance(content, list):
        errors.append("PayloadContent must be a list")
    else:
        if expect_unsupervised:
            supervised_keys = {
                it.payload_key
                for sec in build_catalog("all")
                for it in sec.items
                if it.kind == "restriction" and it.supervised and it.payload_key
            }
            for sub in content:
                if isinstance(sub, dict) and sub.get("PayloadType") == "com.apple.applicationaccess":
                    leaked = sorted(set(sub.keys()) & supervised_keys)
                    if leaked:
                        errors.append(f"Unsupervised profile contains supervised keys: {leaked}")

    plutil = shutil.which("plutil") or ("/usr/bin/plutil" if Path("/usr/bin/plutil").exists() else None)
    if plutil:
        with tempfile.NamedTemporaryFile(suffix=".mobileconfig") as tmp:
            tmp.write(profile_bytes)
            tmp.flush()
            res = subprocess.run([plutil, "-lint", "-s", tmp.name], capture_output=True, text=True, check=False)
            if res.returncode != 0:
                msg = (res.stderr or res.stdout).strip() or f"plutil exited {res.returncode}"
                errors.append(f"plutil -lint failed: {msg}")

    return len(errors) == 0, errors


def build_dns_only_mobileconfig(
    dns_spec: str,
    *,
    dns_apple_only: bool = False,
    target: str = "all",
) -> tuple[bytes, dict[str, Any]]:
    """Convenience helper to build a profile with only an Encrypted DNS payload."""
    sections = deepcopy(build_catalog(target))
    return build_mobileconfig(
        sections,
        target=target,
        supervised=False,
        dns_apple_only=dns_apple_only,
        dns_spec=dns_spec,
    )
