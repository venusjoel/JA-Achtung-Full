"""Full-system smoke compare: the complete TT top with nothing bypassed.

Buttons go in through the real gamepad PMOD serial protocol, every RAM access
goes through the real QSPI PSRAM controller with the display streamer
competing for the bus, and the VGA timing paces the game. The final PSRAM
image is compared against the Python model — covering the gamepad decoder,
QSPI write path, and game/display arbitration that the fast direct-RAM tests
bypass. Slow, so it runs a short trace at the coarse 64x48 geometry.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

from tests.common.gamepad import (
    PMOD_CLK,
    PMOD_IDLE,
    P1_LEFT,
    P2_RIGHT,
    pmod_frame_bits,
    send_2x1_start_sequence,
    send_button_mask,
    send_pmod_frame,
)
from tests.common.maps import frame_bytes_1x1, frame_bytes_2x1, map_1x1, map_2x1, write_text_map
from tests.common.psram_bfm import SplitPsramBFM
from tests.common.traces import load_trace


CLK_PERIOD_NS = 20


@cocotb.test()
async def system_compare_trace(dut):
    target = os.environ["ACHTUNG_TARGET"]
    trace = load_trace(os.environ["ACHTUNG_TRACE"])
    frames = int(os.environ.get("ACHTUNG_FRAMES", trace.frames))
    frame_w = int(os.environ.get("ACHTUNG_FRAME_W", "64"))
    frame_h = int(os.environ.get("ACHTUNG_FRAME_H", "48"))
    idle_timeout_frames = int(os.environ.get("ACHTUNG_IDLE_TIMEOUT_FRAMES", "260"))
    out_map = Path(os.environ["ACHTUNG_HDL_MAP"])

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
        await send_2x1_start_sequence(dut)

    await wait_for_engine_idle(dut, timeout_frames=idle_timeout_frames)

    for frame in range(frames):
        await send_button_mask(dut, trace.button_at(frame))
        await RisingEdge(dut.u_dut.frame_start)
        if int(dut.u_dut.vblank.value) == 1:
            await FallingEdge(dut.u_dut.vblank)

    await ClockCycles(dut.clk, 20)

    if target == "1x1-minimal":
        raw = ram_bfm.model.read(0, frame_bytes_1x1(frame_w, frame_h))
        lines = map_1x1(raw, frame_w, frame_h)
    elif target == "1x2-working-game":
        raw = ram_bfm.model.read(0, frame_bytes_2x1(frame_w, frame_h))
        lines = map_2x1(raw, frame_w, frame_h)
    else:
        raise AssertionError(f"Unknown target {target!r}")

    write_text_map(lines, out_map, f"Achtung {target} {frame_w}x{frame_h}")


@cocotb.test()
async def absent_controller_is_masked(dut):
    """An unplugged all-ones controller half must not press any buttons."""
    target = os.environ["ACHTUNG_TARGET"]

    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = PMOD_IDLE
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 12)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    def decoded_buttons() -> dict[str, int]:
        if target == "1x1-minimal":
            return {
                "start": int(dut.u_dut.pad_start.value),
                "l": int(dut.u_dut.pad_l.value),
                "r": int(dut.u_dut.pad_r.value),
            }
        decoder = dut.u_dut.gamepad_inst
        return {
            name: int(getattr(decoder, f"{name}_reg").value)
            for name in (
                "select", "start", "up", "down", "left", "right",
                "a", "l", "r",
            )
        }

    def assert_all_released() -> None:
        decoded = decoded_buttons()
        assert all(value == 0 for value in decoded.values()), decoded

    # P2 absent, P1 connected and released: the all-ones P2 half is idle.
    await send_pmod_frame(dut, pmod_frame_bits(0, p2_present=False))
    assert_all_released()

    # Real P1 controls still pass while P2 remains absent. In the full game,
    # include A and Select because A drives boost and lobby colour locking.
    await send_pmod_frame(dut, pmod_frame_bits(
        P1_LEFT, p1_a=True, p1_start=True, p1_select=True,
        p2_present=False))
    decoded = decoded_buttons()
    if target == "1x1-minimal":
        assert decoded == {"start": 1, "l": 0b01, "r": 0}, decoded
    else:
        assert decoded == {
            "select": 0b01, "start": 0b01, "up": 0, "down": 0,
            "left": 0, "right": 0, "a": 0b01,
            "l": 0b01, "r": 0,
        }, decoded

    # Check the symmetric case and P2 passthrough as well.
    await send_pmod_frame(dut, pmod_frame_bits(0, p1_present=False))
    assert_all_released()
    await send_pmod_frame(dut, pmod_frame_bits(
        P2_RIGHT, p2_a=True, p2_start=True, p2_select=True,
        p1_present=False))
    decoded = decoded_buttons()
    if target == "1x1-minimal":
        assert decoded == {"start": 1, "l": 0, "r": 0b10}, decoded
    else:
        assert decoded == {
            "select": 0b10, "start": 0b10, "up": 0, "down": 0,
            "left": 0, "right": 0, "a": 0b10,
            "l": 0, "r": 0b10,
        }, decoded

        # D-pad steering is a separate path from L/R and must also reach the
        # gameplay OR gates; the normal trace helper intentionally uses only
        # shoulder buttons so one path cannot mask a broken other path.
        await send_pmod_frame(dut, pmod_frame_bits(
            0, p1_dpad_left=True, p2_dpad_right=True))
        decoded = decoded_buttons()
        assert decoded["left"] == 0b01 and decoded["l"] == 0, decoded
        assert decoded["right"] == 0b10 and decoded["r"] == 0, decoded
        assert int(dut.u_dut.p1_left.value) == 1
        assert int(dut.u_dut.p2_right.value) == 1

    # With both halves pulled high, every stored control must remain released.
    await send_pmod_frame(dut, pmod_frame_bits(
        0, p1_present=False, p2_present=False))
    assert_all_released()


@cocotb.test()
async def gamepad_clock_edge_uses_settled_sync_stage(dut):
    """The serial counter must not consume the metastability catcher stage."""
    target = os.environ["ACHTUNG_TARGET"]

    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0  # latch, serial clock, and data all low
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 12)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 4)

    counter = (dut.u_dut.pad_bit_count if target == "1x1-minimal"
               else dut.u_dut.gamepad_inst.bit_count)
    assert int(counter.value) == 0

    # Change the asynchronous pin halfway between system-clock edges. The
    # first two rising edges only fill the two-stage synchronizer; the third
    # edge is the earliest legal time for the decoder to consume the pulse.
    await FallingEdge(dut.clk)
    dut.ui_in.value = PMOD_CLK
    for cycle, expected in enumerate((0, 0, 1), start=1):
        await RisingEdge(dut.clk)
        await ReadOnly()
        got = int(counter.value)
        assert got == expected, (
            f"gamepad bit counter after synchronized edge cycle {cycle}: "
            f"expected {expected}, got {got}"
        )


async def wait_for_engine_idle(dut, timeout_frames: int) -> None:
    seen_frames = 0
    while seen_frames < timeout_frames:
        await RisingEdge(dut.clk)
        await ReadOnly()
        state = int(dut.u_dut.engine_inst.state.value)
        if int(dut.u_dut.frame_start.value) == 1:
            seen_frames += 1
        if (
            state == 2 and
            int(dut.u_dut.vblank.value) == 0 and
            int(dut.u_dut.frame_start.value) == 0
        ):
            await FallingEdge(dut.clk)
            return
    raise AssertionError(f"Timed out waiting for engine IDLE, state={int(dut.u_dut.engine_inst.state.value)}")
