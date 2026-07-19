/*
 * SPDX-FileCopyrightText: 2026 Joel Kaplan and Amit Elmaliach
 * SPDX-License-Identifier: Apache-2.0
 */

// vga_sync.v
module vga_sync (
    input wire clk, // Assuming 25.175 MHz for 640x480@60Hz
    input wire pixel_tick,
    input wire rst_n,
    output reg [9:0] h_count,
    output reg [9:0] v_count,
    output wire hsync,
    output wire vsync,
    output wire active_video,
    output wire vblank
);

    // In cocotb we use a much shorter frame so the game loop remains interactive.
`ifdef COCOTB_SIM
`ifdef FULL_VGA_SIM
    localparam H_VISIBLE     = 10'd640;
    localparam V_VISIBLE     = 10'd480;
    localparam H_TOTAL       = 10'd800;
    localparam V_TOTAL       = 10'd525;
    localparam H_SYNC_START  = 10'd656;
    localparam H_SYNC_END    = 10'd752;
    localparam V_SYNC_START  = 10'd490;
    localparam V_SYNC_END    = 10'd492;
`elsif FAST_COMPARE_SIM
    localparam H_VISIBLE     = 10'd8;
    localparam V_VISIBLE     = 10'd4;
    localparam H_TOTAL       = 10'd40;
    localparam V_TOTAL       = 10'd20;
    localparam H_SYNC_START  = 10'd36;
    localparam H_SYNC_END    = 10'd40;
    localparam V_SYNC_START  = 10'd5;
    localparam V_SYNC_END    = 10'd7;
`else
    localparam H_VISIBLE     = 10'd64;
    localparam V_VISIBLE     = 10'd48;
    localparam H_TOTAL       = 10'd80;
    localparam V_TOTAL       = 10'd53;
    localparam H_SYNC_START  = 10'd68;
    localparam H_SYNC_END    = 10'd76;
    localparam V_SYNC_START  = 10'd49;
    localparam V_SYNC_END    = 10'd51;
`endif
`else
    localparam H_VISIBLE     = 10'd640;
    localparam V_VISIBLE     = 10'd480;
    localparam H_TOTAL       = 10'd800;
    localparam V_TOTAL       = 10'd525;
    localparam H_SYNC_START  = 10'd656;
    localparam H_SYNC_END    = 10'd752;
    localparam V_SYNC_START  = 10'd490;
    localparam V_SYNC_END    = 10'd492;
`endif
    //genrtating the VGA similation signal, we can use the same timing as 640x480@60Hz
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            h_count <= 10'd0;
            v_count <= 10'd0;
        end else if (pixel_tick) begin
            if (h_count == H_TOTAL - 10'd1) begin
                h_count <= 10'd0;
                if (v_count == V_TOTAL - 10'd1)
                    v_count <= 10'd0;
                else
                    v_count <= v_count + 10'd1;
            end else begin
                h_count <= h_count + 10'd1;
            end
        end
    end

    wire h_visible = (h_count < H_VISIBLE);
    (* keep *) wire v_visible_active = (v_count < V_VISIBLE);
    (* keep *) wire v_visible_blank = (v_count < V_VISIBLE);

    assign hsync = ~(h_count >= H_SYNC_START && h_count < H_SYNC_END);
    assign vsync = ~(v_count >= V_SYNC_START && v_count < V_SYNC_END);
    assign active_video = h_visible && v_visible_active;
    assign vblank = !v_visible_blank;

endmodule
