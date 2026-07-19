# SPDX-FileCopyrightText: © 2026 Joel Kaplan and Amit Elmaliach
# SPDX-License-Identifier: Apache-2.0

"""Pin-level smoke test for tt_um_ja_achtung_1x2 (JA Achtung Full).

Drives only the chip pins so the same test runs on RTL and on the gate-level
netlist: after reset the design must produce VGA sync activity on uo_out and
QSPI PSRAM activity on uio_out. The full game-logic test suites live in
"Game Simulation/tests/" and run in their own workflow.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

# Gamepad PMOD idle levels: latch (ui[4]) and clock (ui[5]) high, no data.
PMOD_IDLE = 0b0011_0000

HSYNC_BIT = 7  # uo_out[7]
VSYNC_BIT = 3  # uo_out[3]
QSPI_SCK_BIT = 3   # uio_out[3]
QSPI_CSN_BIT = 6   # uio_out[6]


def safe_bit(signal, bit):
    text = str(signal.value).lower()
    char = text[len(text) - 1 - bit]
    return int(char) if char in "01" else None


def strict_value(signal):
    """Return a fully known binary signal value or fail with its exact state."""
    text = str(signal.value).lower()
    if any(char not in "01" for char in text):
        raise AssertionError(f"unknown logic value: {signal.value}")
    return int(text, 2)


async def wait_bit_values(dut, signal, bit, timeout_cycles, step=64):
    """Return once the bit has been seen both low and high."""
    seen = set()
    elapsed = 0
    while elapsed < timeout_cycles:
        value = safe_bit(signal, bit)
        if value is not None:
            seen.add(value)
        if seen == {0, 1}:
            return
        await ClockCycles(dut.clk, step)
        elapsed += step
    raise AssertionError(
        f"bit {bit} stuck, saw only {seen} after {timeout_cycles} cycles")


async def wait_qspi_activity(dut, timeout_cycles):
    """Observe both SCK levels while PSRAM CS# is actively asserted."""
    active_sck = set()
    for _ in range(timeout_cycles):
        sck = safe_bit(dut.uio_out, QSPI_SCK_BIT)
        csn = safe_bit(dut.uio_out, QSPI_CSN_BIT)
        if csn == 0 and sck is not None:
            active_sck.add(sck)
        if active_sck == {0, 1}:
            return
        await ClockCycles(dut.clk, 1)
    raise AssertionError(
        "QSPI SCK did not toggle under active CS# after "
        f"{timeout_cycles} cycles: active SCK values={active_sck}")


@cocotb.test()
async def test_project(dut):
    dut._log.info("Start")

    # 50 MHz system clock, same as the real board.
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = PMOD_IDLE
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 20)
    # Physical reset contract for APS6404L power-up: all external CS# pins
    # high, SCK low, and all four SIO pins actively driven low.  Requiring the
    # complete vectors also rejects hidden X/Z values in RTL and GL tests.
    assert strict_value(dut.uio_out) == 0xC1, dut.uio_out.value
    assert strict_value(dut.uio_oe) == 0xFF, dut.uio_oe.value
    # Avoid releasing asynchronous reset on the same simulator time-step as a
    # rising clock edge. That creates a recovery/removal race in SDF-free gate
    # simulation even though reset release is synchronous on the real board.
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    # Fixed-direction uio pins: PSRAM-B CS# (7), active PSRAM CS# (6), SCK
    # (3), and flash CS# (0) are always outputs.  The four QSPI data enables
    # are dynamic after reset.
    for bit in (7, 6, 3, 0):
        assert safe_bit(dut.uio_oe, bit) == 1, (
            f"uio_oe[{bit}] is not a known output: {dut.uio_oe.value}")

    # QSPI PSRAM init: serial clock must toggle and chip-select must assert.
    await wait_qspi_activity(dut, timeout_cycles=8_000)
    dut._log.info("QSPI PSRAM activity OK")

    # HSYNC is quick enough to prove in both RTL and gate-level simulation.
    # The RTL build uses a reduced 64x48 frame, so it also proves VSYNC without
    # making the hosted gate-level smoke simulate a full 640x480 frame.
    await wait_bit_values(dut, dut.uo_out, HSYNC_BIT, timeout_cycles=2_000, step=8)
    dut._log.info("HSYNC OK")

    if int(dut.gl_test_mode.value) == 0:
        await wait_bit_values(dut, dut.uo_out, VSYNC_BIT, timeout_cycles=40_000, step=16)
        dut._log.info("VSYNC OK")

    dut._log.info("Smoke test passed")
