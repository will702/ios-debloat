"""Core dataclasses for ios-watchos-ipados-debloat."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Item:
    """Single toggleable row, radio choice, checklist task, or action in the TUI/CLI."""

    id: str
    kind: str  # "action" | "restriction" | "dns" | "stock_app" | "watch_check"
    label: str
    section: str
    comment: str
    presets: tuple[str, ...] = ()
    supervised: bool = False
    platforms: tuple[str, ...] = ("ios", "ipados")
    payload_key: Optional[str] = None
    debloat_value: bool = False
    ddm_spec: Optional[tuple[str, tuple[str, ...], bool]] = None
    dns_config: Optional[dict[str, object]] = None
    bundle_id: Optional[str] = None
    deprecated_in: Optional[str] = None
    # Runtime state:
    # - restriction / stock_app: selected=True ([✓]) means ON/installed; selected=False ([ ]) means debloated/removed.
    #   disabled=True means currently debloated/removed on target/state.
    # - dns: selected=True ((•)) means chosen DNS; active=True means currently applied DNS.
    # - watch_check: selected=True ([x]) means user completed manual step; active=True means saved completed.
    disabled: bool = False
    selected: bool = True
    active: bool = False
    locked: bool = False
    lock_reason: str = ""
    action: str = ""


@dataclass
class Section:
    """Logical group of items displayed together in the TUI and --list output."""

    title: str
    kind: str  # "action" | "dns" | "restriction" | "stock_app" | "watch_check"
    items: list[Item] = field(default_factory=list)


@dataclass
class DeviceInfo:
    """Metadata for a connected or offline target Apple device."""

    udid: str = ""
    name: str = "Offline"
    product_type: str = ""
    os_version: str = ""
    platform: str = "all"  # "ios" | "ipados" | "watchos" | "all"
    supervised: bool = False
    connection: str = "offline"  # "usb" | "wifi" | "devicectl" | "offline"
    pmd3_available: bool = False


@dataclass
class CatalogStats:
    """Summary counts across the catalog for docs, CLI help, and --status."""

    sections: int
    restrictions_total: int
    restrictions_unsupervised: int
    restrictions_supervised: int
    telemetry_preset: int
    balanced_preset: int
    dns_presets: int
    stock_apps: int
    watch_checklist: int
    watch_profile_keys: int
    telemetry_daemons: int
