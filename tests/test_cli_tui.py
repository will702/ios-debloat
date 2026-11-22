"""End-to-end CLI tests, TUI state machine tests, and README count sync check."""
from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ios_debloat import cli
from ios_debloat.catalog import build_catalog
from ios_debloat.models import DeviceInfo
from ios_debloat.tui import (
    apply_locks,
    build_display_rows,
    flat_index,
    jump_section,
    keep_locked_on,
    menu_section,
    pending_changes,
    select_for_action,
)

ROOT = Path(__file__).resolve().parent.parent


class CLIAandTUITests(unittest.TestCase):
    def _run_cli(self, args: list[str], home: Path) -> tuple[int, str, str]:
        env = os.environ.copy()
        env["IOS_DEBLOAT_HOME"] = str(home)
        env["IOS_DEBLOAT_PMD3"] = "/nonexistent-pmd3-for-offline-test"
        with mock.patch.dict(os.environ, env):
            with mock.patch("ios_debloat.device.pmd3_path", return_value=None):
                with mock.patch("ios_debloat.device.devicectl_list_devices", return_value=[]):
                    import io
                    from contextlib import redirect_stderr, redirect_stdout

                    out, err = io.StringIO(), io.StringIO()
                    with redirect_stdout(out), redirect_stderr(err):
                        code = cli.main(args)
                    return code, out.getvalue(), err.getvalue()

    def test_cli_offline_flows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)

            code, out, _ = self._run_cli(["--version"], home)
            self.assertEqual(code, 0)
            self.assertIn("ios-watchos-ipados-debloat", out)

            code, out, _ = self._run_cli(["--list"], home)
            self.assertEqual(code, 0)
            self.assertIn("allowDiagnosticSubmission", out)

            code, out, _ = self._run_cli(["--preset", "telemetry", "--dry-run"], home)
            self.assertEqual(code, 0)
            dry = json.loads(out)
            self.assertGreaterEqual(dry["restriction_count"], 5)
            self.assertEqual(dry["supervised"], False)

            mc_out = home / "out.mobileconfig"
            code, out, _ = self._run_cli(
                [
                    "--preset",
                    "balanced",
                    "--dns",
                    "adguard",
                    "--dns-apple-only",
                    "--target",
                    "ios",
                    "--out",
                    str(mc_out),
                ],
                home,
            )
            self.assertEqual(code, 0)
            self.assertTrue(mc_out.is_file())
            plist = plistlib.loads(mc_out.read_bytes())
            self.assertEqual(plist["PayloadIdentifier"], "io.github.ios-debloat.profile.ios")

            ddm_dir = home / "ddm"
            code, out, _ = self._run_cli(
                ["--preset", "balanced", "--supervised", "--export-ddm", str(ddm_dir)],
                home,
            )
            self.assertEqual(code, 0)
            self.assertTrue((ddm_dir / "com.apple.configuration.intelligence.settings.json").is_file())

            code, out, _ = self._run_cli(["--export-blocklist", "adguard"], home)
            self.assertEqual(code, 0)
            self.assertIn("||metrics.apple.com^", out)

            code, out, _ = self._run_cli(["--status", "--json"], home)
            self.assertEqual(code, 0)
            st = json.loads(out)
            self.assertEqual(st["mode"], "unsupervised")

            code, out, _ = self._run_cli(["--audit", "--json"], home)
            self.assertEqual(code, 0)
            aud = json.loads(out)
            self.assertEqual(aud["mode"], "offline")

            code, out, _ = self._run_cli(["--watch-checklist", "--check", "watch:bg-refresh"], home)
            self.assertEqual(code, 0)
            self.assertIn("[x] watch:bg-refresh", out)

            code, out, _ = self._run_cli(["--supervise-guide"], home)
            self.assertEqual(code, 0)
            self.assertIn("Apple Configurator", out)

            code, out, _ = self._run_cli(["--create-keybag", "TestOrg"], home)
            self.assertEqual(code, 0)
            kb = home / "supervision" / "keybag.pem"
            self.assertTrue(kb.is_file())
            self.assertEqual(kb.stat().st_mode & 0o777, 0o600)

            # Snapshot & --restore
            restored_mc = home / "restored.mobileconfig"
            code, _, _ = self._run_cli(["--restore", "--out", str(restored_mc)], home)
            self.assertEqual(code, 0)
            self.assertTrue(restored_mc.is_file())

    def test_tui_state_machine_and_navigation(self) -> None:
        sections = build_catalog("all")
        dev = DeviceInfo(name="Test iPhone", os_version="26.6.2", platform="ios", supervised=False, connection="offline")
        apply_locks(sections, supervised_mode=False, has_usb_pmd3=False)

        msg = select_for_action(sections, "preset:balanced")
        self.assertIn("need supervision, skipped", msg)
        kept = keep_locked_on(sections)
        self.assertEqual(kept, 0)

        dis, en, dns, apps = pending_changes(sections)
        self.assertGreater(len(dis), 0)
        self.assertEqual(en, [])
        self.assertIsNone(dns)
        self.assertEqual(apps, [])

        # Menu + sections layout & jump_section
        view = [menu_section(sections, device=dev, supervised_mode=False), *sections]
        flat = flat_index(view)
        rows, item_map = build_display_rows(view)
        self.assertEqual(len(item_map), len(flat))
        self.assertTrue(any(k == "section" for k, _ in rows))

        next_idx = jump_section(view, flat, 0, direction=1)
        self.assertGreater(next_idx, 0)
        prev_idx = jump_section(view, flat, next_idx, direction=-1)
        self.assertEqual(prev_idx, 0)

    def test_readme_sync_check(self) -> None:
        res = subprocess.run(
            [sys.executable, str(ROOT / "extras" / "sync_readme.py"), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
