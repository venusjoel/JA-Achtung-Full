# JA Achtung Full root testbench

This cocotb testbench exercises the standalone 1x2 Tiny Tapeout project,
`tt_um_ja_achtung_1x2`. Its Makefile lists the exact source set from
`targets/1x2-working-game`.

## How to run

To run the RTL simulation:

```sh
make -B
```

The pinned Tiny Tapeout gate-level action supplies the powered post-route
netlist and runs this testbench with `GATES=yes`. For a local gate-level run,
copy the powered final netlist to `gate_level_netlist.v`, set `PDK_ROOT`, and
run:

Then run:

```sh
make -B GATES=yes
```

To save VCD instead of FST, select the VCD dump in `tb.v` and run:

```sh
make -B FST=
```

This will generate `tb.vcd` instead of `tb.fst`.

## How to view the waveform file

Using GTKWave

```sh
gtkwave tb.fst tb.gtkw
```

Using Surfer

```sh
surfer tb.fst
```
