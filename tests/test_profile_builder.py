"""Tests for .mobileconfig XML generation, DDM JSON export, and validation."""
from __future__ import annotations

import json
import plistlib
import tempfile
import unittest
from pathlib import Path

from ios_debloat.catalog import APPLE_TELEMETRY_DOMAINS, SILENCE_NOTIFICATION_BUNDLES, build_catalog
from ios_debloat.profile_builder import (
    build_dns_only_mobileconfig,
    build_mobileconfig,
    export_ddm_declarations,
    profile_identifier,
    validate_profile,
)
from ios_debloat.tui import apply_locks, select_for_action


class ProfileBuilderTests(unittest.TestCase):
    def test_unsupervised_profile_filters_supervised_keys_and_passes_plutil(self) -> None:
        sections = build_catalog("all")
        apply_locks(sections, supervised_mode=False, has_usb_pmd3=False)
        select_for_action(sections, "preset:balanced")

        xml_bytes, summary = build_mobileconfig(sections, target="ios", supervised=False)
        ok, errs = validate_profile(xml_bytes, expect_unsupervised=True)
        self.assertTrue(ok, f"Validation errors: {errs}")
        self.assertGreater(summary["restriction_count"], 0)

        doc = plistlib.loads(xml_bytes)
        self.assertEqual(doc["PayloadIdentifier"], profile_identifier("ios"))
        self.assertFalse(doc["PayloadRemovalDisallowed"])

        res_payload = next(p for p in doc["PayloadContent"] if p["PayloadType"] == "com.apple.applicationaccess")
        self.assertFalse(res_payload["allowDiagnosticSubmission"])
        self.assertTrue(res_payload["forceLimitAdTracking"])
        self.assertTrue(res_payload["forceOnDeviceOnlyDictation"])
        self.assertNotIn("allowWritingTools", res_payload)

        # Defense-in-depth: even if a supervised item is manually marked selected=False,
        # build_mobileconfig(..., supervised=False) strips it and records skipped_supervised.
        for s in sections:
            for it in s.items:
                if it.id == "allowWritingTools":
                    it.selected = False
        xml2, summary2 = build_mobileconfig(sections, target="ios", supervised=False)
        ok2, errs2 = validate_profile(xml2, expect_unsupervised=True)
        self.assertTrue(ok2, f"Defense-in-depth validation failed: {errs2}")
        self.assertIn("allowWritingTools", summary2["skipped_supervised"])

    def test_supervised_profile_includes_ai_keys_and_notification_silencing(self) -> None:
        sections = build_catalog("all")
        apply_locks(sections, supervised_mode=True, has_usb_pmd3=False)
        select_for_action(sections, "preset:balanced")

        xml_bytes, summary = build_mobileconfig(
            sections,
            target="ipados",
            supervised=True,
            silence_stock_notifications=True,
        )
        ok, errs = validate_profile(xml_bytes, expect_unsupervised=False)
        self.assertTrue(ok, f"Validation errors: {errs}")
        self.assertEqual(summary["skipped_supervised"], [])
        self.assertTrue(summary["notifications_silenced"])

        doc = plistlib.loads(xml_bytes)
        res_payload = next(p for p in doc["PayloadContent"] if p["PayloadType"] == "com.apple.applicationaccess")
        self.assertFalse(res_payload["allowWritingTools"])
        self.assertFalse(res_payload["allowMailSummary"])

        notif_payload = next(p for p in doc["PayloadContent"] if p["PayloadType"] == "com.apple.notificationsettings")
        bundles = [entry["BundleIdentifier"] for entry in notif_payload["NotificationSettings"]]
        self.assertEqual(bundles, list(SILENCE_NOTIFICATION_BUNDLES))

    def test_deterministic_uuidv5_across_builds(self) -> None:
        s1 = build_catalog("all")
        s2 = build_catalog("all")
        select_for_action(s1, "preset:telemetry")
        select_for_action(s2, "preset:telemetry")

        b1, _ = build_mobileconfig(s1, target="all", supervised=False)
        b2, _ = build_mobileconfig(s2, target="all", supervised=False)
        self.assertEqual(plistlib.loads(b1)["PayloadUUID"], plistlib.loads(b2)["PayloadUUID"])

    def test_dns_payload_global_and_apple_split(self) -> None:
        xml_bytes, summary = build_dns_only_mobileconfig("adguard", dns_apple_only=True, target="ios")
        ok, errs = validate_profile(xml_bytes, expect_unsupervised=True)
        self.assertTrue(ok, f"DNS profile invalid: {errs}")
        self.assertEqual(summary["dns"], "dns:adguard")
        self.assertTrue(summary["dns_apple_only"])

        doc = plistlib.loads(xml_bytes)
        dns_payload = doc["PayloadContent"][0]
        self.assertEqual(dns_payload["PayloadType"], "com.apple.dnsSettings.managed")
        settings = dns_payload["DNSSettings"]
        self.assertEqual(settings["DNSProtocol"], "HTTPS")
        self.assertEqual(settings["ServerURL"], "https://dns.adguard-dns.com/dns-query")
        self.assertTrue(settings["AllowFailover"])
        self.assertEqual(settings["SupplementalMatchDomains"], list(APPLE_TELEMETRY_DOMAINS))

    def test_ddm_export_matches_apple_nested_schema(self) -> None:
        sections = build_catalog("all")
        apply_locks(sections, supervised_mode=True, has_usb_pmd3=False)
        select_for_action(sections, "preset:balanced")

        with tempfile.TemporaryDirectory() as tmp:
            paths = export_ddm_declarations(sections, Path(tmp), supervised=True)
            names = {p.name for p in paths}
            self.assertIn("com.apple.configuration.intelligence.settings.json", names)
            self.assertIn("com.apple.configuration.siri.settings.json", names)
            self.assertIn("com.apple.configuration.external-intelligence.settings.json", names)
            self.assertIn("com.apple.configuration.keyboard.settings.json", names)

            intel = json.loads((Path(tmp) / "com.apple.configuration.intelligence.settings.json").read_text("utf-8"))
            self.assertEqual(intel["Type"], "com.apple.configuration.intelligence.settings")
            payload = intel["Payload"]
            self.assertFalse(payload["AllowWritingTools"])
            self.assertTrue(payload["ForceOnDeviceOnlyDictation"])
            self.assertFalse(payload["Apps"]["Mail"]["AllowSummary"])
            self.assertFalse(payload["Apps"]["Notes"]["AllowTranscription"])
            self.assertFalse(payload["Apps"]["Safari"]["AllowSummary"])


if __name__ == "__main__":
    unittest.main()
