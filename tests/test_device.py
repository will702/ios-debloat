"""Tests for optional pymobiledevice3 / devicectl device adapter (mocked subprocesses)."""
from __future__ import annotations

import json
import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ios_debloat import device
from ios_debloat.catalog import build_catalog
from ios_debloat.deliver import export_profile
from ios_debloat.profile_builder import build_mobileconfig, profile_identifier


def _cp(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class DeviceAdapterTests(unittest.TestCase):
    def test_list_devices_profiles_processes_crashes_and_uninstall_guard(self) -> None:
        calls: list[tuple[list[str], dict[str, str]]] = []

        def fake_runner(cmd: list[str], env: dict[str, str] | None) -> subprocess.CompletedProcess:
            calls.append((cmd, dict(env or {})))
            sub = cmd[1:3]
            if sub == ["usbmux", "list"]:
                return _cp(
                    json.dumps(
                        [
                            {
                                "UniqueDeviceID": "00008110-TEST",
                                "DeviceName": "Greg's iPhone",
                                "ProductType": "iPhone14,5",
                                "ProductVersion": "26.6.2",
                                "ConnectionType": "USB",
                            }
                        ]
                    )
                )
            if sub == ["profile", "cloud-configuration"]:
                return _cp(json.dumps({"IsSupervised": False}))
            if sub == ["profile", "list"]:
                return _cp(
                    json.dumps(
                        {
                            "ProfileMetadata": {
                                profile_identifier("ios"): {
                                    "PayloadUUID": "1111",
                                    "PayloadVersion": 1,
                                    "PayloadContent": [
                                        {
                                            "PayloadType": "com.apple.applicationaccess",
                                            "allowDiagnosticSubmission": False,
                                            "forceLimitAdTracking": True,
                                        },
                                        {
                                            "PayloadType": "com.apple.dnsSettings.managed",
                                            "DNSSettings": {"ServerURL": "https://dns.adguard-dns.com/dns-query"},
                                        },
                                    ],
                                }
                            }
                        }
                    )
                )
            if sub == ["apps", "list"]:
                return _cp(json.dumps({"com.apple.tips": {"CFBundleIdentifier": "com.apple.tips"}}))
            if sub == ["apps", "uninstall"]:
                return _cp("")
            if sub == ["processes", "ps"]:
                return _cp(
                    json.dumps(
                        {
                            "1": {"ProcessName": "launchd"},
                            "42": {"ProcessName": "analyticsd"},
                            "77": {"ProcessName": "adprivacyd"},
                        }
                    )
                )
            if sub == ["crash", "ls"]:
                # crash ls outputs plain newline-separated paths, NOT JSON!
                return _cp("Analytics-2026-11-21.ips\nJetsamEvent-2026.ips\n")
            if sub == ["profile", "install"] or sub == ["profile", "remove"]:
                return _cp("")
            return _cp("", returncode=1, stderr="unexpected cmd")

        with mock.patch.dict(os.environ, {"IOS_DEBLOAT_PMD3": "/fake/pymobiledevice3"}):
            devs = device.list_devices(runner=fake_runner)
            self.assertEqual(len(devs), 1)
            self.assertEqual(devs[0].platform, "ios")
            self.assertFalse(devs[0].supervised)
            self.assertTrue(devs[0].pmd3_available)

            profs = device.list_profiles(udid="00008110-TEST", runner=fake_runner)
            keys, dns_id = device.get_active_debloat_keys(profs)
            self.assertEqual(keys, {"allowDiagnosticSubmission", "forceLimitAdTracking"})
            self.assertEqual(dns_id, "dns:adguard")

            procs = device.list_running_processes(udid="00008110-TEST", runner=fake_runner)
            self.assertTrue(any(p["name"] == "analyticsd" for p in procs))

            crashes = device.list_crash_reports(udid="00008110-TEST", runner=fake_runner)
            self.assertEqual(crashes, ["Analytics-2026-11-21.ips", "JetsamEvent-2026.ips"])

            apps = device.list_installed_apps(udid="00008110-TEST", runner=fake_runner)
            self.assertIn("com.apple.tips", apps)

            # Allowlist permits removable stock app
            device.uninstall_stock_app("com.apple.tips", udid="00008110-TEST", runner=fake_runner)

            # Allowlist blocks core SSV apps before invoking subprocess
            with self.assertRaises(ValueError):
                device.uninstall_stock_app("com.apple.Preferences", udid="00008110-TEST", runner=fake_runner)
            with self.assertRaises(ValueError):
                device.uninstall_stock_app("com.apple.MobileSafari", udid="00008110-TEST", runner=fake_runner)

            # Keybag install passes --keybag flag
            device.install_profile(
                Path("/tmp/p.mobileconfig"),
                udid="00008110-TEST",
                keybag=Path("/tmp/keybag.pem"),
                wifi=True,
                runner=fake_runner,
            )

        # Verify NO_COLOR=1 and PYMOBILEDEVICE3_UDID propagated to subprocesses
        prof_calls = [c for c in calls if c[0][1:3] == ["profile", "install"]]
        self.assertEqual(len(prof_calls), 1)
        cmd_used, env_used = prof_calls[0]
        self.assertIn("--keybag", cmd_used)
        self.assertIn("--mobdev2", cmd_used)
        self.assertEqual(env_used["NO_COLOR"], "1")
        self.assertEqual(env_used["PYMOBILEDEVICE3_UDID"], "00008110-TEST")

    def test_offline_when_pmd3_and_devicectl_absent(self) -> None:
        with mock.patch("ios_debloat.device.pmd3_path", return_value=None):
            with mock.patch("ios_debloat.device.devicectl_list_devices", return_value=[]):
                self.assertEqual(device.list_devices(), [])

    def test_real_ios_profile_list_reconciles_with_local_mobileconfig(self) -> None:
        sections = build_catalog("all")
        for sec in sections:
            for it in sec.items:
                if it.id in ("allowDiagnosticSubmission", "allowApplePersonalizedAdvertising", "forceLimitAdTracking"):
                    it.selected = False
                elif it.kind == "dns":
                    it.selected = it.id == "dns:adguard"

        xml_bytes, _ = build_mobileconfig(sections, target="all", supervised=False)
        doc = plistlib.loads(xml_bytes)

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"IOS_DEBLOAT_HOME": tmp}):
                export_profile(xml_bytes, target="all")

                # Real iOS 26.6.2 GetProfileList shape omits PayloadContent from ProfileMetadata
                real_ios_resp = {
                    "OrderedIdentifiers": ["io.github.ios-debloat.profile.all"],
                    "ProfileManifest": {
                        "io.github.ios-debloat.profile.all": {
                            "Description": doc["PayloadDisplayName"],
                            "IsActive": True,
                        }
                    },
                    "ProfileMetadata": {
                        "io.github.ios-debloat.profile.all": {
                            "PayloadDisplayName": doc["PayloadDisplayName"],
                            "PayloadUUID": doc["PayloadUUID"],
                            "PayloadVersion": 1,
                        }
                    },
                    "Status": "Acknowledged",
                }
                keys, dns_id = device.get_active_debloat_keys(real_ios_resp)
                self.assertEqual(
                    keys,
                    {"allowDiagnosticSubmission", "allowApplePersonalizedAdvertising", "forceLimitAdTracking"},
                )
                self.assertEqual(dns_id, "dns:adguard")

                # When removed from device Settings, empty ProfileMetadata yields empty state
                removed_keys, removed_dns = device.get_active_debloat_keys(
                    {"OrderedIdentifiers": [], "ProfileManifest": {}, "ProfileMetadata": {}, "Status": "Acknowledged"}
                )
                self.assertEqual(removed_keys, set())
                self.assertIsNone(removed_dns)


if __name__ == "__main__":
    unittest.main()
