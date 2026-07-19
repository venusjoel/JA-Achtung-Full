"""Full VGA read-path test for the standalone 1x2 project.

Preloads a lined test picture straight into the PSRAM model, then lets the
real top-level design stream it out: QSPI PSRAM controller -> display
streamer -> VGA sync. Every visible pixel of one full frame is captured from
the current framebuffer stream and the physical RGB pins. Both are compared
with the expected picture, so burst/address errors and RGB-versus-sync phase
errors show up at an exact (x, y).

The gameplay engine is quiesced first (forced game-over for the 1x1 build,
forced game-over for the 2x1 build) so only the display path touches
PSRAM while the frame is captured.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge, Timer

from tests.common.gamepad import PMOD_IDLE
from tests.common.maps import (
    frame_bytes_1x1,
    frame_bytes_2x1,
    row_stride_1x1,
    write_text_map,
)
from tests.common.psram_bfm import SplitPsramBFM


CLK_PERIOD_NS = 20
STATE_1X1_OVER = 1
STATE_2X1_OVER = 1
STATE_2X1_IDLE = 2


def pattern_bit_1x1(cell_x: int, y: int) -> int:
    # Plaid of 8-pixel-wide columns and 4-row-tall lines (1 bit per 4px cell).
    return ((cell_x >> 1) ^ (y >> 2)) & 1


def pattern_pixel_2x1(x: int, y: int) -> int:
    # Checkered 4x4 blocks alternating between player colors 1 and 2.
    return 1 if ((x >> 2) ^ (y >> 2)) & 1 == 0 else 2


def pattern_bytes_1x1(width: int, height: int) -> bytearray:
    stride = row_stride_1x1(width)
    data = bytearray(frame_bytes_1x1(width, height))
    for y in range(height):
        for cell_x in range(width // 4):
            if pattern_bit_1x1(cell_x, y):
                data[y * stride + (cell_x >> 3)] |= 1 << (cell_x & 0x7)
    return data


def pattern_bytes_2x1(width: int, height: int) -> bytearray:
    data = bytearray(frame_bytes_2x1(width, height))
    for y in range(height):
        for x in range(width):
            pixel_index = y * width + x
            shift = (pixel_index & 0x3) << 1
            data[pixel_index >> 2] |= pattern_pixel_2x1(x, y) << shift
    return data


def expected_lines(target: str, width: int, height: int) -> list[str]:
    if target == "1x1-minimal":
        return ["".join("#" if pattern_bit_1x1(x >> 2, y) else "."
                        for x in range(width)) for y in range(height)]
    chars = ".12?"
    return ["".join(chars[pattern_pixel_2x1(x, y)] for x in range(width))
            for y in range(height)]


def captured_lines(target: str, captured: list[list[int]]) -> list[str]:
    if target == "1x1-minimal":
        return ["".join("#" if pixel else "." for pixel in row) for row in captured]
    chars = ".12?"
    return ["".join(chars[pixel & 0x3] for pixel in row) for row in captured]


def _debug_int(value) -> int:
    text = str(value).lower()
    if any(ch not in "01" for ch in text):
        return 0
    return int(text, 2)


def _strict_int(value, label: str) -> int:
    text = str(value).lower()
    if any(ch not in "01" for ch in text):
        raise AssertionError(f"{label} contains unknown logic: {value}")
    return int(text, 2)


def _pin_rgb(uo: int) -> int:
    # VGA PMOD order is R,G,B in pins 0,1,2, while the logical RGB value uses
    # R,G,B as bits 2,1,0.
    return (((uo >> 0) & 1) << 2) | (((uo >> 1) & 1) << 1) | ((uo >> 2) & 1)


def _expected_pin_rgb(target: str, x: int, y: int, width: int, height: int) -> int:
    if target == "1x1-minimal":
        return 0b111 if pattern_bit_1x1(x >> 2, y) else 0b000
    wall_t = 1 if width == 64 else 8
    if x < wall_t or x >= width - wall_t or y < wall_t or y >= height - wall_t:
        return 0b111
    return 0b100 if pattern_pixel_2x1(x, y) == 1 else 0b010


async def check_2x1_gap_head_marker(dut, width: int, height: int) -> None:
    """Prove the display marker follows the canonical 32-pixel gap window."""
    top = dut.u_dut
    engine = top.engine_inst

    # Put both live players in active gameplay without waiting through the
    # lobby and framebuffer clear.  This is a display-path unit check; the
    # normal game suites independently exercise the real lobby/game flow.
    engine.state.value = STATE_2X1_IDLE
    engine.p1_alive.value = 1
    engine.p2_alive.value = 1
    engine.p1_gap_counter.value = 0
    engine.p2_gap_counter.value = 0
    await Timer(1, unit="ns")

    # The HDL bit decode must be false for 0..223 and true for exactly the
    # final 32 counts, 224..255, matching Curved2x1Model._gap_active().
    for counter in range(256):
        engine.p1_gap_counter.value = counter
        await Timer(1, unit="ns")
        expected = 1 if counter >= 224 else 0
        actual = _strict_int(top.p1_head_on.value, "p1_head_on")
        assert actual == expected, (
            f"p1 head/gap decode mismatch at counter {counter}: "
            f"expected {expected}, got {actual}"
        )

    # Find a stable interior display pixel, then place both heads there.  The
    # 2x2 marker compares coordinate upper bits, so the current pixel must be
    # covered regardless of whether its x/y coordinates are odd or even.
    wall_t = 1 if width == 64 else 8
    for _ in range(100_000):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        x = _strict_int(top.h_count.value, "h_count")
        y = _strict_int(top.v_count.value, "v_count")
        if (
            _strict_int(top.active_video.value, "active_video") and
            wall_t + 2 <= x < width - wall_t - 2 and
            wall_t + 2 <= y < height - wall_t - 2
        ):
            break
    else:
        raise AssertionError("Timed out waiting for an interior VGA pixel")

    engine.p1_x_fp.value = x << 6
    engine.p1_y_fp.value = y << 6
    engine.p2_x_fp.value = x << 6
    engine.p2_y_fp.value = y << 6

    # P1 alone in a gap produces player-color code 1.
    engine.p1_gap_counter.value = 224
    engine.p2_gap_counter.value = 0
    await Timer(1, unit="ns")
    assert _strict_int(top.head_select_p2.value, "head_select_p2") == 0
    assert _strict_int(top.head_marker_px.value, "head_marker_px") == 1
    assert _strict_int(top.pixel_color.value, "pixel_color") == 1

    # P2 alone in a gap produces player-color code 2.
    engine.p1_gap_counter.value = 0
    engine.p2_gap_counter.value = 224
    await Timer(1, unit="ns")
    assert _strict_int(top.head_select_p2.value, "head_select_p2") == 1
    assert _strict_int(top.head_marker_px.value, "head_marker_px") == 1
    assert _strict_int(top.pixel_color.value, "pixel_color") == 2

    # When both players are in gaps, the existing once-per-frame phase bit
    # alternates which player's shared marker color is displayed.
    engine.p1_gap_counter.value = 224
    engine.p2_gap_counter.value = 224
    top.boost_flash_phase.value = 0
    await Timer(1, unit="ns")
    assert _strict_int(top.head_select_p2.value, "head_select_p2") == 0
    assert _strict_int(top.pixel_color.value, "pixel_color") == 1
    top.boost_flash_phase.value = 1
    await Timer(1, unit="ns")
    assert _strict_int(top.head_select_p2.value, "head_select_p2") == 1
    assert _strict_int(top.pixel_color.value, "pixel_color") == 2

    dut._log.info("1x2 gap/head marker matched the 32-of-256 gap contract")


async def _debug_monitor(dut):
    top = dut.u_dut
    disp = top.disp_inst
    prev = None
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        state = (
            _debug_int(top.vblank.value),
            _debug_int(top.v_count.value),
            _debug_int(disp.disp_req.value),
            _debug_int(disp.disp_ack.value),
            _debug_int(disp.display_shift_valid.value),
            _debug_int(disp.next_burst_valid.value),
            _debug_int(disp.next_fetch_burst.value),
        )
        if state != prev:
            dut._log.info(
                "DBG vblank=%d v=%d req=%d ack=%d shift_valid=%d next_valid=%d fetch=%d",
                *state)
            prev = state
        if state[1] == 0 and _debug_int(top.pixel_tick.value):
            dut._log.info(
                "PIX v=%d h=%d act=%d occ=%d shift=%08x",
                state[1], _debug_int(top.h_count.value),
                _debug_int(top.active_video.value),
                _debug_int(top.pixel_occupied.value),
                _debug_int(disp.display_shift.value))


async def capture_frame(
    dut, pixel_signal, target: str, width: int, height: int, rows: int
) -> list[list[int]]:
    top = dut.u_dut

    if os.environ.get("ACHTUNG_VGA_DEBUG"):
        cocotb.start_soon(_debug_monitor(dut))

    # Start on a clean frame boundary. frame_start (vblank rising edge)
    # rewinds the streamer, so the frame right after the next vblank is the
    # first one guaranteed to be fetched entirely from the preloaded picture.
    await RisingEdge(top.vblank)
    await FallingEdge(top.vblank)

    captured = [[0] * width for _ in range(rows)]
    seen = 0
    total = width * rows

    def capture_current_pixel() -> bool:
        nonlocal seen
        active = _strict_int(top.active_video.value, "active_video")
        x = _strict_int(top.h_count.value, "h_count")
        y = _strict_int(top.v_count.value, "v_count")
        if not active or x >= width or y >= rows:
            return False

        captured[y][x] = _strict_int(pixel_signal.value, "pixel signal")
        uo = _strict_int(dut.uo_out.value, "uo_out")
        assert ((uo >> 7) & 1) == _strict_int(top.hsync.value, "hsync"), (
            "uo_out[7] != hsync"
        )
        assert ((uo >> 3) & 1) == _strict_int(top.vsync.value, "vsync"), (
            "uo_out[3] != vsync"
        )
        for low_bit, high_bit in ((0, 4), (1, 5), (2, 6)):
            assert ((uo >> low_bit) & 1) == ((uo >> high_bit) & 1), (
                f"VGA ladder copies differ at ({x}, {y})"
            )
        got_rgb = _pin_rgb(uo)
        expected_rgb = _expected_pin_rgb(target, x, y, width, height)
        assert got_rgb == expected_rgb, (
            f"physical VGA RGB phase mismatch at ({x}, {y}): "
            f"expected {expected_rgb:03b}, got {got_rgb:03b}"
        )
        seen += 1
        return True

    # Falling vblank lands exactly on visible pixel (0, 0). Capture it now;
    # subsequent counter-advance edges are identifiable because pixel_div has
    # toggled back low after the nonblocking assignments settle.
    await ReadOnly()
    capture_current_pixel()

    while seen < total:
        await RisingEdge(dut.clk)
        await ReadOnly()
        if _strict_int(top.pixel_tick.value, "pixel_tick") == 0:
            capture_current_pixel()
    return captured


@cocotb.test()
async def vga_streams_lined_picture(dut):
    target = os.environ["ACHTUNG_TARGET"]
    frame_w = int(os.environ["ACHTUNG_FRAME_W"])
    frame_h = int(os.environ["ACHTUNG_FRAME_H"])
    rows_to_check = int(os.environ.get("ACHTUNG_VGA_ROWS", str(frame_h)))
    captured_map = Path(os.environ["ACHTUNG_VGA_MAP"])
    expected_map = Path(os.environ["ACHTUNG_VGA_EXPECTED_MAP"])

    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    ram_bfm = SplitPsramBFM(
        dut.u_dut.psram_inst,
        uio_in=dut.uio_in,
        uio_out=dut.uio_out,
        uio_oe=dut.uio_oe,
    )
    cocotb.start_soon(ram_bfm.run())
    cocotb.start_soon(ram_bfm.monitor_top_mapping(dut.clk))

    dut.ena.value = 1
    dut.ui_in.value = PMOD_IDLE
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 12)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    await ram_bfm.wait_for_qpi_ready(dut.clk)

    if target == "1x2-working-game":
        await check_2x1_gap_head_marker(dut, frame_w, frame_h)

    if target == "1x1-minimal":
        # Park the game in S_OVER so it stops clearing/painting the
        # framebuffer; with no Start press it stays there for the whole test.
        dut.u_dut.engine_inst.state.value = STATE_1X1_OVER
        # Let any in-flight clear write transaction drain before preloading.
        await ClockCycles(dut.clk, 120)
        picture = pattern_bytes_1x1(frame_w, frame_h)
        pixel_signal = dut.u_dut.pixel_occupied
    elif target == "1x2-working-game":
        # Park in game-over with a draw. This disables the lobby overlay and
        # makes the deliberate arena border white while leaving interior RGB
        # driven only by the framebuffer colors under test.
        dut.u_dut.engine_inst.state.value = STATE_2X1_OVER
        dut.u_dut.engine_inst.p1_alive.value = 0
        dut.u_dut.engine_inst.p2_alive.value = 0
        await ClockCycles(dut.clk, 8)
        picture = pattern_bytes_2x1(frame_w, frame_h)
        pixel_signal = dut.u_dut.pixel_color
    else:
        raise AssertionError(f"Unknown target {target!r}")

    ram_bfm.model.write(0, list(picture))

    if os.environ.get("ACHTUNG_VGA_DEBUG") and target == "1x1-minimal":
        dut._log.info("DBG engine state=%d mem[0:4]=%s",
                      int(dut.u_dut.engine_inst.state.value),
                      list(ram_bfm.model.read(0, 4)))

    captured = await capture_frame(
        dut, pixel_signal, target, frame_w, frame_h, rows_to_check
    )

    got_lines = captured_lines(target, captured)
    want_lines = expected_lines(target, frame_w, frame_h)
    write_text_map(got_lines, captured_map, f"VGA capture {target} {frame_w}x{frame_h}")
    write_text_map(want_lines, expected_map, f"VGA expected {target} {frame_w}x{frame_h}")

    for y in range(rows_to_check):
        if got_lines[y] != want_lines[y]:
            for x, (got, want) in enumerate(zip(got_lines[y], want_lines[y])):
                if got != want:
                    raise AssertionError(
                        f"VGA mismatch at ({x}, {y}): expected {want!r}, got {got!r}; "
                        f"see {captured_map}"
                    )

    dut._log.info("VGA picture matched: %dx%d pixels", frame_w, rows_to_check)
