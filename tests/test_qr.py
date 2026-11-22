"""Tests for pure-Python QR encoder and real macOS CoreImage QR round-trip decoding."""
from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from ios_debloat.qr import encode_qr, render_terminal


def _matrix_to_png(matrix: list[list[bool]], scale: int = 8, quiet: int = 4) -> bytes:
    """Minimal zero-dep PNG encoder for CoreImage QR round-trip verification."""
    n = len(matrix)
    dim = (n + 2 * quiet) * scale
    raw_rows: list[bytes] = []
    for pr in range(dim):
        mr = (pr // scale) - quiet
        row = bytearray([0])  # filter type 0
        for pc in range(dim):
            mc = (pc // scale) - quiet
            dark = 0 <= mr < n and 0 <= mc < n and matrix[mr][mc]
            row.append(0 if dark else 255)
        raw_rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", dim, dim, 8, 0, 0, 0, 0)
    idat = zlib.compress(b"".join(raw_rows), level=6)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _coreimage_decode_batch(image_paths: list[Path]) -> list[str]:
    """Decode QR PNGs using macOS CoreImage CIDetectorTypeQRCode via Swift."""
    swift_code = """\
import Foundation
import CoreImage

let detector = CIDetector(
    ofType: CIDetectorTypeQRCode,
    context: nil,
    options: [CIDetectorAccuracy: CIDetectorAccuracyHigh]
)!

for path in CommandLine.arguments.dropFirst() {
    let url = URL(fileURLWithPath: path)
    guard let img = CIImage(contentsOf: url) else {
        print("ERR:LOAD")
        continue
    }
    let features = detector.features(in: img)
    if let qr = features.first as? CIQRCodeFeature, let msg = qr.messageString {
        print("OK:" + msg)
    } else {
        print("ERR:NONE")
    }
}
"""
    with tempfile.NamedTemporaryFile(suffix=".swift", mode="w", encoding="utf-8", delete=False) as sf:
        sf.write(swift_code)
        swift_path = Path(sf.name)
    try:
        res = subprocess.run(
            ["xcrun", "swift", str(swift_path), *(str(p) for p in image_paths)],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"CoreImage swift decode failed: {res.stderr}")
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    finally:
        if swift_path.exists():
            swift_path.unlink()


class QRTests(unittest.TestCase):
    def test_qr_matrix_dimensions_and_terminal_render(self) -> None:
        m1 = encode_qr("https://example.com")  # 19 bytes -> V2 (25x25)
        self.assertEqual(len(m1), 25)
        self.assertEqual(len(m1[0]), 25)

        m_short = encode_qr("http://1.2.3.4:1")  # 16 bytes -> V1 (21x21)
        self.assertEqual(len(m_short), 21)

        art = render_terminal("http://192.168.1.42:8765/a1b2c3d4/ios-debloat.mobileconfig")
        lines = art.splitlines()
        self.assertGreater(len(lines), 15)
        self.assertTrue(all(len(line) == len(lines[0]) for line in lines))

        with self.assertRaises(ValueError):
            encode_qr("x" * 200)

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("xcrun"), "macOS CoreImage test")
    def test_coreimage_roundtrip_across_versions_1_to_7(self) -> None:
        payloads = [
            "http://10.0.0.1:9",                                                        # V1 (17B)
            "http://192.168.1.1:8765/ab.mc",                                            # V2 (29B)
            "http://192.168.1.42:8765/1234abcd/ios.mobileconfig",                       # V3 (51B)
            "http://192.168.100.200:8765/a1b2c3d4/ios-debloat.mobileconfig",            # V4 (62B)
            "http://192.168.100.200:8765/a1b2c3d4e5f6/" + ("a" * 50) + ".mobileconfig", # V5 (~97B)
            "http://192.168.100.200:8765/a1b2c3d4/" + ("b" * 80) + ".mobileconfig",     # V6 (~123B)
            "http://192.168.100.200:8765/a1b2c3d4/" + ("c" * 100) + ".mobileconfig",    # V7 (~143B)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            paths: list[Path] = []
            for idx, payload in enumerate(payloads):
                png = _matrix_to_png(encode_qr(payload), scale=6, quiet=4)
                p = Path(tmp) / f"qr_{idx}.png"
                p.write_bytes(png)
                paths.append(p)
            decoded = _coreimage_decode_batch(paths)
            self.assertEqual(len(decoded), len(payloads))
            for expected, actual in zip(payloads, decoded):
                self.assertEqual(actual, f"OK:{expected}")


if __name__ == "__main__":
    unittest.main()
