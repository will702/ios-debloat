"""Scriptable CLI & TUI orchestration for ios-watchos-ipados-debloat."""
from __future__ import annotations

import argparse
import curses
import json
import sys
from pathlib import Path
from typing import Any, Optional

from ios_debloat import VERSION
from ios_debloat.audit import build_audit, build_status, format_audit, format_status
from ios_debloat.catalog import (
    BUILTIN_PRESETS,
    VALID_TARGETS,
    build_catalog,
    catalog_stats,
    export_blocklist,
    format_catalog_list,
    resolve_preset,
)
from ios_debloat.deliver import export_profile, reveal_for_airdrop, serve_profile_qr
from ios_debloat.device import (
    get_active_debloat_keys,
    install_profile,
    list_crash_reports,
    list_devices,
    list_installed_apps,
    list_profiles,
    list_running_processes,
    remove_profile,
    uninstall_stock_app,
)
from ios_debloat.models import DeviceInfo, Section
from ios_debloat.profile_builder import (
    apply_dns_selection,
    build_mobileconfig,
    export_ddm_declarations,
    profile_identifier,
    sign_profile,
    validate_profile,
)
from ios_debloat.state import (
    apply_saved_state,
    apply_watch_checklist,
    default_keybag_path,
    load_last_state,
    load_latest_snapshot,
    load_user_labels,
    load_watch_checklist,
    presets_dir,
    save_last_state,
    save_watch_checklist,
    write_snapshot,
)
from ios_debloat.supervision import create_supervision_keybag, supervision_guide_text
from ios_debloat.tui import (
    apply_locks,
    keep_locked_on,
    pending_changes,
    reopen_tty_stdin,
    run_tui,
    select_for_action,
)


def _select_device(
    devices: list[DeviceInfo],
    udid: Optional[str],
) -> Optional[DeviceInfo]:
    if not devices:
        return None
    if udid:
        for d in devices:
            if d.udid == udid:
                return d
        raise RuntimeError(f"Connected device with UDID {udid!r} not found")
    return devices[0]


def _load_device_context(
    target: str,
    *,
    udid: Optional[str] = None,
    wifi: bool = False,
    wifi_host: Optional[str] = None,
    force_supervised: bool = False,
) -> tuple[
    list[Section],
    Optional[DeviceInfo],
    Optional[dict[str, Any]],
    Optional[dict[str, Any]],
    bool,
]:
    user_labels = load_user_labels()
    sections = build_catalog(target=target, user_labels=user_labels)
    devices = list_devices(wifi=wifi, wifi_host=wifi_host)
    device = _select_device(devices, udid)

    profiles_resp: Optional[dict[str, Any]] = None
    installed_apps: Optional[dict[str, Any]] = None

    if device and device.pmd3_available:
        try:
            profiles_resp = list_profiles(udid=device.udid, wifi=wifi, wifi_host=wifi_host)
        except Exception:
            profiles_resp = None
        try:
            installed_apps = list_installed_apps(udid=device.udid, wifi=wifi, wifi_host=wifi_host)
        except Exception:
            installed_apps = None

    if profiles_resp is not None:
        disabled_keys, active_dns = get_active_debloat_keys(profiles_resp)
        for sec in sections:
            for it in sec.items:
                if it.kind == "restriction":
                    is_off = it.id in disabled_keys
                    it.disabled = is_off
                    it.selected = not is_off
                elif it.kind == "dns":
                    target_dns = active_dns or "dns:none"
                    is_cur = it.id == target_dns
                    it.active = is_cur
                    it.selected = is_cur
    else:
        apply_saved_state(sections, load_last_state())

    if installed_apps is not None:
        for sec in sections:
            for it in sec.items:
                if it.kind == "stock_app" and it.bundle_id:
                    is_installed = it.bundle_id in installed_apps
                    it.disabled = not is_installed
                    it.selected = is_installed

    watch_done = load_watch_checklist()
    apply_watch_checklist(sections, watch_done)

    supervised_mode = bool(force_supervised or (device and device.supervised))
    has_usb = bool(device and device.pmd3_available and device.connection in ("usb", "wifi"))
    apply_locks(sections, supervised_mode=supervised_mode, has_usb_pmd3=has_usb)
    return sections, device, profiles_resp, installed_apps, supervised_mode


def _build_parser() -> argparse.ArgumentParser:
    stats = catalog_stats()
    epilog = f"""\
Presets:
  telemetry   {stats.telemetry_preset} keys — analytics, crash reports, ads, Siri Suggestions, on-device dictation
  balanced    {stats.balanced_preset} keys — telemetry + Siri, Apple Intelligence, Continuity & Handoff
  custom      {presets_dir()}/NAME.txt

Catalog: {stats.restrictions_total} restrictions ({stats.restrictions_unsupervised} unsupervised, {stats.restrictions_supervised} supervised), {stats.dns_presets} encrypted DNS presets, {stats.stock_apps} removable stock Apple apps, {stats.watch_checklist} watchOS checklist items.
"""
    p = argparse.ArgumentParser(
        prog="debloat",
        description="Debloat iPhone, iPad, and Apple Watch from your terminal using Apple Configuration Profiles, DDM, Encrypted DNS, and optional USB/Wi-Fi audit.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-v", "--version", action="store_true", help="print version and exit")
    p.add_argument("--target", choices=VALID_TARGETS, default="all", help="filter catalog to ios, ipados, watchos, or all")
    p.add_argument("--preset", help="apply preset: telemetry, balanced, or custom file in ~/.ios-debloat/presets/")
    p.add_argument("--disable-all", action="store_true", help="disable all unlocked restrictions in current mode")
    p.add_argument("--enable-all", action="store_true", help="revert all restrictions & remove debloat profile")
    p.add_argument("--restore", action="store_true", help="restore state from the snapshot before your last apply")
    p.add_argument("--dns", help="Encrypted DNS: none, adguard, mullvad-base, mullvad-all, quad9, controld, nextdns:<id>, https://..., or DoT host")
    p.add_argument("--dns-apple-only", action="store_true", help="route only safe Apple telemetry/ad domains through the DNS profile (SupplementalMatchDomains)")
    p.add_argument("--silence-notifications", action="store_true", help="silence noisy built-in Apple apps via com.apple.notificationsettings (supervised only)")
    p.add_argument("--supervised", action="store_true", help="unlock supervised-only Apple Intelligence/media keys")
    p.add_argument("--keybag", type=Path, help="path to supervision PEM keybag for silent USB profile installs")
    p.add_argument("--deliver", choices=("auto", "usb", "qr", "export", "airdrop"), default="auto", help="delivery channel when applying (default: auto/export)")
    p.add_argument("--out", type=Path, help="output path for exported .mobileconfig file")
    p.add_argument("--export-ddm", type=Path, metavar="DIR", help="export Apple Declarative Device Management (DDM) JSON configs for OS 26.4/27+")
    p.add_argument("--export-blocklist", choices=("domains", "adguard", "hosts"), help="print safe Apple telemetry/ad DNS blocklist and exit")
    p.add_argument("--serve", nargs="?", const=8765, type=int, metavar="PORT", help="start LAN HTTP + terminal QR server for exported profile (default port 8765)")
    p.add_argument("--sign", nargs=2, metavar=("CERT", "KEY"), help="sign .mobileconfig with OpenSSL S/MIME cert and private key")
    p.add_argument("--status", action="store_true", help="show current device, profile, DNS, and watchOS checklist status")
    p.add_argument("--audit", action="store_true", help="run live (if USB+pymobiledevice3) or offline privacy & telemetry daemon audit")
    p.add_argument("--list", action="store_true", help="print catalog in preset file format")
    p.add_argument("--watch-checklist", action="store_true", help="show interactive/CLI watchOS companion checklist")
    p.add_argument("--check", metavar="ITEM_ID", help="with --watch-checklist: mark an item completed")
    p.add_argument("--uncheck", metavar="ITEM_ID", help="with --watch-checklist: mark an item incomplete")
    p.add_argument("--supervise-guide", action="store_true", help="show safe step-by-step device supervision guide")
    p.add_argument("--create-keybag", nargs="?", const="Self-Supervised", metavar="ORG", help="create local supervision PEM keybag (~/.ios-debloat/supervision/keybag.pem)")
    p.add_argument("--wifi", action="store_true", help="discover/connect to paired device over Wi-Fi (mobdev2)")
    p.add_argument("--wifi-host", help="connect directly over Wi-Fi to device IP/hostname (mobdev2-host)")
    p.add_argument("--udid", help="target a specific device UDID")
    p.add_argument("--dry-run", action="store_true", help="preview profile changes without writing files or touching device")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output for --status and --audit")
    return p


def _deliver_profile(
    sections: list[Section],
    *,
    target: str,
    supervised: bool,
    dns_apple_only: bool,
    silence_notifications: bool,
    dns_override: Optional[dict[str, Any]],
    deliver: str,
    out_path: Optional[Path],
    serve_port: Optional[int],
    sign_pair: Optional[tuple[Path, Path]],
    device: Optional[DeviceInfo],
    keybag: Optional[Path],
    wifi: bool,
    wifi_host: Optional[str],
    dry_run: bool,
    remove_when_empty: bool = False,
) -> tuple[int, str]:
    profile_bytes, summary = build_mobileconfig(
        sections,
        target=target,
        supervised=supervised,
        dns_apple_only=dns_apple_only,
        silence_stock_notifications=silence_notifications,
        dns_override=dns_override,
    )
    ok, errs = validate_profile(profile_bytes, expect_unsupervised=not supervised)
    if not ok:
        return 1, "Profile validation failed:\n  " + "\n  ".join(errs)

    if sign_pair is not None and not dry_run:
        cert_p, key_p = sign_pair
        profile_bytes = sign_profile(profile_bytes, cert_p, key_p)

    if dry_run:
        return 0, json.dumps(summary, indent=2)

    write_snapshot(
        sections,
        device_id=device.udid if device else "offline",
        supervised=supervised,
    )

    _, _, _, apps_to_uninstall = pending_changes(sections)

    if deliver == "usb":
        if not device or not device.pmd3_available:
            return 1, "USB delivery requires a connected device and `pymobiledevice3` installed."
        kb = keybag or (default_keybag_path() if supervised and default_keybag_path().is_file() else None)
        if remove_when_empty and summary["payload_count"] == 0:
            remove_profile(profile_identifier(target), udid=device.udid, wifi=wifi, wifi_host=wifi_host)
            msg = f"Removed profile {profile_identifier(target)} from {device.name}."
        else:
            dest = export_profile(profile_bytes, target=target, out_path=out_path)
            install_profile(dest, udid=device.udid, keybag=kb, wifi=wifi, wifi_host=wifi_host)
            msg = (
                f"Pushed {dest.name} to {device.name} "
                f"({'silent keybag' if kb else 'confirm Install prompt on device'}). "
                f"({summary['restriction_count']} restrictions, dns={summary['dns'] or 'none'})"
            )
        for app in apps_to_uninstall:
            if app.bundle_id:
                uninstall_stock_app(app.bundle_id, udid=device.udid, wifi=wifi, wifi_host=wifi_host)
                app.disabled = True
        save_last_state(sections, supervised=supervised, target=target, device_id=device.udid)
        return 0, msg

    dest = export_profile(profile_bytes, target=target, out_path=out_path)
    save_last_state(sections, supervised=supervised, target=target, device_id=device.udid if device else "offline")

    if deliver == "qr" or serve_port is not None:
        port = serve_port if serve_port is not None else 8765
        serve_profile_qr(profile_bytes, port=port)
        return 0, f"Exported {dest} and stopped QR server."

    if deliver == "airdrop":
        revealed = reveal_for_airdrop(dest)
        note = "Opened Finder — right-click -> Share -> AirDrop to your iPhone/iPad." if revealed else f"Saved {dest}"
        return 0, note

    note = (
        f"Exported {dest}\n"
        f"Summary : {summary['restriction_count']} restrictions | DNS: {summary['dns'] or 'none'}"
        + (" (Apple-only split)" if summary["dns_apple_only"] else "")
        + f" | mode: {'supervised' if supervised else 'unsupervised'}"
    )
    if remove_when_empty and summary["payload_count"] == 0:
        note += "\nRevert  : remove the existing profile in iPhone/iPad Settings -> General -> VPN & Device Management (or pass `--enable-all --deliver usb`)."
    if summary["skipped_supervised"]:
        note += f"\nSkipped : {len(summary['skipped_supervised'])} supervised-only keys (pass --supervised to include)"
    note += "\nNext    : run with `--deliver qr` to scan wirelessly, or `--deliver airdrop` on Mac."
    if device and device.pmd3_available:
        note += f"\nUSB     : {device.name} detected — pass `--deliver usb` to push over USB."
    return 0, note


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"ios-watchos-ipados-debloat {VERSION}")
        return 0

    if args.export_blocklist:
        print(export_blocklist(args.export_blocklist), end="")
        return 0

    if args.create_keybag is not None:
        kb = create_supervision_keybag(organization=args.create_keybag)
        print(f"Created supervision keybag: {kb} (mode 0600)")
        return 0

    if args.supervise_guide:
        all_secs = build_catalog("all")
        sup_count = sum(1 for sec in all_secs for it in sec.items if it.kind == "restriction" and it.supervised)
        print(supervision_guide_text(supervised_count=sup_count, currently_supervised=args.supervised))
        return 0

    try:
        sections, device, profiles_resp, installed_apps, supervised_mode = _load_device_context(
            args.target,
            udid=args.udid,
            wifi=args.wifi,
            wifi_host=args.wifi_host,
            force_supervised=args.supervised,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.watch_checklist:
        done = load_watch_checklist()
        changed = False
        valid_watch_ids = {it.id for sec in sections for it in sec.items if it.kind == "watch_check"}
        if args.check:
            if args.check not in valid_watch_ids:
                print(f"unknown watch checklist item {args.check!r}", file=sys.stderr)
                return 1
            done.add(args.check)
            changed = True
        if args.uncheck:
            if args.uncheck not in valid_watch_ids:
                print(f"unknown watch checklist item {args.uncheck!r}", file=sys.stderr)
                return 1
            done.discard(args.uncheck)
            changed = True
        if changed:
            save_watch_checklist(done)
        apply_watch_checklist(sections, done)
        print(f"watchOS Companion Checklist ({len(done)}/{len(valid_watch_ids)} completed):")
        for sec in sections:
            for it in sec.items:
                if it.kind == "watch_check":
                    mark = "[x]" if it.selected else "[ ]"
                    print(f"  {mark} {it.id:<22} {it.comment}")
        return 0

    if args.list:
        listed = sections
        if args.preset:
            wanted = resolve_preset(sections, args.preset, presets_dir=presets_dir())
            if wanted is None:
                print(f"unknown preset {args.preset!r}", file=sys.stderr)
                return 1
            listed = [
                Section(title=sec.title, kind=sec.kind, items=[it for it in sec.items if it.id in wanted])
                for sec in sections
            ]
            listed = [sec for sec in listed if sec.items]
        print(format_catalog_list(listed), end="")
        return 0

    if args.status:
        watch_done = load_watch_checklist()
        st = build_status(
            sections,
            device=device,
            profiles_response=profiles_resp,
            installed_apps=installed_apps,
            watch_done=watch_done,
            supervised_mode=supervised_mode,
        )
        print(json.dumps(st, indent=2) if args.json else format_status(st))
        return 0

    if args.audit:
        processes = None
        crashes = None
        if device and device.pmd3_available:
            try:
                processes = list_running_processes(udid=device.udid, wifi=args.wifi, wifi_host=args.wifi_host)
            except Exception:
                processes = None
            try:
                crashes = list_crash_reports(udid=device.udid, wifi=args.wifi, wifi_host=args.wifi_host)
            except Exception:
                crashes = None
        rep = build_audit(
            sections,
            device=device,
            profiles_response=profiles_resp,
            installed_apps=installed_apps,
            processes=processes,
            crash_reports=crashes,
        )
        print(json.dumps(rep, indent=2) if args.json else format_audit(rep))
        return 0

    # Non-interactive mutating / export actions
    dns_override = None
    if args.dns:
        try:
            dns_override = apply_dns_selection(sections, args.dns)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    action_requested = any(
        (args.preset, args.disable_all, args.enable_all, args.restore, args.dns, args.export_ddm, args.serve is not None)
    )
    if action_requested:
        remove_when_empty = False
        if args.restore:
            snap = load_latest_snapshot()
            if not snap:
                print("no snapshot found to restore (~/.ios-debloat/snapshots/latest.json)", file=sys.stderr)
                return 1
            apply_saved_state(sections, snap)
            supervised_mode = bool(args.supervised or snap.get("supervised"))
            apply_locks(sections, supervised_mode=supervised_mode, has_usb_pmd3=bool(device and device.pmd3_available))
            remove_when_empty = True
        elif args.enable_all:
            select_for_action(sections, "enable-all")
            remove_when_empty = True
        elif args.disable_all:
            select_for_action(sections, "disable-all")
        elif args.preset:
            res = select_for_action(sections, f"preset:{args.preset}", user_presets_dir=presets_dir())
            if res.startswith("unknown preset"):
                print(res, file=sys.stderr)
                return 1

        if args.export_ddm:
            paths = export_ddm_declarations(sections, args.export_ddm, supervised=True if args.supervised else supervised_mode)
            if args.json:
                print(json.dumps([str(p) for p in paths], indent=2))
            else:
                print(f"Exported {len(paths)} DDM declaration(s) to {args.export_ddm}:")
                for p in paths:
                    print(f"  - {p.name}")
            if not any((args.out, args.deliver != "auto", args.serve is not None)):
                return 0

        sign_pair = (Path(args.sign[0]), Path(args.sign[1])) if args.sign else None
        code, msg = _deliver_profile(
            sections,
            target=args.target,
            supervised=supervised_mode,
            dns_apple_only=args.dns_apple_only,
            silence_notifications=args.silence_notifications,
            dns_override=dns_override,
            deliver=args.deliver,
            out_path=args.out,
            serve_port=args.serve,
            sign_pair=sign_pair,
            device=device,
            keybag=args.keybag,
            wifi=args.wifi,
            wifi_host=args.wifi_host,
            dry_run=args.dry_run,
            remove_when_empty=remove_when_empty,
        )
        stream = sys.stdout if code == 0 else sys.stderr
        print(msg, file=stream)
        return code

    # Interactive TUI (default)
    if not reopen_tty_stdin():
        print(
            "the interactive TUI needs a terminal on stdin, or pass flags like --preset, --status, --audit.",
            file=sys.stderr,
        )
        return 1

    def _reload(cur_sup: bool) -> tuple[list[Section], Optional[DeviceInfo]]:
        secs, dev, _, _, det_sup = _load_device_context(
            args.target,
            udid=args.udid,
            wifi=args.wifi,
            wifi_host=args.wifi_host,
            force_supervised=cur_sup or args.supervised,
        )
        del det_sup
        return secs, dev

    def _apply_from_tui(
        cur_secs: list[Section],
        cur_dev: Optional[DeviceInfo],
        cur_sup: bool,
        deliver_mode: str,
    ) -> str:
        code, msg = _deliver_profile(
            cur_secs,
            target=args.target,
            supervised=cur_sup,
            dns_apple_only=args.dns_apple_only,
            silence_notifications=args.silence_notifications,
            dns_override=None,
            deliver=deliver_mode,
            out_path=args.out,
            serve_port=None,
            sign_pair=(Path(args.sign[0]), Path(args.sign[1])) if args.sign else None,
            device=cur_dev,
            keybag=args.keybag,
            wifi=args.wifi,
            wifi_host=args.wifi_host,
            dry_run=False,
            remove_when_empty=False,
        )
        return msg.splitlines()[0] if msg else ("done" if code == 0 else "error")

    def _audit_from_tui(cur_secs: list[Section], cur_dev: Optional[DeviceInfo]) -> str:
        procs = None
        crashes = None
        if cur_dev and cur_dev.pmd3_available:
            try:
                procs = list_running_processes(udid=cur_dev.udid, wifi=args.wifi, wifi_host=args.wifi_host)
            except Exception:
                procs = None
            try:
                crashes = list_crash_reports(udid=cur_dev.udid, wifi=args.wifi, wifi_host=args.wifi_host)
            except Exception:
                crashes = None
        rep = build_audit(
            cur_secs,
            device=cur_dev,
            profiles_response=profiles_resp,
            installed_apps=installed_apps,
            processes=procs,
            crash_reports=crashes,
        )
        return "\n" + format_audit(rep)

    def _guide_from_tui(cur_secs: list[Section], cur_dev: Optional[DeviceInfo]) -> str:
        sup_cnt = sum(1 for s in cur_secs for it in s.items if it.kind == "restriction" and it.supervised)
        return "\n" + supervision_guide_text(
            supervised_count=sup_cnt,
            currently_supervised=bool(cur_dev and cur_dev.supervised),
        )

    out_msg = curses.wrapper(
        run_tui,
        sections,
        device=device,
        supervised_mode=supervised_mode,
        reload_fn=_reload,
        apply_fn=_apply_from_tui,
        audit_fn=_audit_from_tui,
        supervise_guide_fn=_guide_from_tui,
    )
    if out_msg:
        print(out_msg)
    return 0
