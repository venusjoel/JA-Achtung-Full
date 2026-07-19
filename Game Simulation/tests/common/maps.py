from __future__ import annotations

from pathlib import Path


def frame_bytes_1x1(width: int, height: int) -> int:
    return row_stride_1x1(width) * height


def row_stride_1x1(width: int) -> int:
    if width == 64:
        return 4
    return width // 32


def frame_bytes_2x1(width: int, height: int) -> int:
    return (width * height) // 4


def map_1x1(raw: bytes | bytearray, width: int, height: int) -> list[str]:
    stride = row_stride_1x1(width)
    lines = []
    for y in range(height):
        chars = []
        row_base = y * stride
        for x in range(width):
            cell_x = x >> 2
            byte_index = row_base + (cell_x >> 3)
            bit_index = cell_x & 0x7
            occupied = (raw[byte_index] >> bit_index) & 0x1
            chars.append("#" if occupied else ".")
        lines.append("".join(chars))
    return lines


def map_2x1(raw: bytes | bytearray, width: int, height: int) -> list[str]:
    chars_by_value = ".12?"
    lines = []
    for y in range(height):
        chars = []
        for x in range(width):
            pixel_index = y * width + x
            byte_value = raw[pixel_index >> 2]
            pair_shift = (pixel_index & 0x3) << 1
            pixel = (byte_value >> pair_shift) & 0x3
            chars.append(chars_by_value[pixel])
        lines.append("".join(chars))
    return lines


def write_text_map(lines: list[str], path: str | Path, title: str) -> Path:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(title + "\n" + "\n".join(lines) + "\n")
    return out_path


def first_difference(left: str | Path, right: str | Path) -> str | None:
    left_lines = Path(left).read_text().splitlines()
    right_lines = Path(right).read_text().splitlines()
    max_len = max(len(left_lines), len(right_lines))
    for index in range(max_len):
        left_line = left_lines[index] if index < len(left_lines) else "<missing>"
        right_line = right_lines[index] if index < len(right_lines) else "<missing>"
        if left_line != right_line:
            return f"line {index + 1}: expected {left_line!r}, got {right_line!r}"
    return None
