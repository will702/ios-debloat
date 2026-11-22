"""Optional pymobiledevice3 & xcrun devicectl adapter (strictly optional external CLIs)."""
from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from ios_debloat.catalog import DNS_PRESETS, REMOVABLE_STOCK_APP_IDS, build_catalog
from ios_debloat.models import DeviceInfo
from ios_debloat.state import load_last_state, profiles_dir

Runner = Callable[[list[str], Optional[dict[str, str]]], subprocess.CompletedProcess]


def default_runner(cmd: list[str], env: Optional[dict[str, str]] = None) -> subprocess.CompletedProcess:
    """Execute an external command safely and capture text output."""
    return subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)


def pmd3_path() -> Optional[str]:
    """Locate `pymobiledevice3` executable if installed."""
    override = os.environ.get("IOS_DEBLOAT_PMD3")
    if override:
        return override
    found = shutil.which("pymobiledevice3")
    if found:
        return found
    local_bin = Path.home() / ".local" / "bin" / "pymobiledevice3"
    if local_bin.is_file() and os.access(str(local_bin), os.X_OK):
        return str(local_bin)
    return None


def _build_env(udid: Optional[str] = None) -> dict[str, str]:
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    if udid:
        env["PYMOBILEDEVICE3_UDID"] = udid
    return env


def _transport_flags(wifi: bool = False, wifi_host: Optional[str] = None) -> list[str]:
    if wifi_host:
        return ["--mobdev2-host", wifi_host]
    if wifi:
        return ["--mobdev2"]
    return []


def _run_pmd3(
    args: list[str],
    *,
    udid: Optional[str] = None,
    runner: Optional[Runner] = None,
) -> subprocess.CompletedProcess:
    exe = pmd3_path()
    if not exe:
        raise RuntimeError("pymobiledevice3 is not installed")
    run = runner or default_runner
    return run([exe, *args], _build_env(udid))


def _parse_json_stdout(res: subprocess.CompletedProcess, context: str) -> Any:
    if res.returncode != 0:
        err = (res.stderr or res.stdout).strip() or f"exit code {res.returncode}"
        raise RuntimeError(f"{context} failed: {err}")
    text = res.stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError as exc:
        raise RuntimeError(f"{context} returned invalid JSON: {exc}") from exc


def get_cloud_configuration(
    *,
    udid: Optional[str] = None,
    wifi: bool = False,
    wifi_host: Optional[str] = None,
    runner: Optional[Runner] = None,
) -> Optional[dict[str, Any]]:
    """Query `pymobiledevice3 profile cloud-configuration` to inspect supervision status."""
    args = ["profile", "cloud-configuration", *_transport_flags(wifi, wifi_host)]
    res = _run_pmd3(args, udid=udid, runner=runner)
    if res.returncode != 0:
        return None
    text = res.stdout.strip()
    if not text or text == "null":
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def devicectl_list_devices(runner: Optional[Runner] = None) -> list[DeviceInfo]:
    """Fallback read-only detection via macOS `xcrun devicectl` when pymobiledevice3 is absent."""
    if sys.platform != "darwin" or not shutil.which("xcrun"):
        return []
    run = runner or default_runner
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        res = run(
            ["xcrun", "devicectl", "list", "devices", "--json-output", str(tmp_path)],
            _build_env(),
        )
        if res.returncode != 0 or not tmp_path.is_file():
            return []
        data = json.loads(tmp_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    devices: list[DeviceInfo] = []
    raw_list = (data.get("result") or {}).get("devices") or []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        props = item.get("properties") or {}
        hw = props.get("hardware") or item.get("hardwareProperties") or {}
        sw = props.get("software") or item.get("deviceProperties") or {}
        st = props.get("state") or item.get("deviceProperties") or {}
        conn = props.get("connection") or item.get("connectionProperties") or {}

        udid = str(hw.get("udid") or "")
        product_type = str(hw.get("productType") or "")
        plat_raw = str(hw.get("platform") or "").lower()
        if plat_raw not in ("ios", "ipados"):
            continue
        platform = "ipados" if product_type.startswith("iPad") else "ios"
        name = str(st.get("name") or hw.get("deviceType") or "Apple Device")
        os_ver_obj = sw.get("osVersionNumber")
        if isinstance(os_ver_obj, dict):
            os_version = str(os_ver_obj.get("stringValue") or "")
        else:
            os_version = str(os_ver_obj or "")
        transport = str(conn.get("transportType") or "wired")
        conn_label = "wifi" if "wifi" in transport.lower() or "network" in transport.lower() else "devicectl"
        if udid:
            devices.append(
                DeviceInfo(
                    udid=udid,
                    name=name,
                    product_type=product_type,
                    os_version=os_version,
                    platform=platform,
                    supervised=False,
                    connection=conn_label,
                    pmd3_available=False,
                )
            )
    return devices


def list_devices(
    *,
    wifi: bool = False,
    wifi_host: Optional[str] = None,
    runner: Optional[Runner] = None,
) -> list[DeviceInfo]:
    """List connected iOS/iPadOS devices using pymobiledevice3, or devicectl fallback."""
    if pmd3_path() is not None:
        args = ["usbmux", "list"]
        if wifi:
            args.append("--network")
        res = _run_pmd3(args, runner=runner)
        if res.returncode == 0:
            raw = _parse_json_stdout(res, "pymobiledevice3 usbmux list")
            if isinstance(raw, list) and raw:
                out: list[DeviceInfo] = []
                for entry in raw:
                    if not isinstance(entry, dict):
                        continue
                    udid = str(entry.get("UniqueDeviceID") or "")
                    product_type = str(entry.get("ProductType") or "")
                    platform = "ipados" if product_type.startswith("iPad") else "ios"
                    conn_type = str(entry.get("ConnectionType") or "USB")
                    conn = "wifi" if "network" in conn_type.lower() or wifi or wifi_host else "usb"
                    cloud = get_cloud_configuration(
                        udid=udid or None,
                        wifi=wifi,
                        wifi_host=wifi_host,
                        runner=runner,
                    )
                    supervised = bool(cloud and cloud.get("IsSupervised"))
                    out.append(
                        DeviceInfo(
                            udid=udid,
                            name=str(entry.get("DeviceName") or product_type or "iPhone/iPad"),
                            product_type=product_type,
                            os_version=str(entry.get("ProductVersion") or ""),
                            platform=platform,
                            supervised=supervised,
                            connection=conn,
                            pmd3_available=True,
                        )
                    )
                if out:
                    return out

    return devicectl_list_devices(runner=runner)


def list_profiles(
    *,
    udid: Optional[str] = None,
    wifi: bool = False,
    wifi_host: Optional[str] = None,
    runner: Optional[Runner] = None,
) -> dict[str, Any]:
    """Return installed configuration profiles from the connected device."""
    args = ["profile", "list", *_transport_flags(wifi, wifi_host)]
    res = _run_pmd3(args, udid=udid, runner=runner)
    data = _parse_json_stdout(res, "pymobiledevice3 profile list")
    return data if isinstance(data, dict) else {}


def install_profile(
    profile_path: Path,
    *,
    udid: Optional[str] = None,
    keybag: Optional[Path] = None,
    wifi: bool = False,
    wifi_host: Optional[str] = None,
    runner: Optional[Runner] = None,
) -> None:
    """Install a `.mobileconfig` profile onto a connected device via pymobiledevice3."""
    args = ["profile", "install", *_transport_flags(wifi, wifi_host)]
    if keybag is not None:
        args.extend(["--keybag", str(keybag)])
    args.append(str(profile_path))
    res = _run_pmd3(args, udid=udid, runner=runner)
    if res.returncode != 0:
        err = (res.stderr or res.stdout).strip() or f"exit code {res.returncode}"
        raise RuntimeError(f"pymobiledevice3 profile install failed: {err}")


def remove_profile(
    identifier: str,
    *,
    udid: Optional[str] = None,
    wifi: bool = False,
    wifi_host: Optional[str] = None,
    runner: Optional[Runner] = None,
) -> None:
    """Remove an installed configuration profile by its PayloadIdentifier."""
    args = ["profile", "remove", *_transport_flags(wifi, wifi_host), identifier]
    res = _run_pmd3(args, udid=udid, runner=runner)
    if res.returncode != 0:
        err = (res.stderr or res.stdout).strip() or f"exit code {res.returncode}"
        raise RuntimeError(f"pymobiledevice3 profile remove failed: {err}")


def list_installed_apps(
    *,
    udid: Optional[str] = None,
    wifi: bool = False,
    wifi_host: Optional[str] = None,
    runner: Optional[Runner] = None,
) -> dict[str, Any]:
    """List installed system apps via InstallationProxy."""
    args = ["apps", "list", "--type", "System", *_transport_flags(wifi, wifi_host)]
    res = _run_pmd3(args, udid=udid, runner=runner)
    data = _parse_json_stdout(res, "pymobiledevice3 apps list")
    return data if isinstance(data, dict) else {}


def uninstall_stock_app(
    bundle_id: str,
    *,
    udid: Optional[str] = None,
    wifi: bool = False,
    wifi_host: Optional[str] = None,
    runner: Optional[Runner] = None,
) -> None:
    """Uninstall a strictly allowlisted removable stock Apple app via pymobiledevice3."""
    if bundle_id not in REMOVABLE_STOCK_APP_IDS:
        raise ValueError(
            f"Refusing to uninstall {bundle_id!r}: not in curated removable stock Apple app allowlist."
        )
    args = ["apps", "uninstall", *_transport_flags(wifi, wifi_host), bundle_id]
    res = _run_pmd3(args, udid=udid, runner=runner)
    if res.returncode != 0:
        err = (res.stderr or res.stdout).strip() or f"exit code {res.returncode}"
        raise RuntimeError(f"pymobiledevice3 apps uninstall {bundle_id} failed: {err}")


def list_running_processes(
    *,
    udid: Optional[str] = None,
    wifi: bool = False,
    wifi_host: Optional[str] = None,
    runner: Optional[Runner] = None,
) -> list[dict[str, Any]]:
    """List running iOS/iPadOS processes using `pymobiledevice3 processes ps`."""
    args = ["processes", "ps", *_transport_flags(wifi, wifi_host)]
    res = _run_pmd3(args, udid=udid, runner=runner)
    data = _parse_json_stdout(res, "pymobiledevice3 processes ps")
    processes: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for pid, info in data.items():
            if isinstance(info, dict):
                processes.append({"pid": pid, "name": str(info.get("ProcessName") or "")})
    return processes


def list_crash_reports(
    *,
    udid: Optional[str] = None,
    wifi: bool = False,
    wifi_host: Optional[str] = None,
    runner: Optional[Runner] = None,
) -> list[str]:
    """List crash & analytics report paths (`pymobiledevice3 crash ls /` emits newline-separated text)."""
    args = ["crash", "ls", "/", *_transport_flags(wifi, wifi_host)]
    res = _run_pmd3(args, udid=udid, runner=runner)
    if res.returncode != 0:
        err = (res.stderr or res.stdout).strip() or f"exit code {res.returncode}"
        raise RuntimeError(f"pymobiledevice3 crash ls failed: {err}")
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def _extract_keys_from_payloads(
    payloads: list[dict[str, Any]],
    *,
    include_restrictions: bool,
) -> tuple[set[str], Optional[str]]:
    debloat_val_map = {
        it.payload_key: it.debloat_value
        for sec in build_catalog("all")
        for it in sec.items
        if it.kind == "restriction" and it.payload_key
    }
    url_to_dns = {
        str(cfg["url"]): item_id
        for item_id, _, _, cfg in DNS_PRESETS
        if cfg and cfg.get("url") and "{id}" not in str(cfg["url"])
    }

    disabled_keys: set[str] = set()
    active_dns: Optional[str] = None

    for sub in payloads:
        if not isinstance(sub, dict):
            continue
        ptype = sub.get("PayloadType")
        if ptype == "com.apple.applicationaccess" and include_restrictions:
            for key, expected_val in debloat_val_map.items():
                if key in sub and sub[key] == expected_val:
                    disabled_keys.add(key)
        elif ptype == "com.apple.dnsSettings.managed":
            settings = sub.get("DNSSettings") or {}
            if isinstance(settings, dict):
                url = str(settings.get("ServerURL") or "")
                if url in url_to_dns:
                    active_dns = url_to_dns[url]
                elif url.startswith("https://dns.nextdns.io/"):
                    active_dns = "dns:nextdns"
                elif url or settings.get("ServerName"):
                    active_dns = "dns:custom"
    return disabled_keys, active_dns


def _load_matching_local_payloads(
    identifier: str,
    payload_uuid: Optional[str],
) -> Optional[list[dict[str, Any]]]:
    pdir = profiles_dir()
    if not pdir.is_dir():
        return None
    candidates: list[Path] = []
    latest = pdir / "latest.mobileconfig"
    if latest.is_file():
        candidates.append(latest)
    others = sorted(
        (p for p in pdir.glob("*.mobileconfig") if p.name != "latest.mobileconfig"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    candidates.extend(others)

    for path in candidates:
        try:
            doc = plistlib.loads(path.read_bytes())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        if doc.get("PayloadIdentifier") != identifier:
            continue
        if payload_uuid and doc.get("PayloadUUID") != payload_uuid:
            continue
        content = doc.get("PayloadContent")
        if isinstance(content, list):
            return content
    return None


def get_active_debloat_keys(
    profiles_response: dict[str, Any],
    *,
    local_fallback: bool = True,
) -> tuple[set[str], Optional[str]]:
    """Extract currently active debloat restriction IDs and DNS ID from `profile list` output.

    Real iOS `MCInstall GetProfileList` responses omit `PayloadContent` inside
    `ProfileMetadata` and report active status in `ProfileManifest`. When an
    `io.github.ios-debloat.*` profile is confirmed installed & active on the
    device without inline `PayloadContent`, reconcile against the matching local
    exported `.mobileconfig` (or `last-state.json`).
    """
    if not profiles_response:
        return set(), None

    disabled_keys: set[str] = set()
    active_dns: Optional[str] = None

    metadata = profiles_response.get("ProfileMetadata") or {}
    manifest = profiles_response.get("ProfileManifest") or {}
    if not isinstance(metadata, dict):
        return disabled_keys, active_dns

    for ident, meta in metadata.items():
        if not isinstance(meta, dict):
            continue
        if isinstance(manifest, dict) and ident in manifest:
            man_entry = manifest.get(ident)
            if isinstance(man_entry, dict) and man_entry.get("IsActive") is False:
                continue

        is_ours = str(ident).startswith("io.github.ios-debloat.")
        payloads = meta.get("PayloadContent")
        if isinstance(payloads, list) and payloads:
            keys, dns_id = _extract_keys_from_payloads(payloads, include_restrictions=is_ours)
            disabled_keys.update(keys)
            if dns_id:
                active_dns = dns_id
            continue

        if is_ours and local_fallback:
            local_payloads = _load_matching_local_payloads(str(ident), meta.get("PayloadUUID"))
            if local_payloads is not None:
                keys, dns_id = _extract_keys_from_payloads(local_payloads, include_restrictions=True)
                disabled_keys.update(keys)
                if dns_id:
                    active_dns = dns_id
                continue

            last_state = load_last_state()
            if last_state:
                expected_ident = f"io.github.ios-debloat.profile.{last_state.get('target', 'all')}"
                if expected_ident == ident:
                    disabled_keys.update(str(k) for k in (last_state.get("disabled_restrictions") or []))
                    saved_dns = str(last_state.get("dns_id") or "")
                    if saved_dns and saved_dns != "dns:none":
                        active_dns = saved_dns

    return disabled_keys, active_dns
