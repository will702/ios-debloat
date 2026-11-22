"""Tests for catalog invariants, presets, target filtering, and blocklist exports."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ios_debloat.catalog import (
    REMOVABLE_STOCK_APP_IDS,
    build_catalog,
    catalog_stats,
    export_blocklist,
    format_catalog_list,
    resolve_preset,
)


class CatalogTests(unittest.TestCase):
    def test_no_duplicate_ids_or_payload_keys(self) -> None:
        sections = build_catalog("all")
        all_items = [it for sec in sections for it in sec.items]
        ids = [it.id for it in all_items]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate item IDs in catalog")

        payload_keys = [it.payload_key for it in all_items if it.payload_key]
        self.assertEqual(len(payload_keys), len(set(payload_keys)), "Duplicate Apple restriction keys")

    def test_allow_vs_force_polarity(self) -> None:
        sections = build_catalog("all")
        for sec in sections:
            for it in sec.items:
                if it.kind != "restriction" or not it.payload_key:
                    continue
                if it.payload_key.startswith("allow"):
                    self.assertFalse(it.debloat_value, f"{it.payload_key} should debloat to False")
                elif it.payload_key.startswith("force"):
                    self.assertTrue(it.debloat_value, f"{it.payload_key} should debloat to True")

    def test_removed_ios27_keys_absent(self) -> None:
        sections = build_catalog("all")
        keys = {it.payload_key for sec in sections for it in sec.items if it.payload_key}
        self.assertNotIn("enforcedSoftwareUpdateDelay", keys)
        self.assertNotIn("forceDelayedSoftwareUpdates", keys)

    def test_core_ssv_apps_excluded_from_uninstall_allowlist(self) -> None:
        forbidden = {
            "com.apple.Preferences",
            "com.apple.MobileSafari",
            "com.apple.mobilephone",
            "com.apple.MobileSMS",
            "com.apple.AppStore",
            "com.apple.camera",
            "com.apple.mobileslideshow",
        }
        self.assertTrue(forbidden.isdisjoint(REMOVABLE_STOCK_APP_IDS))

    def test_preset_subset_invariants_and_custom_presets(self) -> None:
        sections = build_catalog("all")
        tel = resolve_preset(sections, "telemetry")
        bal = resolve_preset(sections, "balanced")
        all_res = {it.id for s in sections for it in s.items if it.kind == "restriction"}
        assert tel is not None and bal is not None
        self.assertTrue(tel.issubset(bal))
        self.assertTrue(bal.issubset(all_res))

        with tempfile.TemporaryDirectory() as tmp:
            pdir = Path(tmp)
            (pdir / "mine.txt").write_text(
                "# comment\nallowDiagnosticSubmission # keep this off\nnonexistentKey\n",
                encoding="utf-8",
            )
            custom = resolve_preset(sections, "mine", presets_dir=pdir)
            self.assertEqual(custom, {"allowDiagnosticSubmission"})
            self.assertIsNone(resolve_preset(sections, "missing", presets_dir=pdir))

    def test_target_filtering_watchos(self) -> None:
        watch_secs = build_catalog("watchos")
        res_keys = {it.id for s in watch_secs for it in s.items if it.kind == "restriction"}
        self.assertEqual(
            res_keys,
            {
                "allowAssistantWhileLocked",
                "allowAssistantUserGeneratedContent",
                "forceOnDeviceOnlyDictation",
                "forceOnDeviceOnlyTranslation",
                "allowAutomaticAppDownloads",
            },
        )
        kinds = {s.kind for s in watch_secs}
        self.assertNotIn("stock_app", kinds)
        self.assertNotIn("dns", kinds)
        self.assertIn("watch_check", kinds)
        self.assertEqual(watch_secs[0].kind, "watch_check")

    def test_stats_and_blocklist_formats(self) -> None:
        stats = catalog_stats()
        self.assertGreater(stats.restrictions_total, 50)
        self.assertEqual(stats.restrictions_total, stats.restrictions_unsupervised + stats.restrictions_supervised)

        domains = export_blocklist("domains")
        adguard = export_blocklist("adguard")
        hosts = export_blocklist("hosts")
        self.assertIn("metrics.apple.com", domains)
        self.assertIn("||metrics.apple.com^", adguard)
        self.assertIn("0.0.0.0 metrics.apple.com", hosts)
        self.assertNotIn("icloud.com", domains.splitlines())
        self.assertNotIn("apple.com", domains.splitlines())

        listed = format_catalog_list(build_catalog("all"))
        self.assertIn("allowDiagnosticSubmission", listed)


if __name__ == "__main__":
    unittest.main()
