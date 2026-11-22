"""Profile export, local LAN HTTP QR server, and macOS AirDrop reveal."""
from __future__ import annotations

import datetime
import secrets
import socket
import subprocess
import sys
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

from ios_debloat.qr import render_terminal
from ios_debloat.state import profiles_dir


def export_profile(
    profile_bytes: bytes,
    *,
    target: str = "all",
    out_path: Optional[Path] = None,
) -> Path:
    """Write `.mobileconfig` bytes to `out_path` or `~/.ios-debloat/profiles/`."""
    if out_path is not None:
        dest = Path(out_path).expanduser()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(profile_bytes)
        return dest

    pdir = profiles_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = pdir / f"ios-debloat-{target}-{stamp}.mobileconfig"
    dest.write_bytes(profile_bytes)
    latest = pdir / "latest.mobileconfig"
    latest.write_bytes(profile_bytes)
    return dest


def detect_lan_ip() -> str:
    """Return the host's primary LAN IPv4 address without sending network traffic."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        ip = sock.getsockname()[0]
        if ip:
            return str(ip)
    except OSError:
        pass
    finally:
        sock.close()
    return "127.0.0.1"


class _ProfileHTTPHandler(BaseHTTPRequestHandler):
    profile_bytes: bytes = b""
    expected_path: str = "/"
    filename: str = "ios-debloat.mobileconfig"
    stats: dict[str, int] = {"downloads": 0}
    on_download: Any = None

    def do_GET(self) -> None:  # noqa: N802
        clean_path = self.path.split("?", 1)[0]
        if clean_path != self.expected_path:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not found\n")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-apple-aspen-config")
        self.send_header("Content-Disposition", f'attachment; filename="{self.filename}"')
        self.send_header("Content-Length", str(len(self.profile_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(self.profile_bytes)
        self.stats["downloads"] = self.stats.get("downloads", 0) + 1
        if self.on_download is not None:
            self.on_download(self.client_address[0])

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def start_profile_server(
    profile_bytes: bytes,
    *,
    port: int = 8765,
    bind_ip: str = "0.0.0.0",
    host_ip: Optional[str] = None,
    filename: str = "ios-debloat.mobileconfig",
    token: Optional[str] = None,
    on_download: Any = None,
) -> tuple[ThreadingHTTPServer, str, dict[str, int]]:
    """Start a threaded HTTP server serving the profile at a tokenized URL."""
    tok = token or secrets.token_hex(4)
    expected_path = f"/{tok}/{filename}"
    stats = {"downloads": 0}

    handler_cls = type(
        "BoundProfileHandler",
        (_ProfileHTTPHandler,),
        {
            "profile_bytes": profile_bytes,
            "expected_path": expected_path,
            "filename": filename,
            "stats": stats,
            "on_download": staticmethod(on_download) if on_download else None,
        },
    )
    server = ThreadingHTTPServer((bind_ip, port), handler_cls)
    actual_port = server.server_address[1]
    advertise_ip = host_ip or (bind_ip if bind_ip not in ("0.0.0.0", "") else detect_lan_ip())
    url = f"http://{advertise_ip}:{actual_port}{expected_path}"
    return server, url, stats


def serve_profile_qr(
    profile_bytes: bytes,
    *,
    port: int = 8765,
    bind_ip: str = "0.0.0.0",
    one_shot: bool = False,
) -> int:
    """Print terminal QR code + install guide and serve `.mobileconfig` over LAN HTTP."""
    downloads: list[str] = []

    def _note(client_ip: str) -> None:
        downloads.append(client_ip)
        print(f"Downloaded by {client_ip} — open Settings -> Profile Downloaded -> Install on your iPhone/iPad.")
        sys.stdout.flush()

    server, url, _ = start_profile_server(
        profile_bytes,
        port=port,
        bind_ip=bind_ip,
        on_download=_note,
    )
    try:
        qr_art = render_terminal(url, quiet=2, invert=True)
        print("\nScan this QR code with your iPhone or iPad Camera (same Wi-Fi network):\n")
        print(qr_art)
        print(f"\nURL: {url}\n")
        print("Install steps on iPhone / iPad:")
        print("  1. Scan the QR code -> tap the Safari banner -> tap Allow.")
        print("  2. Open Settings -> Profile Downloaded (or General -> VPN & Device Management).")
        print("  3. Tap Install (profile is 100% reversible: tap Remove Profile anytime).")
        print("\nWaiting for download... press Ctrl-C to stop." if not one_shot else "\nWaiting for 1 download...")
        sys.stdout.flush()

        if one_shot:
            while not downloads:
                server.handle_request()
        else:
            server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped QR server.")
    finally:
        server.server_close()
    return 0


def reveal_for_airdrop(path: Path) -> bool:
    """Reveal `.mobileconfig` in macOS Finder for one-click Share -> AirDrop."""
    if sys.platform != "darwin":
        return False
    res = subprocess.run(["open", "-R", str(path)], capture_output=True, text=True, check=False)
    return res.returncode == 0
