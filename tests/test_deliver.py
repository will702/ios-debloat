"""Tests for LAN HTTP profile server, export, and snapshot/--restore state."""
from __future__ import annotations

import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from ios_debloat.catalog import build_catalog
from ios_debloat.deliver import export_profile, start_profile_server
from ios_debloat.profile_builder import build_mobileconfig
from ios_debloat.state import (
    apply_saved_state,
    load_latest_snapshot,
    load_watch_checklist,
    save_watch_checklist,
    write_snapshot,
)
from ios_debloat.tui import select_for_action


class DeliverAndStateTests(unittest.TestCase):
    def test_http_profile_server_serves_exact_bytes_and_404s_wrong_token(self) -> None:
        sections = build_catalog("all")
        select_for_action(sections, "preset:telemetry")
        profile_bytes, _ = build_mobileconfig(sections, target="ios", supervised=False)

        server, url, stats = start_profile_server(
            profile_bytes,
            port=0,
            bind_ip="127.0.0.1",
            host_ip="127.0.0.1",
            token="deadbeef",
        )
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get("Content-Type"), "application/x-apple-aspen-config")
                body = resp.read()
                self.assertEqual(body, profile_bytes)
            self.assertEqual(stats["downloads"], 1)

            bad_url = url.replace("/deadbeef/", "/wrongtok/")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(bad_url, timeout=5)
            self.assertEqual(ctx.exception.code, 404)
            ctx.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=2)

    def test_export_snapshot_restore_and_watch_checklist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"IOS_DEBLOAT_HOME": tmp}):
                sections = build_catalog("all")
                for sec in sections:
                    for it in sec.items:
                        if it.id == "allowDiagnosticSubmission":
                            it.disabled = True
                            it.selected = False

                snap_path = write_snapshot(sections, device_id="offline", supervised=False)
                self.assertTrue(snap_path.is_file())

                # Mutate state after snapshot
                select_for_action(sections, "preset:balanced")
                loaded_snap = load_latest_snapshot()
                assert loaded_snap is not None
                fresh = build_catalog("all")
                apply_saved_state(fresh, loaded_snap)
                diag = next(it for s in fresh for it in s.items if it.id == "allowDiagnosticSubmission")
                siri = next(it for s in fresh for it in s.items if it.id == "allowAssistant")
                self.assertTrue(diag.disabled)
                self.assertFalse(diag.selected)
                self.assertFalse(siri.disabled)
                self.assertTrue(siri.selected)

                # Export default profile location
                exported = export_profile(b"<plist/>", target="ios")
                self.assertTrue(exported.is_file())
                self.assertTrue((Path(tmp) / "profiles" / "latest.mobileconfig").is_file())

                # Watch checklist round-trip
                save_watch_checklist({"watch:bg-refresh", "watch:noise"})
                self.assertEqual(load_watch_checklist(), {"watch:bg-refresh", "watch:noise"})


if __name__ == "__main__":
    unittest.main()
