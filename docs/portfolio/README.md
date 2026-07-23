# JA Achtung Project Portfolio

This portfolio presents the two Tiny Tapeout implementations of our
hardware version of *Achtung, die Kurve!*, created by Joel Kaplan and
Amit Elmaliach.

## Start here

- [Presentation slides (PDF)](JA-Achtung-Project-Presentation.pdf)
- [Final project report (PDF)](JA-Achtung-Final-Report.pdf)
- [PowerPoint presentation with embedded demonstration videos](JA-Achtung-Project-Presentation.pptx)
- [Editable report source](JA-Achtung-Final-Report.docx)

The PDFs are the quickest way to review the project in a browser. Download
and open the PowerPoint file in desktop PowerPoint to play its embedded
demonstration videos.

## Project at a glance

The project combines direct 640x480 VGA generation, an external QSPI PSRAM
framebuffer, dual game-controller input, game logic, and display arbitration
inside unusually dense Tiny Tapeout designs:

- [JA Achtung Compact -- 1x1](https://github.com/venusjoel/JA-Achtung-Compact):
  cardinal movement and a 1-bit framebuffer in one Tiny Tapeout tile.
- [JA Achtung Full -- 1x2](https://github.com/venusjoel/JA-Achtung-Full):
  64-direction movement, boost, trail gaps, a colour-selection lobby, and
  a 2-bit framebuffer in two Tiny Tapeout tiles.

Both repositories include reproducible simulation, gate-level checks,
hardening results, and a DE10-Lite FPGA build sourced directly from the
submitted HDL.
