# DE10-Lite FPGA build

This project runs the exact JA Achtung Full `1x2` Tiny Tapeout RTL on a Terasic
DE10-Lite (`10M50DAF484C7G`). The only FPGA-specific RTL is the thin
`de10_fpga_top.v` pin wrapper. The Quartus project references the submission
files directly from `../../src`; it does not keep a second copy of the game.

The FPGA support is optional developer/demo tooling. Nothing under `fpga/` is
listed in `info.yaml`, so it does not change the Tiny Tapeout ASIC or GDS build.

## Hardware needed

- Terasic DE10-Lite and its USB cable
- [Tiny VGA PMOD](https://github.com/mole99/tiny-vga) and a VGA monitor
- [QSPI PSRAM PMOD](https://github.com/mole99/qspi-pmod) with an APS6404L RAM A
- [Gamepad PMOD](https://github.com/psychogenic/gamepad-pmod), using the default
  Tiny Tapeout firmware configuration
- Two SNES-compatible controllers
- Jumper wires or a correctly wired breakout between the PMODs and DE10-Lite
  GPIO header JP1

Important: JP1 is a 3.3 V GPIO header, but it is not a PMOD connector. Do not
plug a PMOD directly onto JP1. Wire the signals using the tables below, connect
every PMOD VCC to **3.3 V** (JP1 pin 29), and connect every PMOD GND to GND
(JP1 pin 30 or 12). Never power these PMODs from JP1 pin 11, which is 5 V.

## DE10-Lite board signals

| Function | DE10-Lite signal | FPGA pin |
| --- | --- | --- |
| 50 MHz game clock | `MAX10_CLK1_50` | `PIN_P11` |
| Active-low reset | `KEY[0]` / KEY0 | `PIN_B8` |

KEY0 is the game and PSRAM reset. The slide switches and KEY1 are unused.

## Tiny VGA PMOD wiring

The PMOD pin numbers below follow the Tiny VGA board markings. R1/G1/B1 are
the most-significant colour bits; R0/G0/B0 are the least-significant bits.

| VGA PMOD pin | Signal | TT output | JP1 pin | GPIO | FPGA pin |
| --- | --- | --- | ---: | --- | --- |
| 1 | R1 | `uo[0]` | 1 | `GPIO[0]` | `PIN_V10` |
| 2 | G1 | `uo[1]` | 3 | `GPIO[2]` | `PIN_V9` |
| 3 | B1 | `uo[2]` | 5 | `GPIO[4]` | `PIN_V8` |
| 4 | VSync | `uo[3]` | 7 | `GPIO[6]` | `PIN_V7` |
| 7 | R0 | `uo[4]` | 8 | `GPIO[7]` | `PIN_W7` |
| 8 | G0 | `uo[5]` | 6 | `GPIO[5]` | `PIN_W8` |
| 9 | B0 | `uo[6]` | 4 | `GPIO[3]` | `PIN_W9` |
| 10 | HSync | `uo[7]` | 2 | `GPIO[1]` | `PIN_W10` |

Connect the PMOD's GND pins to DE10-Lite GND and its VCC pins to 3.3 V.

## QSPI PSRAM PMOD wiring

The design uses RAM A. Flash and RAM B chip selects are held high. “Signal” is
the eight-position Tiny Tapeout PMOD signal number; standard 12-pin PMOD
connector positions are shown in parentheses.

| Signal | Function | TT bidirectional | JP1 pin | GPIO | FPGA pin |
| --- | --- | --- | ---: | --- | --- |
| 1 (pin 1) | Flash CS# (unused) | `uio[0]` | 19 | `GPIO[16]` | `PIN_AB12` |
| 2 (pin 2) | PSRAM IO0 | `uio[1]` | 21 | `GPIO[18]` | `PIN_AB11` |
| 3 (pin 3) | PSRAM IO1 | `uio[2]` | 23 | `GPIO[20]` | `PIN_AB10` |
| 4 (pin 4) | PSRAM SCK | `uio[3]` | 25 | `GPIO[22]` | `PIN_AA9` |
| 5 (pin 7) | PSRAM IO2 | `uio[4]` | 26 | `GPIO[23]` | `PIN_Y8` |
| 6 (pin 8) | PSRAM IO3 | `uio[5]` | 24 | `GPIO[21]` | `PIN_AA10` |
| 7 (pin 9) | RAM A CS# | `uio[6]` | 22 | `GPIO[19]` | `PIN_W11` |
| 8 (pin 10) | RAM B CS# (unused) | `uio[7]` | 20 | `GPIO[17]` | `PIN_Y11` |

Connect the QSPI PMOD's VCC to 3.3 V and GND to GND. Do not use 5 V.

## Gamepad PMOD wiring

Only the three default Tiny Tapeout report pins are required. Leave the other
`gamepad_ui` inputs unconnected; the Quartus project enables weak pull-ups.

| Gamepad PMOD signal | TT input | JP1 pin | GPIO | FPGA pin |
| --- | --- | ---: | --- | --- |
| Latch / IO5 | `ui[4]` | 40 | `GPIO[35]` | `PIN_AA2` |
| Clock / IO6 | `ui[5]` | 38 | `GPIO[33]` | `PIN_Y3` |
| Data / IO7 | `ui[6]` | 36 | `GPIO[31]` | `PIN_Y4` |

Connect the Gamepad PMOD's VCC to 3.3 V and GND to GND. Controller 1 and
controller 2 plug into the two SNES sockets on that PMOD.

## Build and load

Install Intel Quartus Prime Lite with MAX 10 device support. The project was
validated with Quartus Prime Lite 17.0. From PowerShell in this repository:

```powershell
cd fpga/de10-lite
.\build.cmd
```

This creates `output_files/de10_game.sof`. To rebuild and immediately program
a connected DE10-Lite through its on-board USB-Blaster:

The helper stages a fresh ASCII-only copy of these exact source files under
`C:\fpga_work` because Quartus 17 cannot open this repository's Unicode path.
It copies only the completed `.sof` back into this repository. Set the
`JA_ACHTUNG_FPGA_WORK` environment variable to use another short ASCII path.

```powershell
.\load.cmd
```

To program the existing `.sof` without rebuilding:

```powershell
.\load.cmd -SkipBuild
```

The JTAG load is volatile and disappears when the board loses power. Close the
DE10-Lite Control Panel before programming because it can hold the USB-Blaster.

For the safest PSRAM start-up, hold KEY0 down while programming, keep it held
for at least 150 microseconds after power and configuration are stable (a
normal human-length press is much longer), and then release it. The RTL sends
the APS6404L reset/quad-enable sequence and displays the colour-selection lobby.

In the lobby, use each controller's D-pad to choose a colour, A to confirm,
Select to unlock, and Start after both players are ready. During play, steer
with Left/Right or L/R and hold A for boost.

The JP1 numbering and FPGA balls follow the official
[DE10-Lite user manual](https://ftp.intel.com/Public/Pub/fpgaup/pub/Intel_Material/Boards/DE10-Lite/DE10_Lite_User_Manual.pdf).
