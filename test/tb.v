`default_nettype none
`timescale 1ns / 1ps

/* Testbench shell around the real project top. The cocotb test in test.py
   drives the pins only, so the same bench works for RTL and gate-level. */
module tb ();

  initial begin
    $dumpfile("tb.fst");
    $dumpvars(0, tb);
    #1;
  end

  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;
  reg [7:0] uio_in;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

`ifdef GL_TEST
  wire VPWR = 1'b1;
  wire VGND = 1'b0;
  // Gate-level sim is much slower; the cocotb test reads this flag and skips
  // the checks that need a full VGA frame.
  reg gl_test_mode = 1'b1;
`else
  reg gl_test_mode = 1'b0;
`endif

  tt_um_ja_achtung_1x2 user_project (

`ifdef GL_TEST
      .VPWR(VPWR),
      .VGND(VGND),
`endif

      .ui_in  (ui_in),
      .uo_out (uo_out),
      .uio_in (uio_in),
      .uio_out(uio_out),
      .uio_oe (uio_oe),
      .ena    (ena),
      .clk    (clk),
      .rst_n  (rst_n)
  );

endmodule
