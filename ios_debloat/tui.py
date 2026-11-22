"""Interactive curses TUI modeled directly on OleksandrKrupko/mac-os-debloat."""
from __future__ import annotations

import curses
import os
import sys
import textwrap
from pathlib import Path
from typing import Callable, Optional

from ios_debloat.catalog import MENU_SECTION, resolve_preset
from ios_debloat.models import DeviceInfo, Item, Section
from ios_debloat.state import load_watch_checklist, presets_dir, save_watch_checklist

LABEL_WIDTH = 44
COMMENT_COL = len("  [✓]  ") + LABEL_WIDTH + 2


def apply_locks(
    sections: list[Section],
    *,
    supervised_mode: bool,
    has_usb_pmd3: bool,
) -> int:
    """Update `.locked` and `.lock_reason` on items based on supervision & USB availability."""
    locked = 0
    for sec in sections:
        for it in sec.items:
            if it.kind == "restriction":
                if it.supervised and not supervised_mode:
                    it.locked = True
                    it.lock_reason = "needs supervision"
                    locked += 1
                else:
                    it.locked = False
                    it.lock_reason = ""
            elif it.kind == "stock_app":
                if not has_usb_pmd3:
                    it.locked = True
                    it.lock_reason = "needs USB + pymobiledevice3"
                    locked += 1
                else:
                    it.locked = False
                    it.lock_reason = ""
            else:
                it.locked = False
                it.lock_reason = ""
    return locked


def keep_locked_on(sections: list[Section]) -> int:
    """Ensure locked items cannot be staged for change; keep their current state."""
    kept = 0
    for sec in sections:
        for it in sec.items:
            if it.locked and it.kind in ("restriction", "stock_app"):
                desired_default = not it.disabled
                if it.selected != desired_default:
                    it.selected = desired_default
                    kept += 1
    return kept


def pending_changes(
    sections: list[Section],
) -> tuple[list[Item], list[Item], Optional[Item], list[Item]]:
    """Return `(to_disable_restrictions, to_enable_restrictions, changed_dns_item, apps_to_uninstall)`."""
    to_disable: list[Item] = []
    to_enable: list[Item] = []
    changed_dns: Optional[Item] = None
    uninstall_apps: list[Item] = []

    for sec in sections:
        for it in sec.items:
            if it.kind == "restriction" and not it.locked:
                if not it.selected and not it.disabled:
                    to_disable.append(it)
                elif it.selected and it.disabled:
                    to_enable.append(it)
            elif it.kind == "dns":
                if it.selected and not it.active:
                    changed_dns = it
            elif it.kind == "stock_app" and not it.locked:
                if not it.selected and not it.disabled:
                    uninstall_apps.append(it)
    return to_disable, to_enable, changed_dns, uninstall_apps


def pending_count(sections: list[Section]) -> int:
    """Total number of staged pending changes."""
    dis, en, dns, apps = pending_changes(sections)
    return len(dis) + len(en) + (1 if dns else 0) + len(apps)


def flat_index(sections: list[Section]) -> list[Item]:
    """Return flattened list of selectable items across sections."""
    return [it for sec in sections for it in sec.items]


def menu_section(
    sections: list[Section],
    *,
    device: Optional[DeviceInfo],
    supervised_mode: bool,
) -> Section:
    """Build top action menu rows matching mac-os-debloat's ergonomics."""
    tel_count = sum(1 for sec in sections for it in sec.items if it.kind == "restriction" and "telemetry" in it.presets)
    bal_count = sum(1 for sec in sections for it in sec.items if it.kind == "restriction" and "balanced" in it.presets)
    res_total = sum(1 for sec in sections for it in sec.items if it.kind == "restriction")
    sup_locked = sum(1 for sec in sections for it in sec.items if it.kind == "restriction" and it.locked)

    items = [
        Item(
            id="action:telemetry",
            kind="action",
            label="telemetry",
            section=MENU_SECTION,
            action="preset:telemetry",
            comment=f"disable {tel_count} telemetry, diagnostic, ad & on-device dictation keys (safe daily preset)",
        ),
        Item(
            id="action:balanced",
            kind="action",
            label="balanced",
            section=MENU_SECTION,
            action="preset:balanced",
            comment=f"disable {bal_count} keys — telemetry + Siri, Apple Intelligence, Continuity & Handoff",
        ),
        Item(
            id="action:disable-all",
            kind="action",
            label="disable all",
            section=MENU_SECTION,
            action="disable-all",
            comment=f"disable all {res_total} unlocked keys — includes iCloud sync, Safari & Messages warnings",
        ),
        Item(
            id="action:enable-all",
            kind="action",
            label="enable all",
            section=MENU_SECTION,
            action="enable-all",
            comment="turn all restrictions back ON & clear DNS profile — the reversible panic button",
        ),
    ]

    if device and device.connection != "offline" and not device.supervised:
        items.append(
            Item(
                id="action:supervise",
                kind="action",
                label="supervise device",
                section=MENU_SECTION,
                action="supervise-guide",
                comment=f"unlock {sup_locked} supervised-only AI/media keys — opens step-by-step Supervision Guide",
            )
        )
    else:
        next_state = "OFF (unsupervised)" if supervised_mode else "ON (supervised preview)"
        items.append(
            Item(
                id="action:toggle-supervised",
                kind="action",
                label="toggle supervised",
                section=MENU_SECTION,
                action="toggle-supervised",
                comment=f"switch mode to {next_state} ({sup_locked} keys locked when unsupervised)",
            )
        )

    items.extend(
        [
            Item(
                id="action:serve-qr",
                kind="action",
                label="serve QR / export",
                section=MENU_SECTION,
                action="serve-qr",
                comment="build .mobileconfig from current checkboxes and launch local LAN QR server",
            ),
            Item(
                id="action:audit",
                kind="action",
                label="audit",
                section=MENU_SECTION,
                action="audit",
                comment="run live (if USB connected) or offline telemetry, DNS & stock bloat audit report",
            ),
        ]
    )
    return Section(title=MENU_SECTION, kind="action", items=items)


def select_for_action(
    sections: list[Section],
    action: str,
    *,
    user_presets_dir: Optional[Path] = None,
) -> str:
    """Apply a menu preset/action onto section checkboxes while respecting locks."""
    if action in ("disable-all", "enable-all"):
        want_on = action == "enable-all"
        for sec in sections:
            for it in sec.items:
                if it.kind == "restriction":
                    it.selected = want_on
                elif it.kind == "dns" and want_on:
                    it.selected = it.id == "dns:none"
        kept = keep_locked_on(sections)
        label = action.replace("-", " ")
        return label + (f" ({kept} locked, skipped)" if kept else "")

    if action.startswith("preset:"):
        name = action.split(":", 1)[1]
        pdir = user_presets_dir if user_presets_dir is not None else presets_dir()
        wanted = resolve_preset(sections, name, presets_dir=pdir)
        if wanted is None:
            return f"unknown preset {name}"
        for sec in sections:
            for it in sec.items:
                if it.kind == "restriction":
                    # Presets disable their own labels and leave already-disabled ones off.
                    it.selected = (it.id not in wanted) and (not it.disabled)
        kept = keep_locked_on(sections)
        return f"preset {name}" + (f" ({kept} need supervision, skipped)" if kept else "")

    return action


def jump_section(sections: list[Section], flat: list[Item], cursor: int, direction: int) -> int:
    """Move cursor to first item of next or previous section."""
    del flat
    starts: list[int] = []
    idx = 0
    for sec in sections:
        if sec.items:
            starts.append(idx)
            idx += len(sec.items)
    if not starts:
        return cursor
    if direction > 0:
        for s in starts:
            if s > cursor:
                return s
        return starts[-1]
    prev = starts[0]
    for s in starts:
        if s >= cursor:
            return prev
        prev = s
    return starts[-1]


def build_display_rows(sections: list[Section]) -> tuple[list[tuple[str, object]], dict[int, int]]:
    """Build flattened display rows for curses rendering."""
    rows: list[tuple[str, object]] = []
    item_to_row: dict[int, int] = {}
    item_idx = 0
    for sec in sections:
        rows.append(("section", sec.title))
        for it in sec.items:
            item_to_row[item_idx] = len(rows)
            rows.append(("item", it))
            item_idx += 1
        rows.append(("blank", None))
    return rows, item_to_row


def reopen_tty_stdin() -> bool:
    """Attach stdin to /dev/tty if invoked over a pipe (`curl ... | python3`)."""
    if sys.stdin.isatty():
        return True
    try:
        tty = open("/dev/tty", "r+", encoding="utf-8")
        os.dup2(tty.fileno(), 0)
        sys.stdin = tty
        return True
    except OSError:
        return False


def _format_item_head(it: Item) -> tuple[str, str]:
    if it.kind == "action":
        return f"   ▸   {it.label:<{LABEL_WIDTH}}  ", it.comment
    if it.kind == "dns":
        mark = "(•)" if it.selected else "( )"
        changed = " *" if (it.selected and not it.active) else "  "
        return f"{changed}{mark}  {it.label:<{LABEL_WIDTH}}  ", it.comment
    if it.kind == "watch_check":
        mark = "[x]" if it.selected else "[ ]"
        return f"  {mark}  {it.label:<{LABEL_WIDTH}}  ", it.comment

    mark = "[✓]" if it.selected else "[ ]"
    changed = " *" if it.selected == it.disabled else "  "
    prefix = f"{it.lock_reason} · " if it.locked and it.lock_reason else ""
    return f"{changed}{mark}  {it.label:<{LABEL_WIDTH}}  ", prefix + it.comment


def draw(
    stdscr: "curses._CursesWindow",
    sections: list[Section],
    cursor: int,
    status: str,
    scroll: list[int],
    *,
    device: Optional[DeviceInfo],
    supervised_mode: bool,
) -> None:
    """Render the full interactive terminal screen."""
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    if h < 10 or w < 40:
        stdscr.addnstr(0, 0, "Terminal too small — resize to at least 40x10", max(1, w - 1))
        stdscr.refresh()
        return

    title = (
        "ios-watchos-ipados-debloat   ↑↓ move   space toggle   [ ] section   "
        "enter apply   s supervised   r reload   q quit"
    )
    stdscr.addnstr(0, 0, title[: w - 1], w - 1, curses.A_BOLD)

    diff = pending_count(sections)
    dev_label = f"{device.name} ({device.os_version or device.connection})" if device and device.connection != "offline" else "offline"
    mode_label = "supervised" if supervised_mode else "unsupervised"
    sub = f"[✓] on   [ ] off   * pending   changes: {diff}   {dev_label} · {mode_label}"
    stdscr.addnstr(1, 0, sub[: w - 1], w - 1, curses.A_DIM)

    flat = flat_index(sections)
    current = flat[cursor]

    extra = ""
    if current.locked and current.lock_reason:
        extra = f"[{current.lock_reason}] "
    if current.platforms == ("ios", "ipados", "watchos"):
        extra += "[iOS+iPadOS+watchOS] "
    elif "watchos" in current.platforms and current.kind == "watch_check":
        extra += "[watchOS checklist] "

    explanation = textwrap.wrap(
        f"{current.label}: {extra}{current.comment}",
        max(20, w - 1),
        break_on_hyphens=False,
    )[: max(2, h // 4)]

    room = max(20, w - 1 - COMMENT_COL)
    lines: list[tuple[str, str, Optional[Item]]] = []
    first_line: dict[int, int] = {}

    for kind, payload in build_display_rows(sections)[0]:
        if kind != "item":
            lines.append((kind, str(payload or ""), None))
            continue
        it = payload  # type: ignore[assignment]
        head, comment = _format_item_head(it)
        chunks = textwrap.wrap(comment, room, break_on_hyphens=False) or [""]
        first_line[id(it)] = len(lines)
        lines.append(("item", head + chunks[0], it))
        lines.extend(("item", " " * COMMENT_COL + chunk, it) for chunk in chunks[1:])

    content_top = 3
    content_bottom = h - 2 - len(explanation)
    visible_h = max(1, content_bottom - content_top)

    top = first_line.get(id(current), 0)
    bottom = top + sum(1 for _, _, it in lines if it is current) - 1
    so = scroll[0]
    if top < so:
        so = top
    elif bottom >= so + visible_h:
        so = min(top, bottom - visible_h + 1)
    so = max(0, min(so, max(0, len(lines) - visible_h)))
    scroll[0] = so

    for screen_row, i in enumerate(range(so, min(so + visible_h, len(lines)))):
        kind, text, it = lines[i]
        y = content_top + screen_row
        if kind == "section":
            line = f"── {text} ".ljust(w - 1, "─")[: w - 1]
            stdscr.addnstr(y, 0, line, w - 1, curses.A_DIM)
        elif kind == "item":
            attr = (
                curses.A_REVERSE
                if it is current
                else (curses.A_DIM if (it and it.locked) else curses.A_NORMAL)
            )
            stdscr.addnstr(y, 0, text[: w - 1], w - 1, attr)

    if so > 0:
        try:
            stdscr.addnstr(content_top, max(0, w - 2), "↑", 1, curses.A_DIM)
        except curses.error:
            pass
    if so + visible_h < len(lines):
        try:
            stdscr.addnstr(content_bottom - 1, max(0, w - 2), "↓", 1, curses.A_DIM)
        except curses.error:
            pass

    try:
        for n, line in enumerate(explanation):
            stdscr.addnstr(content_bottom + n, 0, line, w - 1, curses.A_DIM)
        if status:
            stdscr.addnstr(h - 1, 0, status[: w - 1], w - 1, curses.A_BOLD)
    except curses.error:
        pass
    stdscr.refresh()


def _prompt_bar(stdscr: "curses._CursesWindow", text: str) -> int:
    h, w = stdscr.getmaxyx()
    stdscr.move(h - 1, 0)
    stdscr.clrtoeol()
    stdscr.addnstr(h - 1, 0, text[: w - 1], w - 1, curses.A_REVERSE)
    stdscr.refresh()
    stdscr.timeout(-1)
    return stdscr.getch()


def run_tui(
    stdscr: "curses._CursesWindow",
    sections: list[Section],
    *,
    device: Optional[DeviceInfo],
    supervised_mode: bool,
    reload_fn: Callable[[bool], tuple[list[Section], Optional[DeviceInfo]]],
    apply_fn: Callable[[list[Section], Optional[DeviceInfo], bool, str], str],
    audit_fn: Callable[[list[Section], Optional[DeviceInfo]], str],
    supervise_guide_fn: Callable[[list[Section], Optional[DeviceInfo]], str],
) -> Optional[str]:
    """Run the blocking curses TUI event loop."""
    curses.curs_set(0)
    cursor = 0
    status = ""
    scroll = [0]
    sup_mode = supervised_mode
    cur_device = device
    watch_done = load_watch_checklist()

    while True:
        has_usb = bool(cur_device and cur_device.pmd3_available and cur_device.connection in ("usb", "wifi"))
        apply_locks(sections, supervised_mode=sup_mode, has_usb_pmd3=has_usb)
        view = [menu_section(sections, device=cur_device, supervised_mode=sup_mode), *sections]
        flat = flat_index(view)
        cursor = max(0, min(cursor, len(flat) - 1))
        stdscr.timeout(-1)
        draw(stdscr, view, cursor, status, scroll, device=cur_device, supervised_mode=sup_mode)
        c = stdscr.getch()
        status = ""

        if c in (ord("q"), 27):
            return None
        if c in (curses.KEY_DOWN, ord("j")):
            cursor = min(cursor + 1, len(flat) - 1)
        elif c in (curses.KEY_UP, ord("k")):
            cursor = max(cursor - 1, 0)
        elif c == curses.KEY_NPAGE:
            cursor = min(cursor + 10, len(flat) - 1)
        elif c == curses.KEY_PPAGE:
            cursor = max(cursor - 10, 0)
        elif c == ord("]"):
            cursor = jump_section(view, flat, cursor, direction=1)
        elif c == ord("["):
            cursor = jump_section(view, flat, cursor, direction=-1)
        elif c == ord("s"):
            if cur_device and cur_device.connection != "offline" and not cur_device.supervised:
                status = "connected device is unsupervised — press enter on 'supervise device' for guide"
            else:
                sup_mode = not sup_mode
                apply_locks(sections, supervised_mode=sup_mode, has_usb_pmd3=has_usb)
                keep_locked_on(sections)
                status = f"mode: {'supervised' if sup_mode else 'unsupervised'}"
        elif c == ord("r"):
            sections, cur_device = reload_fn(sup_mode)
            if cur_device and cur_device.connection != "offline":
                sup_mode = cur_device.supervised
            watch_done = load_watch_checklist()
            status = "state reloaded"
        elif c == ord(" "):
            row = flat[cursor]
            if row.kind == "action":
                status = "press enter on a menu action to run it"
            elif row.locked:
                status = f"{row.label} ({row.lock_reason})"
            elif row.kind == "dns":
                for sec in sections:
                    for it in sec.items:
                        if it.kind == "dns":
                            it.selected = it is row
                status = f"selected DNS: {row.label}"
            elif row.kind == "watch_check":
                row.selected = not row.selected
                row.active = row.selected
                if row.selected:
                    watch_done.add(row.id)
                else:
                    watch_done.discard(row.id)
                save_watch_checklist(watch_done)
                status = f"watchOS checklist saved ({len(watch_done)} done)"
            else:
                row.selected = not row.selected
        elif c in (curses.KEY_ENTER, 10, 13):
            row = flat[cursor]
            action = row.action
            if action == "toggle-supervised":
                sup_mode = not sup_mode
                apply_locks(sections, supervised_mode=sup_mode, has_usb_pmd3=has_usb)
                keep_locked_on(sections)
                status = f"mode: {'supervised' if sup_mode else 'unsupervised'}"
                continue
            if action == "supervise-guide":
                curses.endwin()
                print(supervise_guide_fn(sections, cur_device))
                input("\nPress enter to return to TUI...")
                stdscr.refresh()
                continue
            if action == "audit":
                curses.endwin()
                print(audit_fn(sections, cur_device))
                input("\nPress enter to return to TUI...")
                stdscr.refresh()
                continue
            if action == "disable-all":
                ch = _prompt_bar(
                    stdscr,
                    "disable all unlocked keys (includes iCloud sync, Safari, Messages warnings)? [y/N]",
                )
                if ch not in (ord("y"), ord("Y")):
                    status = "disable all cancelled"
                    continue
            if action and action != "serve-qr":
                status = select_for_action(sections, action)

            if action == "serve-qr":
                mode = "qr"
            else:
                _, _, _, apps_pending = pending_changes(sections)
                if apps_pending:
                    ch = _prompt_bar(
                        stdscr,
                        f"uninstall {len(apps_pending)} stock Apple app(s) via USB? [y/N]",
                    )
                    if ch not in (ord("y"), ord("Y")):
                        for app in apps_pending:
                            app.selected = True
                if has_usb:
                    ch = _prompt_bar(
                        stdscr,
                        "Deliver: [q]r wireless  [u]sb push  [e]xport .mobileconfig  [a]irdrop  [c]ancel",
                    )
                else:
                    ch = _prompt_bar(
                        stdscr,
                        "Deliver: [q]r wireless  [e]xport .mobileconfig  [a]irdrop Finder  [c]ancel",
                    )
                key_map = {
                    ord("q"): "qr",
                    ord("Q"): "qr",
                    ord("e"): "export",
                    ord("E"): "export",
                    ord("a"): "airdrop",
                    ord("A"): "airdrop",
                }
                if has_usb:
                    key_map[ord("u")] = "usb"
                    key_map[ord("U")] = "usb"
                mode = key_map.get(ch, "")
                if not mode:
                    status = "cancelled"
                    continue

            if mode == "qr":
                curses.endwin()
                msg = apply_fn(sections, cur_device, sup_mode, "qr")
                input("\nPress enter to return to TUI...")
                stdscr.refresh()
                status = msg
            else:
                status = apply_fn(sections, cur_device, sup_mode, mode)
    return None
