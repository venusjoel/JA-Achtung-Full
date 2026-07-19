from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge


MEMORY_SIZE = 8 * 1024 * 1024
ADDRESS_MASK = MEMORY_SIZE - 1


@dataclass
class SimplePsram:
    mem: bytearray = field(default_factory=lambda: bytearray(MEMORY_SIZE))
    # APS6404L powers up in serial SPI mode.  Tests that model a warm reset
    # can opt into QPI explicitly.
    mode: str = "SPI"

    def read(self, address: int, length: int) -> bytearray:
        address &= ADDRESS_MASK
        return bytearray(self.mem[address:address + length])

    def write(self, address: int, data: list[int]) -> None:
        address &= ADDRESS_MASK
        for offset, byte in enumerate(data):
            self.mem[(address + offset) & ADDRESS_MASK] = byte & 0xFF

    def burst_byte(self, address: int, offset: int) -> int:
        return self.mem[(address + offset) & ADDRESS_MASK]


class SplitPsramBFM:
    def __init__(
        self,
        psram,
        *,
        uio_in=None,
        uio_out=None,
        uio_oe=None,
        model: SimplePsram | None = None,
    ):
        self.psram = psram
        self.uio_in = uio_in
        self.uio_out = uio_out
        self.uio_oe = uio_oe
        self.model = model or SimplePsram()
        self.command_log: list[dict] = []

    @property
    def ce_n(self) -> int:
        return _safe_int(self.psram.o_ce_n.value)

    @property
    def sclk(self):
        return self.psram.o_sclk

    def controller_nibble(self) -> int:
        return _safe_int(self.psram.o_sio_out.value) & 0xF

    def controller_oe(self) -> int:
        return _safe_int(self.psram.o_sio_oe.value) & 0xF

    def controller_spi_bit(self) -> int:
        return self.controller_nibble() & 0x1

    def drive_nibble(self, nibble: int) -> None:
        nibble &= 0xF
        if self.uio_in is None:
            self.psram.i_sio_in.value = nibble
        else:
            self.uio_in.value = (
                ((nibble >> 0) & 1) << 1 |
                ((nibble >> 1) & 1) << 2 |
                ((nibble >> 2) & 1) << 4 |
                ((nibble >> 3) & 1) << 5
            )

    def release_bus(self) -> None:
        self.drive_nibble(0)

    def assert_top_mapping(self) -> None:
        """Prove the physical TT uio bus matches the controller split bus."""
        if self.uio_out is None or self.uio_oe is None:
            return
        sio = self.controller_nibble()
        sio_oe = self.controller_oe()
        expected_out = (
            (1 << 7)
            | (self.ce_n << 6)
            | (((sio >> 3) & 1) << 5)
            | (((sio >> 2) & 1) << 4)
            | (_safe_int(self.sclk.value) << 3)
            | (((sio >> 1) & 1) << 2)
            | (((sio >> 0) & 1) << 1)
            | 1
        )
        expected_oe = (
            (1 << 7)
            | (1 << 6)
            | (((sio_oe >> 3) & 1) << 5)
            | (((sio_oe >> 2) & 1) << 4)
            | (1 << 3)
            | (((sio_oe >> 1) & 1) << 2)
            | (((sio_oe >> 0) & 1) << 1)
            | 1
        )
        actual_out = _safe_int(self.uio_out.value)
        actual_oe = _safe_int(self.uio_oe.value)
        assert actual_out == expected_out, (
            f"uio_out mapping mismatch: expected 0x{expected_out:02x}, "
            f"got 0x{actual_out:02x}"
        )
        assert actual_oe == expected_oe, (
            f"uio_oe mapping mismatch: expected 0x{expected_oe:02x}, "
            f"got 0x{actual_oe:02x}"
        )

    async def monitor_top_mapping(self, dut_clk) -> None:
        while True:
            await RisingEdge(dut_clk)
            await ReadOnly()
            self.assert_top_mapping()

    async def capture_spi_bit(self) -> int:
        await RisingEdge(self.sclk)
        await ReadOnly()
        return self.controller_spi_bit()

    async def capture_spi_byte(self) -> int | None:
        value = 0
        observed_oe = []
        for _ in range(8):
            await RisingEdge(self.sclk)
            await ReadOnly()
            # A cold SPI device sees the controller's two-clock QPI-exit
            # preamble as an incomplete serial command and discards it when
            # CE# rises.  Do not invent six clock edges to turn it into 0xFF.
            if self.ce_n:
                assert observed_oe == [0xF, 0x0], (
                    f"aborted QPI-exit preamble used unexpected OE: {observed_oe}"
                )
                return None
            observed_oe.append(self.controller_oe())
            value = (value << 1) | self.controller_spi_bit()
        # The final bit is sampled on the same rising edge at which the FSM
        # releases SIO; post-edge ReadOnly therefore observes OE=0 there.
        assert observed_oe == [0x1] * 7 + [0x0], (
            f"serial command did not drive only SIO0: {observed_oe}"
        )
        return value & 0xFF

    async def capture_qpi_nibble(self) -> int:
        await RisingEdge(self.sclk)
        await ReadOnly()
        self._last_qpi_oe = self.controller_oe()
        return self.controller_nibble()

    async def capture_qpi_byte(self) -> int:
        hi = await self.capture_qpi_nibble()
        hi_oe = self._last_qpi_oe
        lo = await self.capture_qpi_nibble()
        lo_oe = self._last_qpi_oe
        value = ((hi << 4) | lo) & 0xFF
        expected_oe = [0xF, 0x0] if value == 0xF5 else [0xF, 0xF]
        assert [hi_oe, lo_oe] == expected_oe, (
            f"QPI command 0x{value:02x} used OE {[hi_oe, lo_oe]}"
        )
        return value

    async def capture_qpi_addr(self) -> int:
        address = 0
        observed_oe = []
        for _ in range(6):
            address = (address << 4) | await self.capture_qpi_nibble()
            observed_oe.append(self._last_qpi_oe)
        assert observed_oe == [0xF] * 6, (
            f"QPI address phase used unexpected OE: {observed_oe}"
        )
        return address & ADDRESS_MASK

    async def skip_read_wait_cycles(self, count: int = 6) -> None:
        for _ in range(count):
            await RisingEdge(self.sclk)
            await ReadOnly()
            assert self.controller_oe() == 0, "controller drove SIO during read wait"

    async def capture_write_data(self) -> list[int]:
        data = []
        while True:
            await RisingEdge(self.sclk)
            await ReadOnly()
            if self.ce_n:
                return data
            assert self.controller_oe() == 0xF, "QPI write released SIO too early"
            hi = self.controller_nibble()

            await RisingEdge(self.sclk)
            await ReadOnly()
            assert self.controller_oe() == 0xF, "QPI write released SIO too early"
            lo = self.controller_nibble()
            data.append(((hi << 4) | lo) & 0xFF)

            await FallingEdge(self.sclk)
            await ReadOnly()
            if self.ce_n:
                return data

    async def drive_read_stream(self, address: int) -> list[int]:
        data = []
        offset = 0
        while True:
            await FallingEdge(self.sclk)
            if self.ce_n:
                break
            assert self.controller_oe() == 0, "controller drove SIO during QPI read"
            value = self.model.burst_byte(address, offset)
            self.drive_nibble(value >> 4)

            await FallingEdge(self.sclk)
            if self.ce_n:
                break
            assert self.controller_oe() == 0, "controller drove SIO during QPI read"
            self.drive_nibble(value)
            data.append(value)

            await RisingEdge(self.sclk)
            if self.ce_n:
                break
            offset += 1
        self.release_bus()
        return data

    async def run(self) -> None:
        self.release_bus()
        while True:
            await FallingEdge(self.psram.o_ce_n)

            mode = self.model.mode
            cmd = await (self.capture_spi_byte() if mode == "SPI" else self.capture_qpi_byte())
            txn = {
                "mode": mode,
                "cmd": cmd,
                "aborted": cmd is None,
                "addr": None,
                "data": [],
                "read_data": [],
                "wait_cycles": 0,
            }

            if cmd is None:
                pass
            elif cmd == 0xF5:
                self.model.mode = "SPI"
            elif cmd == 0x66:
                pass
            elif cmd == 0x99:
                self.model.mode = "SPI"
            elif cmd == 0x35:
                self.model.mode = "QPI"
            elif cmd == 0xEB:
                address = await self.capture_qpi_addr()
                txn["addr"] = address
                await self.skip_read_wait_cycles(6)
                txn["wait_cycles"] = 6
                txn["read_data"] = await self.drive_read_stream(address)
            elif cmd in (0x02, 0x38):
                address = await self.capture_qpi_addr()
                data = await self.capture_write_data()
                txn["addr"] = address
                txn["data"] = data
                self.model.write(address, data)
            elif cmd == 0xC0:
                pass
            else:
                cocotb.log.warning("Unhandled PSRAM command 0x%02X in %s mode", cmd, mode)

            if self.ce_n == 0:
                await RisingEdge(self.psram.o_ce_n)
            self.command_log.append(txn)

    async def wait_for_qpi_ready(self, dut_clk, timeout_cycles: int = 2000) -> None:
        for _ in range(timeout_cycles):
            accepted = [t["cmd"] for t in self.command_log if t["cmd"] is not None]
            if self.model.mode == "QPI" and accepted[-3:] == [0x66, 0x99, 0x35]:
                return
            await RisingEdge(dut_clk)
        raise AssertionError(
            "Timed out waiting for PSRAM reset/quad sequence 0x66,0x99,0x35"
        )


def _safe_int(value) -> int:
    text = str(value).lower()
    if any(ch not in "01" for ch in text):
        raise AssertionError(f"unknown logic value where binary was required: {value}")
    return int(text, 2)
