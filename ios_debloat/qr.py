"""Pure-Python ISO/IEC 18004 QR Code encoder & terminal Unicode renderer."""
from __future__ import annotations

from typing import Sequence

# GF(256) with primitive polynomial 0x11d (x^8 + x^4 + x^3 + x^2 + 1)
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]

# ECC Level L specifications for QR Versions 1..8
# (version, size, total_data_cw, ec_cw_per_block, num_blocks_g1, data_cw_g1, num_blocks_g2, data_cw_g2, align_centers)
_VERSION_SPECS: tuple[tuple[int, int, int, int, int, int, int, int, tuple[int, ...]], ...] = (
    (1, 21, 19, 7, 1, 19, 0, 0, ()),
    (2, 25, 34, 10, 1, 34, 0, 0, (6, 18)),
    (3, 29, 55, 15, 1, 55, 0, 0, (6, 22)),
    (4, 33, 80, 20, 1, 80, 0, 0, (6, 26)),
    (5, 37, 108, 26, 1, 108, 0, 0, (6, 30)),
    (6, 41, 136, 18, 2, 68, 0, 0, (6, 34)),
    (7, 45, 156, 20, 2, 78, 0, 0, (6, 22, 38)),
    (8, 49, 194, 24, 2, 97, 0, 0, (6, 24, 42)),
)

_REMAINDER_BITS = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0}


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        root = _GF_EXP[i]
        nxt = [0] * (len(poly) + 1)
        for j, coeff in enumerate(poly):
            nxt[j] ^= coeff
            nxt[j + 1] ^= _gf_mul(coeff, root)
        poly = nxt
    return poly


def _rs_remainder(data: Sequence[int], ec_len: int) -> list[int]:
    gen = _rs_generator(ec_len)
    buf = list(data) + [0] * ec_len
    for i in range(len(data)):
        factor = buf[i]
        if factor != 0:
            for j in range(1, len(gen)):
                buf[i + j] ^= _gf_mul(gen[j], factor)
    return buf[len(data) :]


def _select_version(byte_len: int) -> tuple[int, int, int, int, int, int, int, int, tuple[int, ...]]:
    for spec in _VERSION_SPECS:
        data_cw = spec[2]
        # Byte mode overhead: 4-bit mode + 8-bit count = 12 bits; + up to 4-bit terminator = 2 bytes max
        if byte_len + 2 <= data_cw:
            return spec
    max_cap = _VERSION_SPECS[-1][2] - 2
    raise ValueError(f"QR payload too long ({byte_len} bytes; max supported is {max_cap} bytes)")


def _encode_data_codewords(payload: bytes, total_data_cw: int) -> list[int]:
    bits: list[int] = []

    def push_bits(val: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
            bits.append((val >> shift) & 1)

    push_bits(0b0100, 4)  # Byte mode (Versions 1..9 use 8-bit count)
    push_bits(len(payload), 8)
    for b in payload:
        push_bits(b, 8)

    cap_bits = total_data_cw * 8
    term_len = min(4, cap_bits - len(bits))
    push_bits(0, term_len)
    while len(bits) % 8 != 0:
        bits.append(0)

    codewords: list[int] = []
    for i in range(0, len(bits), 8):
        byte = 0
        for b in bits[i : i + 8]:
            byte = (byte << 1) | b
        codewords.append(byte)

    pad_bytes = (0xEC, 0x11)
    pad_idx = 0
    while len(codewords) < total_data_cw:
        codewords.append(pad_bytes[pad_idx % 2])
        pad_idx += 1
    return codewords


def _interleave_blocks(
    data_cw: list[int],
    ec_len: int,
    g1_blocks: int,
    g1_len: int,
    g2_blocks: int,
    g2_len: int,
) -> list[int]:
    data_blocks: list[list[int]] = []
    ec_blocks: list[list[int]] = []
    offset = 0
    for _ in range(g1_blocks):
        blk = data_cw[offset : offset + g1_len]
        offset += g1_len
        data_blocks.append(blk)
        ec_blocks.append(_rs_remainder(blk, ec_len))
    for _ in range(g2_blocks):
        blk = data_cw[offset : offset + g2_len]
        offset += g2_len
        data_blocks.append(blk)
        ec_blocks.append(_rs_remainder(blk, ec_len))

    result: list[int] = []
    max_data_len = max(len(b) for b in data_blocks)
    for i in range(max_data_len):
        for blk in data_blocks:
            if i < len(blk):
                result.append(blk[i])
    for i in range(ec_len):
        for ec in ec_blocks:
            result.append(ec[i])
    return result


def _format_bits(mask: int) -> int:
    # ECC Level L = 01
    data = (0b01 << 3) | mask
    rem = data << 10
    gen = 0b10100110111
    for shift in range(4, -1, -1):
        if rem & (1 << (shift + 10)):
            rem ^= gen << shift
    return ((data << 10) | rem) ^ 0b101010000010010


def _version_bits(version: int) -> int:
    rem = version << 12
    gen = 0b1111100100101
    for shift in range(5, -1, -1):
        if rem & (1 << (shift + 12)):
            rem ^= gen << shift
    return (version << 12) | rem


def _build_base_matrix(version: int, size: int, align: tuple[int, ...]) -> tuple[list[list[bool]], list[list[bool]]]:
    grid = [[False] * size for _ in range(size)]
    func = [[False] * size for _ in range(size)]

    def set_fn(r: int, c: int, val: bool) -> None:
        if 0 <= r < size and 0 <= c < size:
            grid[r][c] = val
            func[r][c] = True

    def draw_finder(top: int, left: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = top + dr, left + dc
                if not (0 <= r < size and 0 <= c < size):
                    continue
                if dr in (-1, 7) or dc in (-1, 7):
                    set_fn(r, c, False)
                else:
                    is_dark = (
                        dr in (0, 6)
                        or dc in (0, 6)
                        or (2 <= dr <= 4 and 2 <= dc <= 4)
                    )
                    set_fn(r, c, is_dark)

    draw_finder(0, 0)
    draw_finder(0, size - 7)
    draw_finder(size - 7, 0)

    # Timing patterns
    for i in range(8, size - 8):
        bit = (i % 2) == 0
        set_fn(6, i, bit)
        set_fn(i, 6, bit)

    # Alignment patterns
    if align:
        for cr in align:
            for cc in align:
                # Skip corners overlapping finder patterns
                if (cr <= 8 and cc <= 8) or (cr <= 8 and cc >= size - 9) or (cr >= size - 9 and cc <= 8):
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        is_dark = abs(dr) == 2 or abs(dc) == 2 or (dr == 0 and dc == 0)
                        set_fn(cr + dr, cc + dc, is_dark)

    # Dark module
    set_fn(4 * version + 9, 8, True)

    # Reserve format info cells
    for i in range(9):
        if i != 6:
            func[8][i] = True
            func[i][8] = True
    for i in range(size - 8, size):
        func[8][i] = True
    for i in range(size - 7, size):
        func[i][8] = True

    # Version info blocks (versions >= 7)
    if version >= 7:
        vbits = _version_bits(version)
        for idx in range(18):
            bit = bool((vbits >> idx) & 1)
            r = idx // 3
            c = size - 11 + (idx % 3)
            set_fn(r, c, bit)
            set_fn(c, r, bit)

    return grid, func


def _place_codewords(
    grid: list[list[bool]],
    func: list[list[bool]],
    codewords: list[int],
    remainder_bits: int,
) -> None:
    size = len(grid)
    bits: list[bool] = []
    for cw in codewords:
        for shift in range(7, -1, -1):
            bits.append(bool((cw >> shift) & 1))
    bits.extend([False] * remainder_bits)

    bit_idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        row_range = range(size - 1, -1, -1) if upward else range(size)
        for row in row_range:
            for dc in (0, -1):
                c = col + dc
                if not func[row][c]:
                    if bit_idx < len(bits):
                        grid[row][c] = bits[bit_idx]
                        bit_idx += 1
        col -= 2
        upward = not upward


def _mask_predicate(mask: int, r: int, c: int) -> bool:
    if mask == 0:
        return (r + c) % 2 == 0
    if mask == 1:
        return r % 2 == 0
    if mask == 2:
        return c % 3 == 0
    if mask == 3:
        return (r + c) % 3 == 0
    if mask == 4:
        return (r // 2 + c // 3) % 2 == 0
    if mask == 5:
        return ((r * c) % 2) + ((r * c) % 3) == 0
    if mask == 6:
        return (((r * c) % 2) + ((r * c) % 3)) % 2 == 0
    return (((r + c) % 2) + ((r * c) % 3)) % 2 == 0


def _apply_format_bits(grid: list[list[bool]], mask: int) -> None:
    size = len(grid)
    fmt = _format_bits(mask)

    def bit(pos: int) -> bool:
        return bool((fmt >> pos) & 1)

    # Top-left format strip
    tl_horizontal = (0, 1, 2, 3, 4, 5, 7, 8)
    for i, col in enumerate(tl_horizontal):
        grid[8][col] = bit(14 - i)
    tl_vertical = (7, 5, 4, 3, 2, 1, 0)
    for i, row in enumerate(tl_vertical):
        grid[row][8] = bit(6 - i)

    # Bottom-left vertical (bits 14..8) & top-right horizontal (bits 7..0)
    for i in range(7):
        grid[size - 1 - i][8] = bit(14 - i)
    for i in range(8):
        grid[8][size - 8 + i] = bit(7 - i)


def _penalty(grid: list[list[bool]]) -> int:
    size = len(grid)
    score = 0

    # N1: 5+ consecutive same-colored modules in row or column
    for r in range(size):
        run = 1
        for c in range(1, size):
            if grid[r][c] == grid[r][c - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)

    for c in range(size):
        run = 1
        for r in range(1, size):
            if grid[r][c] == grid[r - 1][c]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)

    # N2: 2x2 same-colored blocks
    for r in range(size - 1):
        for c in range(size - 1):
            v = grid[r][c]
            if v == grid[r][c + 1] == grid[r + 1][c] == grid[r + 1][c + 1]:
                score += 3

    # N3: finder-like patterns 10111010000 or 00001011101
    pat_a = (True, False, True, True, True, False, True, False, False, False, False)
    pat_b = (False, False, False, False, True, False, True, True, True, False, True)
    for r in range(size):
        row = grid[r]
        for c in range(size - 10):
            seg = tuple(row[c : c + 11])
            if seg == pat_a or seg == pat_b:
                score += 40
    for c in range(size):
        for r in range(size - 10):
            seg = tuple(grid[r + k][c] for k in range(11))
            if seg == pat_a or seg == pat_b:
                score += 40

    # N4: dark module ratio deviation from 50%
    dark = sum(1 for row in grid for cell in row if cell)
    total = size * size
    pct = (dark * 100) // total
    prev5 = (pct // 5) * 5
    next5 = prev5 + 5
    score += min(abs(prev5 - 50) // 5, abs(next5 - 50) // 5) * 10
    return score


def encode_qr(text: str) -> list[list[bool]]:
    """Encode `text` as a QR matrix (`True` = dark module) using ECC Level L."""
    payload = text.encode("utf-8")
    version, size, total_data_cw, ec_len, g1_b, g1_len, g2_b, g2_len, align = _select_version(len(payload))
    data_cw = _encode_data_codewords(payload, total_data_cw)
    final_cw = _interleave_blocks(data_cw, ec_len, g1_b, g1_len, g2_b, g2_len)
    base_grid, func = _build_base_matrix(version, size, align)
    _place_codewords(base_grid, func, final_cw, _REMAINDER_BITS[version])

    best_grid: list[list[bool]] | None = None
    best_score = 10**9
    for mask in range(8):
        cand = [row[:] for row in base_grid]
        for r in range(size):
            for c in range(size):
                if not func[r][c] and _mask_predicate(mask, r, c):
                    cand[r][c] = not cand[r][c]
        _apply_format_bits(cand, mask)
        sc = _penalty(cand)
        if sc < best_score:
            best_score = sc
            best_grid = cand

    assert best_grid is not None
    return best_grid


def render_terminal(text: str, *, quiet: int = 2, invert: bool = True) -> str:
    """Render `text` as a compact Unicode half-block QR code for terminals.

    With `invert=True` (default for dark terminal themes), light quiet-zone/white
    modules are drawn with bright foreground blocks (`█`/`▀`/`▄`) and dark
    modules are empty terminal background spaces (` `), producing high contrast
    for the iOS Camera app. Set `invert=False` on light-background terminals.
    """
    matrix = encode_qr(text)
    n = len(matrix)
    padded_size = n + 2 * quiet

    def is_dark(r: int, c: int) -> bool:
        mr = r - quiet
        mc = c - quiet
        if 0 <= mr < n and 0 <= mc < n:
            return matrix[mr][mc]
        return False

    def cell_on(r: int, c: int) -> bool:
        dark = is_dark(r, c)
        return (not dark) if invert else dark

    lines: list[str] = []
    for r in range(0, padded_size, 2):
        chars: list[str] = []
        has_bottom = (r + 1) < padded_size
        for c in range(padded_size):
            top = cell_on(r, c)
            bot = cell_on(r + 1, c) if has_bottom else invert
            if top and bot:
                chars.append("█")
            elif top and not bot:
                chars.append("▀")
            elif not top and bot:
                chars.append("▄")
            else:
                chars.append(" ")
        lines.append("".join(chars))
    return "\n".join(lines)


def write_ppm(matrix: list[list[bool]], *, scale: int = 8, quiet: int = 4) -> bytes:
    """Render QR matrix into a binary P6 PPM image (light background, dark modules)."""
    n = len(matrix)
    dim = (n + 2 * quiet) * scale
    header = f"P6\n{dim} {dim}\n255\n".encode("ascii")
    black = b"\x00\x00\x00"
    white = b"\xff\xff\xff"
    rows: list[bytes] = []
    for pr in range(dim):
        mr = (pr // scale) - quiet
        line = bytearray()
        for pc in range(dim):
            mc = (pc // scale) - quiet
            dark = 0 <= mr < n and 0 <= mc < n and matrix[mr][mc]
            line.extend(black if dark else white)
        rows.append(bytes(line))
    return header + b"".join(rows)
