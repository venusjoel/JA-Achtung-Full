// DE10-Lite wrapper for the JA Achtung Full 1x2 Tiny Tapeout RTL.
`default_nettype none

module de10_fpga_top (
    input  wire        MAX10_CLK1_50,
    input  wire [1:0]  KEY,
    input  wire [9:0]  SW,
    input  wire [7:0]  gamepad_ui,
    output wire [7:0]  uo_out,
    output wire        flash_cen,
    inout  wire [3:0]  psram_sio,
    output wire        psram_sclk,
    output wire        psram_a_cen,
    output wire        psram_b_cen
);

    wire [7:0] uio_out_w;
    wire [7:0] uio_oe_w;
    wire [7:0] uio_in_w;

    assign uio_in_w = {
        2'b00, psram_sio[3], psram_sio[2], 1'b0,
        psram_sio[1], psram_sio[0], 1'b0
    };

    tt_um_ja_achtung_1x2 u_top (
        .clk     (MAX10_CLK1_50),
        .rst_n   (KEY[0]),
        .ena     (1'b1),
        .ui_in   (gamepad_ui),
        .uio_in  (uio_in_w),
        .uo_out  (uo_out),
        .uio_out (uio_out_w),
        .uio_oe  (uio_oe_w)
    );

    assign flash_cen   = uio_out_w[0];
    assign psram_sclk  = uio_out_w[3];
    assign psram_a_cen = uio_out_w[6];
    assign psram_b_cen = uio_out_w[7];

    assign psram_sio[0] = uio_oe_w[1] ? uio_out_w[1] : 1'bZ;
    assign psram_sio[1] = uio_oe_w[2] ? uio_out_w[2] : 1'bZ;
    assign psram_sio[2] = uio_oe_w[4] ? uio_out_w[4] : 1'bZ;
    assign psram_sio[3] = uio_oe_w[5] ? uio_out_w[5] : 1'bZ;

    wire _unused = &{1'b0, KEY[1], SW};

endmodule

`default_nettype wire
