"""Local state, snapshots (--restore), watchOS checklist, and user overrides (~/.ios-debloat)."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, Optional

from ios_debloat.models import Item, Section


def state_home() -> Path:
    """Return base directory for snapshots, profiles, checklist, and user presets."""
    override = os.environ.get("IOS_DEBLOAT_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".ios-debloat"


def profiles_dir() -> Path:
    return state_home() / "profiles"


def presets_dir() -> Path:
    return state_home() / "presets"


def snapshots_dir() -> Path:
    return state_home() / "snapshots"


def supervision_dir() -> Path:
    return state_home() / "supervision"


def watch_checklist_path() -> Path:
    return state_home() / "watch-checklist.json"


def last_state_path() -> Path:
    return state_home() / "last-state.json"


def labels_file() -> Path:
    return state_home() / "labels.txt"


def default_keybag_path() -> Path:
    return supervision_dir() / "keybag.pem"


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _extract_disabled_state(sections: list[Section]) -> tuple[list[str], str]:
    disabled_ids: list[str] = []
    dns_id = "dns:none"
    for sec in sections:
        for it in sec.items:
            if it.kind == "restriction" and it.disabled:
                disabled_ids.append(it.id)
            elif it.kind == "dns" and it.active:
                dns_id = it.id
    return sorted(disabled_ids), dns_id


def write_snapshot(
    sections: list[Section],
    *,
    device_id: str = "offline",
    supervised: bool = False,
) -> Path:
    """Save current pre-apply state so `--restore` can revert cleanly."""
    disabled_ids, dns_id = _extract_disabled_state(sections)
    payload = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "device_id": device_id,
        "supervised": supervised,
        "disabled_restrictions": disabled_ids,
        "dns_id": dns_id,
    }
    sdir = snapshots_dir()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    _write_json(sdir / f"snapshot-{stamp}.json", payload)
    return _write_json(sdir / "latest.json", payload)


def load_latest_snapshot() -> Optional[dict[str, Any]]:
    """Load the most recent pre-apply snapshot, or None if absent."""
    return _read_json(snapshots_dir() / "latest.json")


def save_last_state(
    sections: list[Section],
    *,
    supervised: bool = False,
    target: str = "all",
    device_id: str = "offline",
) -> Path:
    """Persist the last applied selection so offline mode remembers active choices."""
    disabled_ids = sorted(
        it.id
        for sec in sections
        for it in sec.items
        if it.kind == "restriction" and not it.selected
    )
    dns_id = "dns:none"
    for sec in sections:
        for it in sec.items:
            if it.kind == "dns" and it.selected:
                dns_id = it.id
                break
    payload = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "device_id": device_id,
        "target": target,
        "supervised": supervised,
        "disabled_restrictions": disabled_ids,
        "dns_id": dns_id,
    }
    return _write_json(last_state_path(), payload)


def load_last_state() -> Optional[dict[str, Any]]:
    """Return the last saved offline/applied selection state."""
    return _read_json(last_state_path())


def apply_saved_state(sections: list[Section], state: Optional[dict[str, Any]]) -> None:
    """Apply saved restriction/DNS state onto `sections` in place."""
    if not state:
        return
    disabled_set = set(state.get("disabled_restrictions") or [])
    dns_id = str(state.get("dns_id") or "dns:none")
    for sec in sections:
        for it in sec.items:
            if it.kind == "restriction":
                is_off = it.id in disabled_set
                it.disabled = is_off
                it.selected = not is_off
            elif it.kind == "dns":
                is_cur = it.id == dns_id
                it.active = is_cur
                it.selected = is_cur


def load_watch_checklist() -> set[str]:
    """Load completed watchOS manual checklist IDs."""
    data = _read_json(watch_checklist_path())
    if not data:
        return set()
    items = data.get("completed")
    if isinstance(items, list):
        return {str(x) for x in items}
    return set()


def save_watch_checklist(done_ids: set[str]) -> Path:
    """Save completed watchOS manual checklist IDs."""
    return _write_json(
        watch_checklist_path(),
        {
            "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "completed": sorted(done_ids),
        },
    )


def apply_watch_checklist(sections: list[Section], done_ids: set[str]) -> None:
    """Synchronize watchOS checklist `selected` and `active` flags from `done_ids`."""
    for sec in sections:
        for it in sec.items:
            if it.kind == "watch_check":
                done = it.id in done_ids
                it.selected = done
                it.active = done


def load_user_labels(path: Optional[Path] = None) -> list[Item]:
    """Load custom Apple restriction keys from `~/.ios-debloat/labels.txt`."""
    target = path or labels_file()
    if not target.is_file():
        return []
    items: list[Item] = []
    for raw in target.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        code, _, comment = stripped.partition("#")
        parts = code.strip().split()
        if not parts:
            continue
        key = parts[0]
        supervised = "[supervised]" in parts[1:] or "[supervised]" in comment
        clean_comment = comment.replace("[supervised]", "").strip() or "Custom user restriction key."
        items.append(
            Item(
                id=key,
                kind="restriction",
                label=key,
                section="User Custom Labels",
                comment=clean_comment,
                supervised=supervised,
                platforms=("ios", "ipados", "watchos"),
                payload_key=key,
                debloat_value=False,
                disabled=False,
                selected=True,
            )
        )
    return items
