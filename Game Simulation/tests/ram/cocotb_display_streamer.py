from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer


CLK_PERIOD_NS = 20


@cocotb.test()
async def test_first_display_burst_pixels_and_next_read(dut):
    target = os.environ["ACHTUNG_TARGET"]

    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_streamer(dut)

    if target == "1x1-minimal":
        first_word = pack_bytes([0x5A, 0xC3, 0x00, 0x00])
        second_word = pack_bytes([0x0F, 0x00, 0x00, 0x00])
        await complete_display_read(dut, expected_addr=0, data_word=first_word)
        await complete_display_read(dut, expected_addr=4, data_word=second_word)

        for pixel_x in range(64):
            got = await tick_pixel_1x1(dut, pixel_x)
            expected = (first_word >> (pixel_x >> 2)) & 0x1
            assert got == expected, f"x={pixel_x}: got {got}, expected {expected}"
    elif target == "1x2-working-game":
        first_pixels = [(idx % 3) for idx in range(32)]
        second_pixels = [2 if idx & 1 else 1 for idx in range(32)]
        await complete_display_read(dut, expected_addr=0, data_word=pack_2bpp_pixels(first_pixels))
        await complete_display_read(dut, expected_addr=8, data_word=pack_2bpp_pixels(second_pixels))

        for pixel_x, expected in enumerate(first_pixels):
            got = await tick_pixel_2x1(dut, pixel_x)
            assert got == expected, f"x={pixel_x}: got {got}, expected {expected}"
    else:
        raise AssertionError(f"Unknown target {target!r}")


@cocotb.test()
async def test_frame_start_rewinds_fetch_address(dut):
    target = os.environ["ACHTUNG_TARGET"]
    burst_bytes = 4 if target == "1x1-minimal" else 8

    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_streamer(dut)

    await complete_display_read(dut, expected_addr=0, data_word=0)
    await complete_display_read(dut, expected_addr=burst_bytes, data_word=0)

    dut.frame_start.value = 1
    await RisingEdge(dut.clk)
    dut.frame_start.value = 0
    await ClockCycles(dut.clk, 1)

    await wait_for_disp_req(dut)
    assert int(dut.disp_addr.value) == 0


async def reset_streamer(dut) -> None:
    dut.rst_n.value = 0
    dut.pixel_tick.value = 0
    dut.pixel_idx.value = 0
    dut.active_video.value = 0
    dut.vblank.value = 0
    dut.frame_start.value = 0
    dut.disp_rdata.value = 0
    dut.disp_ack.value = 0
    await ClockCycles(dut.clk, 4)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def wait_for_disp_req(dut, timeout_cycles: int = 40) -> None:
    for _ in range(timeout_cycles):
        if int(dut.disp_req.value) == 1:
            return
        await RisingEdge(dut.clk)
    raise AssertionError("Timed out waiting for disp_req")


async def complete_display_read(dut, *, expected_addr: int, data_word: int) -> None:
    await wait_for_disp_req(dut)
    assert int(dut.disp_addr.value) == expected_addr
    dut.disp_rdata.value = data_word
    dut.disp_ack.value = 1
    await RisingEdge(dut.clk)
    dut.disp_ack.value = 0
    await ClockCycles(dut.clk, 1)


async def tick_pixel_1x1(dut, pixel_x: int) -> int:
    dut.active_video.value = 1
    dut.pixel_idx.value = pixel_x
    dut.pixel_tick.value = 0
    # Pixel selection is combinational from the current VGA coordinate. This
    # assertion would fail if the old one-clock output register returned.
    await Timer(1, unit="ns")
    got = int(dut.pixel_occupied.value)
    dut.pixel_tick.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.pixel_tick.value = 0
    await RisingEdge(dut.clk)
    return got


async def tick_pixel_2x1(dut, pixel_x: int) -> int:
    dut.active_video.value = 1
    dut.pixel_idx.value = pixel_x
    dut.pixel_tick.value = 0
    await Timer(1, unit="ns")
    got = int(dut.pixel_color.value)
    dut.pixel_tick.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.pixel_tick.value = 0
    await RisingEdge(dut.clk)
    return got


def pack_bytes(data: list[int]) -> int:
    value = 0
    for index, byte in enumerate(data):
        value |= (byte & 0xFF) << (8 * index)
    return value


def pack_2bpp_pixels(pixels: list[int]) -> int:
    value = 0
    for index, pixel in enumerate(pixels):
        value |= (pixel & 0x3) << (2 * index)
    return value
