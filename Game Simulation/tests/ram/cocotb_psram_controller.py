from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

from tests.common.psram_bfm import SimplePsram, SplitPsramBFM


CLK_PERIOD_NS = 20


@cocotb.test()
async def test_init_sequence(dut):
    _, bfm = await build_env(dut)
    # A cold APS6404L starts in SPI mode.  The two-clock QPI-exit preamble is
    # deliberately incomplete in SPI and must be discarded at CE# rising;
    # the normal serial reset/reset/quad sequence then establishes QPI.
    assert [entry["cmd"] for entry in bfm.command_log[:4]] == [None, 0x66, 0x99, 0x35]
    assert [entry["mode"] for entry in bfm.command_log[:4]] == ["SPI"] * 4
    assert bfm.command_log[0]["aborted"] is True
    assert bfm.model.mode == "QPI"


@cocotb.test()
async def test_init_sequence_from_warm_qpi(dut):
    _, bfm = await build_env(dut, initial_mode="QPI")
    assert [entry["cmd"] for entry in bfm.command_log[:4]] == [0xF5, 0x66, 0x99, 0x35]
    assert [entry["mode"] for entry in bfm.command_log[:4]] == ["QPI", "SPI", "SPI", "SPI"]
    assert all(not entry["aborted"] for entry in bfm.command_log[:4])
    assert bfm.model.mode == "QPI"


@cocotb.test()
async def test_write_read_round_trip(dut):
    target = os.environ["ACHTUNG_TARGET"]
    model, bfm = await build_env(dut)

    if target == "1x1-minimal":
        await write_1x1_byte(dut, 0x0123, 0xA5)
        got = await read_1x1(dut, 0x0123, byte_access=True)
        await wait_for_command_count(dut, bfm, 6)
        assert got[:1] == [0xA5]
        assert list(model.read(0x0123, 1)) == [0xA5]
    else:
        payload = [0x30 + index for index in range(8)]
        await write_burst(dut, 0x0240, payload)
        got = await read_burst(dut, 0x0240)
        await wait_for_command_count(dut, bfm, 6)
        assert got == payload

    assert any(entry["cmd"] == 0x38 for entry in bfm.command_log)
    assert any(entry["cmd"] == 0xEB for entry in bfm.command_log)


@cocotb.test()
async def test_display_read_width(dut):
    target = os.environ["ACHTUNG_TARGET"]
    model, bfm = await build_env(dut)

    if target == "1x1-minimal":
        expected = [0x10, 0x11, 0x12, 0x13]
        model.write(0x0400, expected)
        got = await read_1x1(dut, 0x0400, byte_access=False)
        await wait_for_command_count(dut, bfm, 5)
        assert got[:4] == expected
        read_txn = [entry for entry in bfm.command_log if entry["cmd"] == 0xEB][-1]
        assert read_txn["read_data"] == expected
    else:
        expected = [0x80 + index for index in range(8)]
        model.write(0x0400, expected)
        got = await read_burst(dut, 0x0400)
        await wait_for_command_count(dut, bfm, 5)
        assert got == expected
        read_txn = [entry for entry in bfm.command_log if entry["cmd"] == 0xEB][-1]
        assert read_txn["read_data"] == expected


async def build_env(dut, *, initial_mode: str = "SPI"):
    bfm = SplitPsramBFM(dut, model=SimplePsram(mode=initial_mode))
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    cocotb.start_soon(bfm.run())

    dut.rst_n.value = 0
    dut.i_we.value = 0
    dut.i_re.value = 0
    dut.i_addr.value = 0
    dut.i_wdata.value = 0
    if hasattr(dut, "i_byte"):
        dut.i_byte.value = 0
    dut.i_sio_in.value = 0
    await ClockCycles(dut.clk, 8)
    await ReadOnly()
    assert int(dut.o_ce_n.value) == 1
    assert int(dut.o_sclk.value) == 0
    assert int(dut.o_sio_out.value) == 0
    assert int(dut.o_sio_oe.value) == 0xF
    # Leave the read-only scheduler phase and release asynchronous reset away
    # from a rising clock edge, matching the top-level RTL/GL smoke test.
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await bfm.wait_for_qpi_ready(dut.clk)
    return bfm.model, bfm


async def wait_until_idle(dut):
    while int(dut.o_busy.value) == 1:
        await RisingEdge(dut.clk)


async def wait_until_busy(dut):
    while int(dut.o_busy.value) == 0:
        await RisingEdge(dut.clk)


async def wait_for_command_count(dut, bfm, expected: int, timeout_cycles: int = 200) -> None:
    for _ in range(timeout_cycles):
        if len(bfm.command_log) >= expected:
            return
        await RisingEdge(dut.clk)
    raise AssertionError(f"Timed out waiting for {expected} PSRAM commands, saw {len(bfm.command_log)}")


async def write_1x1_byte(dut, addr: int, value: int) -> None:
    await wait_until_idle(dut)
    dut.i_addr.value = addr
    dut.i_wdata.value = value & 0xFF
    dut.i_byte.value = 1
    dut.i_we.value = 1
    await wait_until_busy(dut)
    dut.i_we.value = 0
    await wait_until_idle(dut)


async def read_1x1(dut, addr: int, *, byte_access: bool) -> list[int]:
    await wait_until_idle(dut)
    dut.i_addr.value = addr
    dut.i_byte.value = 1 if byte_access else 0
    dut.i_re.value = 1
    await wait_until_busy(dut)
    dut.i_re.value = 0
    await RisingEdge(dut.o_valid)
    await ClockCycles(dut.clk, 2)
    width = len(dut.o_rdata) // 8
    return unpack_word(int(dut.o_rdata.value), width)


async def write_burst(dut, addr: int, data: list[int]) -> None:
    await wait_until_idle(dut)
    dut.i_addr.value = addr
    dut.i_wdata.value = pack_word(data)
    dut.i_we.value = 1
    await wait_until_busy(dut)
    dut.i_we.value = 0
    await wait_until_idle(dut)


async def read_burst(dut, addr: int) -> list[int]:
    await wait_until_idle(dut)
    dut.i_addr.value = addr
    dut.i_re.value = 1
    await wait_until_busy(dut)
    dut.i_re.value = 0
    await RisingEdge(dut.o_valid)
    await ClockCycles(dut.clk, 2)
    return unpack_word(int(dut.o_rdata.value), len(dut.o_rdata) // 8)


def pack_word(data: list[int]) -> int:
    value = 0
    for index, byte in enumerate(data):
        value |= (byte & 0xFF) << (index * 8)
    return value


def unpack_word(value: int, width: int) -> list[int]:
    return [(value >> (index * 8)) & 0xFF for index in range(width)]
