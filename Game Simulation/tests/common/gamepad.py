from __future__ import annotations

from cocotb.triggers import ClockCycles


P1_LEFT = 0b000001
P1_RIGHT = 0b000010
P2_LEFT = 0b000100
P2_RIGHT = 0b001000
P1_BOOST = 0b010000
P2_BOOST = 0b100000

PMOD_LATCH = 1 << 4
PMOD_CLK = 1 << 5
PMOD_DATA = 1 << 6
PMOD_IDLE = PMOD_LATCH | PMOD_CLK


def pmod_frame_bits(button_mask: int, *, p1_a: bool = False, p2_a: bool = False,
                    p1_start: bool = False, p2_start: bool = False,
                    p1_select: bool = False, p2_select: bool = False,
                    p1_dpad_left: bool = False, p1_dpad_right: bool = False,
                    p2_dpad_left: bool = False, p2_dpad_right: bool = False,
                    p1_present: bool = True, p2_present: bool = True) -> list[int]:
    bits = [0] * 24

    if button_mask & P2_LEFT:
        bits[10] = 1
    if button_mask & P2_RIGHT:
        bits[11] = 1
    if button_mask & P1_LEFT:
        bits[22] = 1
    if button_mask & P1_RIGHT:
        bits[23] = 1

    bits[6] = int(p2_dpad_left)
    bits[7] = int(p2_dpad_right)
    bits[18] = int(p1_dpad_left)
    bits[19] = int(p1_dpad_right)

    if p2_select:
        bits[2] = 1
    if p2_start:
        bits[3] = 1
    if p2_a:
        bits[8] = 1
    if p1_select:
        bits[14] = 1
    if p1_start:
        bits[15] = 1
    if p1_a:
        bits[20] = 1

    # A disconnected SNES controller half is pulled high for all 12 bits.
    # Apply this last so presence takes precedence over requested buttons.
    if not p2_present:
        bits[:12] = [1] * 12
    if not p1_present:
        bits[12:] = [1] * 12

    return bits


def _ui_value(*, latch: int = 1, clk: int = 1, data: int = 0) -> int:
    return ((latch & 1) << 4) | ((clk & 1) << 5) | ((data & 1) << 6)


async def send_pmod_frame(dut, bits: list[int], settle_cycles: int = 3) -> None:
    dut.ui_in.value = PMOD_IDLE
    await ClockCycles(dut.clk, settle_cycles)

    for bit in bits:
        dut.ui_in.value = _ui_value(latch=1, clk=1, data=bit)
        await ClockCycles(dut.clk, settle_cycles)
        dut.ui_in.value = _ui_value(latch=1, clk=0, data=bit)
        await ClockCycles(dut.clk, settle_cycles)
        dut.ui_in.value = _ui_value(latch=1, clk=1, data=bit)
        await ClockCycles(dut.clk, settle_cycles)

    dut.ui_in.value = _ui_value(latch=0, clk=1, data=0)
    await ClockCycles(dut.clk, settle_cycles + 1)
    dut.ui_in.value = PMOD_IDLE
    await ClockCycles(dut.clk, settle_cycles + 1)


async def send_button_mask(dut, button_mask: int) -> None:
    await send_pmod_frame(dut, pmod_frame_bits(
        button_mask,
        p1_a=bool(button_mask & P1_BOOST),
        p2_a=bool(button_mask & P2_BOOST),
    ))


async def send_2x1_start_sequence(dut) -> None:
    await send_pmod_frame(dut, pmod_frame_bits(0, p1_a=True, p2_a=True))
    await send_pmod_frame(dut, pmod_frame_bits(0))
    await send_pmod_frame(dut, pmod_frame_bits(0, p1_start=True, p2_start=True))
    await send_pmod_frame(dut, pmod_frame_bits(0))
