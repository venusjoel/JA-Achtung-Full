/*
 * SPDX-FileCopyrightText: 2026 Joel Kaplan and Amit Elmaliach
 * SPDX-License-Identifier: Apache-2.0
 */

module tt_um_ja_achtung_1x2 (
    input  wire [7:0] ui_in,    // Dedicated inputs (Buttons)
    output wire [7:0] uo_out,   // Dedicated outputs (VGA)
    input  wire [7:0] uio_in,   // Bidirectional inputs (QSPI MISO)
    output wire [7:0] uio_out,  // Bidirectional outputs (QSPI CS, CLK, MOSI)
    output wire [7:0] uio_oe,   // Bidirectional enables
    input  wire       ena,      // always 1 when the design is powered
    input  wire       clk,      // System clock
    input  wire       rst_n     // reset_n - low to reset
);

`ifdef COCOTB_SIM
`ifdef FULL_VGA_SIM
    localparam integer FRAME_W  = 640;
    localparam integer FRAME_H  = 480;
    localparam integer START1_X = 100;
    localparam integer START2_X = 540;
    localparam integer START_Y  = 240;
`elsif FAST_COMPARE_SIM
    localparam integer FRAME_W  = 640;
    localparam integer FRAME_H  = 480;
    localparam integer START1_X = 100;
    localparam integer START2_X = 540;
    localparam integer START_Y  = 240;
`else
    localparam integer FRAME_W  = 64;
    localparam integer FRAME_H  = 48;
    localparam integer START1_X = 10;
    localparam integer START2_X = 53;
    localparam integer START_Y  = 24;
`endif
`else
    localparam integer FRAME_W  = 640;
    localparam integer FRAME_H  = 480;
    localparam integer START1_X = 100;
    localparam integer START2_X = 540;
    localparam integer START_Y  = 240;
`endif

    localparam integer BURST_BYTES = 8;
    localparam integer DATA_WIDTH  = 8 * BURST_BYTES;

    // Gamepad PMOD on ui_in[4]=LATCH, ui_in[5]=CLK, ui_in[6]=DATA
    wire [1:0] gp_left, gp_right;
    wire [1:0] gp_select, gp_start;
    wire [1:0] gp_up, gp_down, gp_a, gp_l, gp_r;

    gamepad_pmod_dual gamepad_inst (
        .rst_n      (rst_n),
        .clk        (clk),
        .pmod_data  (ui_in[6]),
        .pmod_clk   (ui_in[5]),
        .pmod_latch (ui_in[4]),
        .select     (gp_select), .start(gp_start),
        .up         (gp_up),  .down   (gp_down),
        .left       (gp_left),.right  (gp_right),
        .a          (gp_a),
        .l          (gp_l),   .r      (gp_r)
    );

    // Either the D-pad or the shoulder buttons can steer during gameplay.
    wire p1_left  = gp_left[0]  | gp_l[0];
    wire p1_right = gp_right[0] | gp_r[0];
    wire p2_left  = gp_left[1]  | gp_l[1];
    wire p2_right = gp_right[1] | gp_r[1];
    wire p1_boost = gp_a[0];
    wire p2_boost = gp_a[1];
    wire p1_menu_start = gp_start[0];
    wire p2_menu_start = gp_start[1];
    wire p1_menu_select = gp_select[0];
    wire p2_menu_select = gp_select[1];
    wire p1_pick_col = gp_left[0] | gp_right[0];
    wire p1_pick_col_inc = gp_right[0];  // sampled only when p1_pick_col pulses
    wire p1_pick_row = gp_up[0] | gp_down[0];
    wire p1_pick_select = p1_boost;
    wire p2_pick_col = gp_left[1] | gp_right[1];
    wire p2_pick_col_inc = gp_right[1];
    wire p2_pick_row = gp_up[1] | gp_down[1];
    wire p2_pick_select = p2_boost;

    reg pixel_div;
    reg boost_flash_phase;
    reg vblank_prev_top;
    wire pixel_tick = pixel_div; //the VGA 25MHz pixel clock is derived by dividing the 50MHz system clock

    //current pixel coordinates and sync signals from the VGA timing generator
    wire [9:0] h_count;
    wire [9:0] v_count;
    //VGA sync pulses and active video signal
    wire       hsync;
    wire       vsync;
    //active_video is high when the current pixel coordinates are within the visible display area
    wire       active_video;
    //true during blanking
    wire       vblank;
    wire       frame_start = vblank && !vblank_prev_top;
    //current 2 bit color as read from the framebuffer stream
    wire [1:0] fb_pixel_color;

    //this is for the game engine
    wire        game_req;    // Game wants a PSRAM transaction (read or write)
    wire        game_we;    //1 means write transaction, 0 means read transaction
    wire        game_ack;   // PSRAM transaction is complete 
    wire        game_over;
    wire        lobby_active;
    wire        clear_active;
    wire [9:0]  p1_head_x, p2_head_x;
    wire [8:0]  p1_head_y, p2_head_y;
    wire        p1_head_on, p2_head_on;
    wire [2:0]  winner_color;
    wire [2:0]  p1_color_id;
    wire [2:0]  p2_color_id;
    wire [2:0]  p1_pick_id;
    wire [2:0]  p2_pick_id;
    wire        p1_selected;
    wire        p2_selected;
    wire [16:0] game_addr;   //address for the PSRAM transaction, aligned to the active burst size
    wire [DATA_WIDTH-1:0] game_wdata; //burst write data for game transactions
    wire [DATA_WIDTH-1:0] game_rdata; //burst read data from PSRAM for game transactions

    //this is for the display streamer
    wire        disp_req;
    wire        disp_ack;
    wire [16:0] disp_addr;
    wire [DATA_WIDTH-1:0] disp_rdata;

    //these connect to the PSRAM controller, which multiplexes access between the game and display streamer
    wire        psram_ce_n;
    wire        psram_sclk;
    wire [3:0]  psram_sio_out;
    wire [3:0]  psram_sio_oe;
    wire [3:0]  psram_sio_in;
    wire        psram_valid;
    wire        psram_busy;
    wire [DATA_WIDTH-1:0] psram_rdata;
    wire [DATA_WIDTH-1:0] psram_wdata;

    //who uses ram this cycle? During active video the display streamer has priority, during vblank the game has priority. The display streamer can only use leftover vblank cycles when the game isn't requesting access.
    wire        actual_qspi_req;
    wire        actual_qspi_we;
    wire [16:0] actual_qspi_addr;
    reg         txn_is_game;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pixel_div          <= 1'b0;
            boost_flash_phase  <= 1'b0;
            vblank_prev_top    <= 1'b0;
            txn_is_game        <= 1'b0;
        end else begin
            // Divide the 50MHz clock to get a 25MHz pixel clock for VGA timing
            pixel_div <= ~pixel_div;
            vblank_prev_top <= vblank;
            // Toggle once per frame; boost flashes at display time without
            // changing the collision framebuffer stored in PSRAM.
            if (vblank && !vblank_prev_top) begin
                boost_flash_phase <= ~boost_flash_phase;
            end
            if (!psram_busy && actual_qspi_req) begin 
                //first display then game, but the game can use any leftover cycles in vblank
                // when the display streamer isn't requesting access
                txn_is_game <= (vblank && game_req);
            end
        end
    end

    vga_sync sync_inst (
        .clk(clk),
        .pixel_tick(pixel_tick),
        .rst_n(rst_n),
        .h_count(h_count),
        .v_count(v_count),
        .hsync(hsync),
        .vsync(vsync),
        .active_video(active_video),
        .vblank(vblank)
    );

    game_fsm #(
        .FRAME_W(FRAME_W),
        .FRAME_H(FRAME_H),
        .START1_X(START1_X),
        .START2_X(START2_X),
        .START_Y(START_Y),
        .BURST_BYTES(BURST_BYTES),
        .DATA_WIDTH(DATA_WIDTH)
    ) engine_inst (
        .clk(clk),
        .rst_n(rst_n),
        .p1_left(p1_left),
        .p1_right(p1_right),
        .p2_left(p2_left),
        .p2_right(p2_right),
        .p1_boost(p1_boost),
        .p2_boost(p2_boost),
        .p1_menu_start(p1_menu_start),
        .p2_menu_start(p2_menu_start),
        .p1_menu_select(p1_menu_select),
        .p2_menu_select(p2_menu_select),
        .p1_pick_col(p1_pick_col),
        .p1_pick_col_inc(p1_pick_col_inc),
        .p1_pick_row(p1_pick_row),
        .p1_pick_select(p1_pick_select),
        .p2_pick_col(p2_pick_col),
        .p2_pick_col_inc(p2_pick_col_inc),
        .p2_pick_row(p2_pick_row),
        .p2_pick_select(p2_pick_select),
        .vblank(vblank),
        .frame_start(frame_start),
        .game_req(game_req),
        .game_we(game_we),
        .game_addr(game_addr),
        .game_wdata(game_wdata),
        .game_rdata(game_rdata),
        .game_ack(game_ack),
        .game_over(game_over),
        .winner_color(winner_color),
        .p1_color_id(p1_color_id),
        .p2_color_id(p2_color_id),
        .p1_pick_id(p1_pick_id),
        .p2_pick_id(p2_pick_id),
        .p1_selected(p1_selected),
        .p2_selected(p2_selected),
        .lobby_active(lobby_active),
        .clear_active(clear_active),
        .p1_head_x(p1_head_x),
        .p1_head_y(p1_head_y),
        .p2_head_x(p2_head_x),
        .p2_head_y(p2_head_y),
        .p1_head_on(p1_head_on),
        .p2_head_on(p2_head_on)
    );

`ifdef FAST_COMPARE_SIM
    assign disp_req = 1'b0;
    assign disp_addr = 17'd0;
    assign fb_pixel_color = 2'b00;
`else
    display_streamer #(
        .FRAME_W(FRAME_W),
        .FRAME_H(FRAME_H),
        .BURST_BYTES(BURST_BYTES),
        .DATA_WIDTH(DATA_WIDTH)
    ) disp_inst (
        .clk(clk),
        .rst_n(rst_n),
        .pixel_tick(pixel_tick),
        .pixel_idx(h_count[4:0]),
        .active_video(active_video),
        .vblank(vblank),
        .frame_start(frame_start),
        .disp_req(disp_req),
        .disp_addr(disp_addr),
        .disp_rdata(disp_rdata),
        .disp_ack(disp_ack),
        .pixel_color(fb_pixel_color)
    );
`endif

    // A solid trail already shows its own head in the framebuffer. During a
    // gap, share one 2x2 display-only marker between the players to avoid two
    // full coordinate comparators. Simultaneous gaps are rare; alternating
    // their priority each frame keeps both heads visible without extra state.
    wire head_select_p2 = p2_head_on && (!p1_head_on || boost_flash_phase);
    wire head_marker_on = p1_head_on || p2_head_on;
    wire [9:0] marker_x = head_select_p2 ? p2_head_x : p1_head_x;
    wire [8:0] marker_y = head_select_p2 ? p2_head_y : p1_head_y;
    wire head_marker_px = head_marker_on &&
        (h_count[9:1] == marker_x[9:1]) && (v_count[8:1] == marker_y[8:1]);
    wire [1:0] pixel_color = head_marker_px ?
        (head_select_p2 ? 2'b10 : 2'b01) : fb_pixel_color;

    // During active video the display path owns PSRAM. During vertical blank
    // the game gets priority for its collision checks and writes, and the
    // display streamer can use any leftover blanking cycles to prefetch the
    // next frame's first bursts.
`ifdef FAST_COMPARE_SIM // In this mode we want to ignore the display streamer and just let the game have full access to PSRAM to maximize simulation speed
    assign actual_qspi_req  = game_req;
    assign actual_qspi_we   = game_we;
    assign actual_qspi_addr = game_addr;
`else // In normal operation, the display streamer has priority during active video, and the game has priority during vblank, but the display streamer can use leftover vblank cycles when the game isn't requesting access
    assign actual_qspi_req  = disp_req | (vblank & game_req);
    assign actual_qspi_we   = vblank & game_req & game_we;
    assign actual_qspi_addr = (vblank & game_req) ? game_addr : disp_addr;
`endif
    // The PSRAM controller always sees the combined requests from both the game and display streamer, and it will assert psram_valid when the transaction is complete. The game and display streamer can check psram_valid along with txn_is_game to determine if their transaction is complete.
    assign psram_wdata      = game_wdata;

    assign game_rdata = psram_rdata;
    assign disp_rdata = psram_rdata;
    assign game_ack   = psram_valid && txn_is_game;
    assign disp_ack   = psram_valid && !txn_is_game;

    psram_controller #(
        .CLK_FREQ_HZ  (50_000_000),
        .SCLK_FREQ_HZ (25_000_000),
        .BURST_BYTES  (BURST_BYTES),
        .DATA_WIDTH   (DATA_WIDTH)
    ) psram_inst (
        .clk      (clk),
        .rst_n    (rst_n),
        .i_we     (actual_qspi_req &&  actual_qspi_we),
        .i_re     (actual_qspi_req && !actual_qspi_we),
        .i_addr   (actual_qspi_addr),
        .i_wdata  (psram_wdata),
        .o_rdata  (psram_rdata),
        .o_valid  (psram_valid),
        .o_busy   (psram_busy),
        .o_ce_n   (psram_ce_n),
        .o_sclk   (psram_sclk),
        .o_sio_out(psram_sio_out),
        .o_sio_oe (psram_sio_oe),
        .i_sio_in (psram_sio_in)
    );

    // VGA output: TT VGA PMOD bit layout
    // [0]=R1 [1]=G1 [2]=B1 [3]=VSYNC [4]=R0 [5]=G0 [6]=B0 [7]=HSYNC
    localparam [9:0] PAL_T  = (FRAME_W == 64) ? 10'd1  : 10'd4;
    localparam [9:0] SIDE_T = (FRAME_W == 64) ? 10'd3  : 10'd16;
    localparam [9:0] WALL_T = (FRAME_W == 64) ? 10'd1 : 10'd8;
    wire arena_border =
        (FRAME_W == 64) ?
            ((h_count < WALL_T) || (h_count >= (FRAME_W[9:0] - WALL_T)) ||
             (v_count < WALL_T) || (v_count >= (FRAME_H[9:0] - WALL_T))) :
            // Visible full-size borders are 8 pixels thick. During active
            // video, x=0..7/632..639 and y=0..7/472..479 are fixed bit slices.
            ((h_count[9:3] == 7'd0)  || (h_count[9:3] == 7'd79) ||
             (v_count[9:3] == 7'd0)  || (v_count[9:3] == 7'd59));
    // Full-size hardware uses a 3x2 grid aligned to 128-pixel blocks:
    // x=128..511, y=128..383. That preserves the same lobby feature while
    // replacing several arbitrary-coordinate comparators with cheap bit tests.
    wire lobby_palette =
        (FRAME_W == 64) ?
            ((h_count >= 10'd12) && (h_count < 10'd52) &&
             (v_count >= 10'd8)  && (v_count < 10'd40)) :
            (!h_count[9] && (h_count[8:7] != 2'd0) &&
             (v_count[8:7] != 2'd0) && (v_count[8:7] != 2'd3));
    wire [1:0] palette_col =
        (FRAME_W == 64) ? ((h_count < 10'd25) ? 2'd0 :
                           ((h_count < 10'd39) ? 2'd1 : 2'd2)) :
                          {h_count[8] & h_count[7], h_count[8] & ~h_count[7]};
    wire palette_row = (FRAME_W == 64) ? (v_count >= 10'd24) : v_count[8];
    wire [2:0] palette_color =
        (FRAME_W == 64) ? (palette_row ? ({1'b0, palette_col} + 3'd3) :
                                         {1'b0, palette_col}) :
                          {palette_row & (palette_col[1] | palette_col[0]),
                           (palette_row ? ~(palette_col[1] | palette_col[0]) : palette_col[1]),
                           (palette_col[0] ^ palette_row)};
    // Side bars only appear once that player has locked a colour.
    wire p1_side = lobby_active && p1_selected &&
                   ((FRAME_W == 64) ? (h_count < SIDE_T) : (h_count[9:4] == 6'd0));
    wire p2_side = lobby_active && p2_selected &&
                   ((FRAME_W == 64) ? (h_count >= (FRAME_W[9:0] - SIDE_T)) :
                                      (h_count[9:4] == 6'd39));
    // Each palette cell owns all four of its borders, drawn just inside the
    // cell so every border pixel maps (via palette_color) back to that same
    // cell. The right/bottom insets are what fix the old clipping: without
    // them the shared divider lines counted as the neighbouring cell, so the
    // highlight box only showed on its left and top sides.
    wire palette_grid_edge =
        (FRAME_W == 64) ?
            (((h_count >= 10'd12) && (h_count < 10'd13)) ||
             ((h_count >= 10'd24) && (h_count < 10'd25)) ||
             ((h_count >= 10'd25) && (h_count < 10'd26)) ||
             ((h_count >= 10'd38) && (h_count < 10'd39)) ||
             ((h_count >= 10'd39) && (h_count < 10'd40)) ||
             ((h_count >= 10'd51) && (h_count < 10'd52)) ||
            ((v_count >= 10'd8)  && (v_count < 10'd9))  ||
             ((v_count >= 10'd23) && (v_count < 10'd24)) ||
             ((v_count >= 10'd24) && (v_count < 10'd25)) ||
             ((v_count >= 10'd39) && (v_count < 10'd40))) :
            (lobby_palette &&
             ((h_count[6:2] == 5'd0) || (h_count[6:2] == 5'd31) ||
              (v_count[6:2] == 5'd0) || (v_count[6:2] == 5'd31)));
    wire palette_border = lobby_active && !clear_active && lobby_palette && palette_grid_edge;
    // White box = where each player's cursor is hovering (pick_id).
    wire cursor_border =
        palette_border &&
        ((palette_color == p1_pick_id) || (palette_color == p2_pick_id));
    // Black box = the colour each player has actually locked in (color_id).
    // A player-coloured marker would disappear on its own swatch; black stays
    // visible on all six bright colours and reuses the cursor geometry.
    wire confirm_border =
        palette_border &&
        ((p1_selected && palette_color == p1_color_id) ||
         (p2_selected && palette_color == p2_color_id));
    wire [2:0] trail_color =
        (pixel_color == 2'b01) ? p1_color_id :
        (pixel_color == 2'b10) ? p2_color_id : 3'd0;
    wire [2:0] lobby_color =
        p1_side ? p1_color_id :
        (p2_side ? p2_color_id : palette_color);
    wire boost_flash_pixel =
        boost_flash_phase && !lobby_active && !game_over &&
        ((p1_boost && pixel_color == 2'b01) ||
         (p2_boost && pixel_color == 2'b10));
    wire [2:0] shown_color =
        lobby_active ? lobby_color :
        (arena_border ? (game_over ? winner_color : 3'd6) : trail_color);
    wire shown_on =
        clear_active ? 1'b0 :
        (lobby_active ? (lobby_palette || p1_side || p2_side) :
        (arena_border || (pixel_color != 2'b00)));
    function [2:0] color_rgb;
        input [2:0] color_id;
        begin
            case (color_id)
                3'd0: color_rgb = 3'b100;
                3'd1: color_rgb = 3'b010;
                3'd2: color_rgb = 3'b001;
                3'd3: color_rgb = 3'b110;
                3'd4: color_rgb = 3'b011;
                3'd5: color_rgb = 3'b101;
                default: color_rgb = 3'b111;
            endcase
        end
    endfunction
    wire [2:0] rgb = color_rgb(shown_color) ^ {3{boost_flash_pixel}};
    // Build the final 3-bit color once, then duplicate each bit for 2-bit VGA.
    // Priority: cursor box (white) over locked-colour marker (black) over
    // normal content.
    wire [2:0] out_rgb =
        (!active_video || !shown_on) ? 3'b000 :
        (cursor_border ? 3'b111 :
        (confirm_border ? 3'b000 : rgb));
    wire [1:0] vga_r = {2{out_rgb[2]}};
    wire [1:0] vga_g = {2{out_rgb[1]}};
    wire [1:0] vga_b = {2{out_rgb[0]}};
    assign uo_out = {hsync, vga_b[0], vga_g[0], vga_r[0], vsync, vga_b[1], vga_g[1], vga_r[1]};

    // uio: QSPI PSRAM PMOD
    // [0]=FLASH_CSn [1]=IO0 [2]=IO1 [3]=SCK [4]=IO2 [5]=IO3 [6]=PSRAM_A_CSn [7]=PSRAM_B_CSn
    assign psram_sio_in = {uio_in[5], uio_in[4], uio_in[2], uio_in[1]};
    assign uio_out = {1'b1, psram_ce_n, psram_sio_out[3], psram_sio_out[2],
                      psram_sclk, psram_sio_out[1], psram_sio_out[0], 1'b1};
    assign uio_oe  = {1'b1, 1'b1, psram_sio_oe[3], psram_sio_oe[2],
                      1'b1, psram_sio_oe[1], psram_sio_oe[0], 1'b1};

endmodule
