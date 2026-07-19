"""Cocotb side of the 2x1 direct-RAM game-logic test.

Locks both players' colours and presses Start through the lobby ports, then
drives buttons, vblank, and frame_start straight from the JSON trace. The
framebuffer is a behavioral burst array; the final memory image is dumped as
a text map for comparison with the Python model.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

from tests.common.maps import frame_bytes_2x1, map_2x1, write_text_map
from tests.common.traces import (
    P1_BOOST,
    P1_LEFT,
    P1_RIGHT,
    P2_BOOST,
    P2_LEFT,
    P2_RIGHT,
    load_trace,
)


CLK_PERIOD_NS = 20
STATE_OVER = 1
STATE_IDLE = 2
SETTLED_STATES = (STATE_IDLE, STATE_OVER)

INPUT_PORTS = (
    "p1_left", "p1_right", "p2_left", "p2_right",
    "p1_boost", "p2_boost",
    "p1_menu_start", "p2_menu_start", "p1_menu_select", "p2_menu_select",
    "p1_pick_col", "p1_pick_col_inc", "p1_pick_row", "p1_pick_select",
    "p2_pick_col", "p2_pick_col_inc", "p2_pick_row", "p2_pick_select",
    "vblank", "frame_start",
)


async def wait_engine_settled(dut, timeout_cycles: int) -> int:
    elapsed = 0
    while elapsed < timeout_cycles:
        await ClockCycles(dut.clk, 8)
        elapsed += 8
        state = int(dut.u_engine.state.value)
        if state in SETTLED_STATES:
            return state
    raise AssertionError(
        f"Engine did not settle within {timeout_cycles} cycles, "
        f"state={int(dut.u_engine.state.value)}"
    )


async def wait_clear_done(dut, timeout_cycles: int) -> None:
    elapsed = 0
    while elapsed < timeout_cycles:
        await ClockCycles(dut.clk, 64)
        elapsed += 64
        if int(dut.u_engine.state.value) == STATE_IDLE:
            return
    raise AssertionError("Timed out waiting for the framebuffer clear after Start")


async def start_game_from_lobby(dut) -> None:
    # Lock a colour for both players (A press), then one Start press.
    dut.p1_pick_select.value = 1
    dut.p2_pick_select.value = 1
    await ClockCycles(dut.clk, 2)
    dut.p1_pick_select.value = 0
    dut.p2_pick_select.value = 0
    await ClockCycles(dut.clk, 2)
    assert int(dut.p1_selected.value) == 1
    assert int(dut.p2_selected.value) == 1

    dut.p1_menu_start.value = 1
    await ClockCycles(dut.clk, 2)
    dut.p1_menu_start.value = 0
    await ClockCycles(dut.clk, 2)


async def reset_to_lobby(dut) -> None:
    for name in INPUT_PORTS:
        getattr(dut, name).value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 8)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 4)


@cocotb.test()
async def game_direct_trace(dut):
    trace = load_trace(os.environ["ACHTUNG_TRACE"])
    frames = int(os.environ.get("ACHTUNG_FRAMES", trace.frames))
    frame_w = int(os.environ["ACHTUNG_FRAME_W"])
    frame_h = int(os.environ["ACHTUNG_FRAME_H"])
    out_map = Path(os.environ["ACHTUNG_HDL_MAP"])

    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_to_lobby(dut)

    await start_game_from_lobby(dut)
    await wait_clear_done(dut, timeout_cycles=200_000)

    for frame in range(frames):
        mask = trace.button_at(frame)
        dut.p1_left.value = 1 if mask & P1_LEFT else 0
        dut.p1_right.value = 1 if mask & P1_RIGHT else 0
        dut.p2_left.value = 1 if mask & P2_LEFT else 0
        dut.p2_right.value = 1 if mask & P2_RIGHT else 0
        dut.p1_boost.value = 1 if mask & P1_BOOST else 0
        dut.p2_boost.value = 1 if mask & P2_BOOST else 0

        dut.vblank.value = 1
        dut.frame_start.value = 1
        await RisingEdge(dut.clk)
        dut.frame_start.value = 0

        await wait_engine_settled(dut, timeout_cycles=512)

        dut.vblank.value = 0
        await ClockCycles(dut.clk, 2)

    if frames >= trace.frames and trace.expected.get("death_player"):
        assert int(dut.game_over.value) == 1, (
            "Expected a terminal collision, but the 1x2 RTL is not game-over")
        for signal_name in ("p1_alive", "p2_alive"):
            if signal_name in trace.expected:
                actual = bool(int(getattr(dut.u_engine, signal_name).value))
                expected = bool(trace.expected[signal_name])
                assert actual == expected, (
                    f"RTL {signal_name}: expected {expected}, got {actual}")

    total_bytes = frame_bytes_2x1(frame_w, frame_h)
    raw = bytearray(int(dut.mem[index].value) & 0xFF for index in range(total_bytes))
    write_text_map(map_2x1(raw, frame_w, frame_h), out_map,
                   f"Achtung 1x2-working-game {frame_w}x{frame_h}")


@cocotb.test()
async def simultaneous_lobby_claim_keeps_colors_distinct(dut):
    """A same-cycle claim of one free color must confirm only one player."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_to_lobby(dut)

    # Move P2 left from the default color 1 onto P1's color 0.
    dut.p2_pick_col_inc.value = 0
    dut.p2_pick_col.value = 1
    await ClockCycles(dut.clk, 2)
    dut.p2_pick_col.value = 0
    await ClockCycles(dut.clk, 2)
    assert int(dut.p1_pick_id.value) == 0
    assert int(dut.p2_pick_id.value) == 0

    dut.p1_pick_select.value = 1
    dut.p2_pick_select.value = 1
    await ClockCycles(dut.clk, 2)
    dut.p1_pick_select.value = 0
    dut.p2_pick_select.value = 0
    await ClockCycles(dut.clk, 2)
    assert int(dut.p1_selected.value) == 1
    assert int(dut.p2_selected.value) == 0
    assert int(dut.p1_color_id.value) == 0
    assert int(dut.p2_color_id.value) == 1

    # P2 can immediately move to the next free color and confirm it.
    dut.p2_pick_col_inc.value = 1
    dut.p2_pick_col.value = 1
    await ClockCycles(dut.clk, 2)
    dut.p2_pick_col.value = 0
    await ClockCycles(dut.clk, 2)
    dut.p2_pick_select.value = 1
    await ClockCycles(dut.clk, 2)
    dut.p2_pick_select.value = 0
    await ClockCycles(dut.clk, 2)
    assert int(dut.p2_selected.value) == 1
    assert int(dut.p1_color_id.value) != int(dut.p2_color_id.value)
