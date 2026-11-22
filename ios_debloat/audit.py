"""Status & telemetry/daemon audit reporting (`--status`, `--audit`)."""
from __future__ import annotations

from typing import Any, Optional

from ios_debloat.catalog import TELEMETRY_DAEMONS, catalog_stats
from ios_debloat.device import get_active_debloat_keys
from ios_debloat.models import DeviceInfo, Section


def build_status(
    sections: list[Section],
    *,
    device: Optional[DeviceInfo],
    profiles_response: Optional[dict[str, Any]] = None,
    installed_apps: Optional[dict[str, Any]] = None,
    watch_done: Optional[set[str]] = None,
    supervised_mode: bool = False,
) -> dict[str, Any]:
    """Assemble structured status data for `--status` and `--status --json`."""
    stats = catalog_stats(sections)
    restrictions = [it for sec in sections for it in sec.items if it.kind == "restriction"]
    disabled_restrictions = [it.id for it in restrictions if it.disabled]

    active_dns = "dns:none"
    for sec in sections:
        for it in sec.items:
            if it.kind == "dns" and it.active:
                active_dns = it.id
                break

    watch_items = [it for sec in sections for it in sec.items if it.kind == "watch_check"]
    watch_completed = len(watch_done or set())

    stock_items = [it for sec in sections for it in sec.items if it.kind == "stock_app"]
    installed_removable: list[str] = []
    if installed_apps is not None:
        for it in stock_items:
            if it.bundle_id and it.bundle_id in installed_apps:
                installed_removable.append(it.bundle_id)

    profile_ids: list[str] = []
    if profiles_response and isinstance(profiles_response.get("ProfileMetadata"), dict):
        profile_ids = sorted(profiles_response["ProfileMetadata"].keys())
    ours_installed = [pid for pid in profile_ids if pid.startswith("io.github.ios-debloat.")]

    return {
        "device": {
            "name": device.name if device else "Offline",
            "udid": device.udid if device else "",
            "product_type": device.product_type if device else "",
            "os_version": device.os_version if device else "",
            "platform": device.platform if device else "all",
            "connection": device.connection if device else "offline",
            "supervised": device.supervised if device else supervised_mode,
            "pmd3_available": device.pmd3_available if device else False,
        },
        "mode": "supervised" if (device.supervised if device else supervised_mode) else "unsupervised",
        "catalog": {
            "restrictions_total": stats.restrictions_total,
            "restrictions_unsupervised": stats.restrictions_unsupervised,
            "restrictions_supervised": stats.restrictions_supervised,
            "watch_profile_keys": stats.watch_profile_keys,
            "stock_apps": stats.stock_apps,
            "watch_checklist": stats.watch_checklist,
        },
        "state": {
            "disabled_restrictions": disabled_restrictions,
            "disabled_count": len(disabled_restrictions),
            "active_dns": active_dns,
            "debloat_profiles_installed": ours_installed,
            "all_profiles_count": len(profile_ids),
            "removable_stock_apps_installed": installed_removable,
            "watch_checklist_done": watch_completed,
            "watch_checklist_total": len(watch_items),
        },
    }


def format_status(status: dict[str, Any]) -> str:
    """Format `--status` dictionary for human reading."""
    dev = status["device"]
    st = status["state"]
    cat = status["catalog"]
    lines = [
        f"Device         : {dev['name']} ({dev['product_type'] or 'no hardware attached'})",
        f"OS / Connection: {dev['os_version'] or 'n/a'} · {dev['connection']} · mode: {status['mode']}",
        f"pymobiledevice3: {'installed' if dev['pmd3_available'] else 'not installed (wireless QR/AirDrop ready)'}",
        f"Catalog        : {cat['restrictions_total']} restrictions "
        f"({cat['restrictions_unsupervised']} unsupervised, {cat['restrictions_supervised']} supervised) · "
        f"{cat['watch_profile_keys']} watchOS profile keys",
        f"Disabled keys  : {st['disabled_count']} / {cat['restrictions_total']}",
        f"Encrypted DNS  : {st['active_dns']}",
        f"watchOS checks : {st['watch_checklist_done']} / {st['watch_checklist_total']} done",
    ]
    if st["debloat_profiles_installed"]:
        lines.append(f"Installed prof : {', '.join(st['debloat_profiles_installed'])}")
    if st["removable_stock_apps_installed"]:
        lines.append(
            f"Stock bloat    : {len(st['removable_stock_apps_installed'])} removable Apple apps installed"
        )
    return "\n".join(lines)


def build_audit(
    sections: list[Section],
    *,
    device: Optional[DeviceInfo],
    profiles_response: Optional[dict[str, Any]] = None,
    installed_apps: Optional[dict[str, Any]] = None,
    processes: Optional[list[dict[str, Any]]] = None,
    crash_reports: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Run privacy, telemetry daemon, profile, and bloat audit (`--audit`)."""
    stats = catalog_stats(sections)
    active_keys, active_dns = get_active_debloat_keys(profiles_response or {})

    running_telemetry: list[dict[str, str]] = []
    if processes is not None:
        seen: set[str] = set()
        for proc in processes:
            pname = str(proc.get("name") or "")
            if pname in TELEMETRY_DAEMONS and pname not in seen:
                seen.add(pname)
                category, desc = TELEMETRY_DAEMONS[pname]
                running_telemetry.append(
                    {
                        "process": pname,
                        "pid": str(proc.get("pid") or ""),
                        "category": category,
                        "description": desc,
                    }
                )
        running_telemetry.sort(key=lambda r: (r["category"], r["process"]))

    removable_installed: list[str] = []
    if installed_apps is not None:
        for sec in sections:
            for it in sec.items:
                if it.kind == "stock_app" and it.bundle_id and it.bundle_id in installed_apps:
                    removable_installed.append(it.bundle_id)

    findings: list[str] = []
    if "allowDiagnosticSubmission" not in active_keys:
        findings.append("Diagnostic & crash submission to Apple is not restricted by profile (`allowDiagnosticSubmission`).")
    if "allowApplePersonalizedAdvertising" not in active_keys:
        findings.append("Apple Personalized Advertising is not restricted (`allowApplePersonalizedAdvertising`).")
    if not active_dns or active_dns == "dns:none":
        findings.append("No Encrypted DNS telemetry/ad blocker profile detected (`com.apple.dnsSettings.managed`).")
    if removable_installed:
        findings.append(f"{len(removable_installed)} removable stock Apple bloat apps are still installed.")
    if crash_reports:
        findings.append(f"{len(crash_reports)} crash/diagnostic files stored on device.")

    return {
        "mode": "live" if (device and device.pmd3_available and processes is not None) else "offline",
        "device": {
            "name": device.name if device else "Offline",
            "udid": device.udid if device else "",
            "os_version": device.os_version if device else "",
            "supervised": device.supervised if device else False,
            "connection": device.connection if device else "offline",
        },
        "privacy_checks": {
            "diagnostic_submission_blocked": "allowDiagnosticSubmission" in active_keys,
            "personalized_ads_blocked": "allowApplePersonalizedAdvertising" in active_keys,
            "active_dns_blocker": active_dns or "none",
            "restricted_keys_count": len(active_keys),
        },
        "running_telemetry_daemons": running_telemetry,
        "removable_stock_apps_installed": sorted(removable_installed),
        "crash_reports_count": len(crash_reports) if crash_reports is not None else None,
        "catalog_summary": {
            "restrictions_total": stats.restrictions_total,
            "restrictions_unsupervised": stats.restrictions_unsupervised,
            "restrictions_supervised": stats.restrictions_supervised,
            "telemetry_daemons_watched": stats.telemetry_daemons,
        },
        "findings": findings,
    }


def format_audit(audit: dict[str, Any]) -> str:
    """Format `--audit` report for terminal output."""
    dev = audit["device"]
    checks = audit["privacy_checks"]
    lines = [
        f"Audit Mode     : {audit['mode']} ({dev['name']} {dev['os_version'] or ''})".rstrip(),
        f"Supervision    : {'supervised' if dev['supervised'] else 'unsupervised'}",
        f"Diag Blocked   : {'yes' if checks['diagnostic_submission_blocked'] else 'no'}",
        f"Ads Blocked    : {'yes' if checks['personalized_ads_blocked'] else 'no'}",
        f"DNS Blocker    : {checks['active_dns_blocker']}",
    ]

    daemons = audit["running_telemetry_daemons"]
    if audit["mode"] == "live":
        lines.append(f"Live Daemons   : {len(daemons)} / {audit['catalog_summary']['telemetry_daemons_watched']} watched telemetry/AI daemons running")
        for d in daemons:
            lines.append(f"  - {d['process']:<24} [{d['category']}] (pid {d['pid']}) {d['description']}")
    else:
        lines.append(
            f"Live Daemons   : skipped ({'install pymobiledevice3 for live `processes ps` audit' if dev['connection'] != 'offline' else 'no USB/Wi-Fi device attached'})"
        )

    apps = audit["removable_stock_apps_installed"]
    if apps:
        lines.append(f"Stock Apps ({len(apps)}): {', '.join(apps)}")

    if audit["crash_reports_count"] is not None:
        lines.append(f"Crash Logs     : {audit['crash_reports_count']} files")

    findings = audit["findings"]
    if findings:
        lines.append("Findings:")
        for f in findings:
            lines.append(f"  * {f}")
    else:
        lines.append("Findings: All core telemetry & DNS checks are active.")
    return "\n".join(lines)
