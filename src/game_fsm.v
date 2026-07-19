/*
 * SPDX-FileCopyrightText: 2026 Joel Kaplan and Amit Elmaliach
 * SPDX-License-Identifier: Apache-2.0
 */

module game_fsm #(
    parameter integer FRAME_W  = 640,
    parameter integer FRAME_H  = 480,
    parameter integer START1_X = 100,
    parameter integer START2_X = 540,
    parameter integer START_Y  = 240,
    parameter integer BURST_BYTES = 8,
    parameter integer DATA_WIDTH  = 8 * BURST_BYTES
) (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        p1_left,
    input  wire        p1_right,
    input  wire        p2_left,
    input  wire        p2_right,
    input  wire        p1_boost,
    input  wire        p2_boost,
    input  wire        p1_menu_start,
    input  wire        p2_menu_start,
    input  wire        p1_menu_select,  // Select button: deselect this player's colour
    input  wire        p2_menu_select,
    input  wire        p1_pick_col,
    input  wire        p1_pick_col_inc,  // 1 = right (next colour), 0 = left (prev)
    input  wire        p1_pick_row,
    input  wire        p1_pick_select,
    input  wire        p2_pick_col,
    input  wire        p2_pick_col_inc,
    input  wire        p2_pick_row,
    input  wire        p2_pick_select,
    input  wire        vblank,
    input  wire        frame_start,

    output wire        game_req,
    output wire        game_we,
    output wire [16:0] game_addr,
    output wire [DATA_WIDTH-1:0] game_wdata,
    input  wire [DATA_WIDTH-1:0] game_rdata,
    input  wire        game_ack,

    output wire        game_over,
    output wire [2:0]  winner_color,
    output reg  [2:0]  p1_color_id,
    output reg  [2:0]  p2_color_id,
    output reg  [2:0]  p1_pick_id,
    output reg  [2:0]  p2_pick_id,
    output reg         p1_selected,   // high once the player has locked a colour
    output reg         p2_selected,
    output wire        lobby_active,
    output wire        clear_active,
    // Live head positions for the display-side head markers. head_on is gated
    // by gameplay state here because the alive flags are intentionally
    // reset-free and may be undefined before the first game starts.
    output wire [9:0]  p1_head_x,
    output wire [8:0]  p1_head_y,
    output wire [9:0]  p2_head_x,
    output wire [8:0]  p2_head_y,
    output wire        p1_head_on,
    output wire        p2_head_on
);

    // Movement uses Q10.6 fixed point: 10 integer screen bits and 6 fraction
    // bits. One pixel per frame is therefore +/-64 in the velocity table.
    localparam integer FRAC_BITS = 6;
    localparam [5:0] TURN_RATE = 6'd1;  // Smallest angle step

    // Four 2-bit pixels are packed into each byte of the framebuffer.
    localparam [9:0] WALL_T = (FRAME_W == 64) ? 10'd1 : 10'd8;
    localparam [9:0] WALL_MAX_X = FRAME_W[9:0] - WALL_T;
    localparam [9:0] WALL_MAX_Y = FRAME_H[9:0] - WALL_T;
    localparam [13:0] FRAME_BURSTS_COUNT = (FRAME_W == 64) ? 14'd128 : 14'd9600;

    // FSM states. The curved movement calculation is split across several
    // vblank cycles so the ASIC only has a short logic path at 50 MHz.
    localparam [2:0] S_LOBBY = 3'd0;
    localparam [2:0] S_OVER  = 3'd1;
    localparam [2:0] IDLE    = 3'd2;
    localparam [2:0] ANGLE   = 3'd3;
    localparam [2:0] CHECK   = 3'd4;
    localparam [2:0] READ    = 3'd5;
    localparam [2:0] WRITE   = 3'd6;
    localparam [2:0] S_CLEAR = 3'd7;

    reg [2:0]  state;
    reg [13:0] clear_burst;
    // Per-player trail-distance counters keep the holes the same physical
    // size and spacing at normal and boosted speed.  A counter advances once
    // for every trail pixel processed, including both pixels of a diagonal
    // fill.  The initial half-period offset keeps the players phase shifted.
    reg [7:0]  p1_gap_counter;
    reg [7:0]  p2_gap_counter;
    // Each 256-pixel period ends with a 32-pixel passable gap. Keep the
    // decode near the counters so it can also gate the display-only marker.
    wire p1_gap = p1_gap_counter[7] && p1_gap_counter[6] && p1_gap_counter[5];
    wire p2_gap = p2_gap_counter[7] && p2_gap_counter[6] && p2_gap_counter[5];

    // True fixed-point player positions.
    reg [15:0] p1_x_fp;
    reg [14:0] p1_y_fp;
    reg [15:0] p2_x_fp;
    reg [14:0] p2_y_fp;

    // The last committed fixed-point position always contains the last pixel
    // written to RAM. Diagonal side-fill pixels are emitted before commit.
    wire [9:0] p1_draw_x = p1_x_fp[15:FRAC_BITS];
    wire [8:0] p1_draw_y = p1_y_fp[14:FRAC_BITS];

    assign p1_head_x = p1_draw_x;
    assign p1_head_y = p1_draw_y;
    assign p2_head_x = p2_x_fp[15:FRAC_BITS];
    assign p2_head_y = p2_y_fp[14:FRAC_BITS];

    // 64 directions: 0=right, 16=down, 32=left, 48=up.
    reg [5:0] p1_angle;
    reg [5:0] p2_angle;
    reg signed [7:0] move_dx;
    reg signed [7:0] move_dy;
    reg       p1_alive;
    reg       p2_alive;
    reg       active_player;  // 0 = player 1, 1 = player 2
    reg       boost_used;     // A gives one extra normal move per frame
    reg       turn_phase;  // Toggles each frame; only one phase updates angle.
    reg       p1_menu_start_prev;
    reg       p2_menu_start_prev;
    reg       p1_menu_select_prev;
    reg       p2_menu_select_prev;
    reg       p1_pick_col_prev;
    reg       p1_pick_row_prev;
    reg       p1_pick_select_prev;
    reg       p2_pick_col_prev;
    reg       p2_pick_row_prev;
    reg       p2_pick_select_prev;

    // Current pixel to check/write, plus an optional second pixel for diagonal
    // movement. This is a tiny two-step line fill, not a full Bresenham engine.
    reg       fill_has_second;

    wire state_lobby = (state == S_LOBBY);
    wire state_over  = (state == S_OVER);
    wire state_read  = (state == READ);
    wire state_write = (state == WRITE);
    wire state_clear = (state == S_CLEAR);

    assign lobby_active = state_lobby || state_clear;
    assign clear_active = state_clear;
    // Solid trail pixels already reveal the head through the framebuffer.
    // The display overlay is needed only while trail writes are suppressed.
    assign p1_head_on = p1_alive && p1_gap && !state_lobby && !state_over && !state_clear;
    assign p2_head_on = p2_alive && p2_gap && !state_lobby && !state_over && !state_clear;
    assign game_over = state_over;
    // In game-over state, exactly one alive bit means that player won.
    // Both dead means a draw, so the border stays white.
    assign winner_color = p1_alive ? p1_color_id : (p2_alive ? p2_color_id : 3'd6);
    assign game_we = (state_write && vblank) ||
                     (state_clear && (clear_burst != FRAME_BURSTS_COUNT));
    assign game_req = (state_read && vblank) || game_we;

    wire p1_start_pulse      = p1_menu_start && !p1_menu_start_prev;
    wire p2_start_pulse      = p2_menu_start && !p2_menu_start_prev;
    // Both players must have locked a colour; then a single Start press from
    // either player begins the game. No separate ready handshake is needed.
    wire both_selected       = p1_selected && p2_selected;
    wire start_now           = both_selected && (p1_start_pulse || p2_start_pulse);
    // Select (per player) clears that player's colour lock.
    wire p1_menu_select_pulse = p1_menu_select && !p1_menu_select_prev;
    wire p2_menu_select_pulse = p2_menu_select && !p2_menu_select_prev;
    wire p1_pick_col_pulse   = p1_pick_col && !p1_pick_col_prev;
    wire p1_pick_row_pulse   = p1_pick_row && !p1_pick_row_prev;
    wire p1_pick_sel_pulse   = p1_pick_select && !p1_pick_select_prev;
    wire p2_pick_col_pulse   = p2_pick_col && !p2_pick_col_prev;
    wire p2_pick_row_pulse   = p2_pick_row && !p2_pick_row_prev;
    wire p2_pick_sel_pulse   = p2_pick_select && !p2_pick_select_prev;
    wire p1_pick_can_lock    = !(p2_selected && p1_pick_id == p2_color_id);
    wire p2_pick_can_lock    = !(p1_selected && p2_pick_id == p1_color_id);
    // If both players claim the same currently free colour on one clock,
    // reserve it for P1 and leave P2 unconfirmed so the UI never silently
    // changes a player's selection when the round starts.
    wire simultaneous_color_claim =
        p1_pick_sel_pulse && p2_pick_sel_pulse && p1_pick_can_lock &&
        (p1_pick_id == p2_pick_id);

    function [2:0] pick_col_step;
        input [2:0] pick_id;
        input       inc;
        begin
            case ({inc, pick_id})
                4'd0: pick_col_step = 3'd2;  // left from 0 wraps to 2
                4'd1: pick_col_step = 3'd0;
                4'd2: pick_col_step = 3'd1;
                4'd3: pick_col_step = 3'd5;
                4'd4: pick_col_step = 3'd3;
                4'd5: pick_col_step = 3'd4;
                4'd8: pick_col_step = 3'd1;  // right from 0 goes to 1
                4'd9: pick_col_step = 3'd2;
                4'd10: pick_col_step = 3'd0;
                4'd11: pick_col_step = 3'd4;
                4'd12: pick_col_step = 3'd5;
                default: pick_col_step = 3'd3;
            endcase
        end
    endfunction

    task start_new_game;
        begin
            clear_burst   <= 14'd0;
            p1_gap_counter <= 8'd0;
            p2_gap_counter <= 8'd128;
            p1_alive      <= 1'b1;
            p2_alive      <= 1'b1;
            p1_x_fp       <= {START1_X[9:0], {FRAC_BITS{1'b0}}};
            p1_y_fp       <= {START_Y[8:0],  {FRAC_BITS{1'b0}}};
            p2_x_fp       <= {START2_X[9:0], {FRAC_BITS{1'b0}}};
            p2_y_fp       <= {START_Y[8:0],  {FRAC_BITS{1'b0}}};
            p1_angle      <= 6'd0;
            p2_angle      <= 6'd32;
            active_player <= 1'b0;
            boost_used    <= 1'b0;
            turn_phase    <= 1'b0;
            if (p1_color_id == p2_color_id)
                p2_color_id <= (p2_color_id == 3'd5) ? 3'd0 : (p2_color_id + 3'd1);
            // Keep the lobby overlay up while S_CLEAR erases old trails.
            // S_CLEAR switches to PLAY only after the framebuffer is clean.
            state         <= S_CLEAR;
        end
    endtask

    // -------------------------------------------------------------------------
    // Shared angle-to-vector decoder
    // -------------------------------------------------------------------------
    // Only one quadrant is stored. The top two angle bits mirror/swap/sign it
    // into all four quadrants, saving ROM/logic compared with a 64-entry table.
    wire active_left = active_player ? p2_left : p1_left;
    wire active_right = active_player ? p2_right : p1_right;
    wire active_boost = active_player ? p2_boost : p1_boost;
    wire [1:0] active_color = {active_player, ~active_player};
    wire [5:0] selected_angle = active_player ? p2_angle : p1_angle;
    wire steer_left = turn_phase && active_left && !active_right;
    wire steer_right = turn_phase && active_right && !active_left;
    wire [5:0] steered_angle = steer_left  ? (selected_angle - TURN_RATE) :
                               steer_right ? (selected_angle + TURN_RATE) :
                                             selected_angle;
    reg [6:0] base_c;
    reg [6:0] base_s;
    reg signed [7:0] vec_dx;
    reg signed [7:0] vec_dy;

    always @(*) begin
        case (steered_angle[3:0])
            4'd0:  begin base_c = 7'd64; base_s = 7'd0;  end
            4'd1:  begin base_c = 7'd64; base_s = 7'd6;  end
            4'd2:  begin base_c = 7'd63; base_s = 7'd12; end
            4'd3:  begin base_c = 7'd61; base_s = 7'd19; end
            4'd4:  begin base_c = 7'd59; base_s = 7'd24; end
            4'd5:  begin base_c = 7'd56; base_s = 7'd30; end
            4'd6:  begin base_c = 7'd53; base_s = 7'd36; end
            4'd7:  begin base_c = 7'd49; base_s = 7'd41; end
            4'd8:  begin base_c = 7'd45; base_s = 7'd45; end
            4'd9:  begin base_c = 7'd41; base_s = 7'd49; end
            4'd10: begin base_c = 7'd36; base_s = 7'd53; end
            4'd11: begin base_c = 7'd30; base_s = 7'd56; end
            4'd12: begin base_c = 7'd24; base_s = 7'd59; end
            4'd13: begin base_c = 7'd19; base_s = 7'd61; end
            4'd14: begin base_c = 7'd12; base_s = 7'd63; end
            default: begin base_c = 7'd6; base_s = 7'd64; end
        endcase

        case (steered_angle[5:4])
            2'd0: begin vec_dx =  {1'b0, base_c}; vec_dy =  {1'b0, base_s}; end
            2'd1: begin vec_dx = -{1'b0, base_s}; vec_dy =  {1'b0, base_c}; end
            2'd2: begin vec_dx = -{1'b0, base_c}; vec_dy = -{1'b0, base_s}; end
            default: begin vec_dx =  {1'b0, base_s}; vec_dy = -{1'b0, base_c}; end
        endcase
    end

    wire signed [15:0] prep_dx_ext = {{8{move_dx[7]}}, move_dx};
    wire signed [15:0] prep_dy_ext = {{8{move_dy[7]}}, move_dy};
    wire [15:0] active_x_fp = active_player ? p2_x_fp : p1_x_fp;
    wire [14:0] active_y_fp = active_player ? p2_y_fp : p1_y_fp;
    wire [15:0] calc_next_x_fp = active_x_fp + prep_dx_ext;
    wire [15:0] calc_next_y_fp = {1'b0, active_y_fp} + prep_dy_ext;
    wire [9:0] calc_next_x = calc_next_x_fp[15:FRAC_BITS];
    wire [8:0] calc_next_y = calc_next_y_fp[14:FRAC_BITS];
    // Full-size walls are 8-pixel strips. Since every move is checked one
    // pixel at a time, a player reaches the strip before they could pass it.
    wire hit_wall =
        (FRAME_W == 64) ?
            (calc_next_x < WALL_T || calc_next_x >= WALL_MAX_X ||
             calc_next_y < WALL_T[8:0] || calc_next_y >= WALL_MAX_Y[8:0]) :
            ((calc_next_x[9:3] == 7'd0)  || (calc_next_x[9:3] == 7'd79) ||
             (calc_next_y[8:3] == 6'd0)  || (calc_next_y[8:3] == 6'd59));

    // -------------------------------------------------------------------------
    // PSRAM packed-pixel address calculation
    // -------------------------------------------------------------------------
    // Supported builds use 640-wide VGA or the tiny 64-wide simulation mode.
    // Build the row byte offset with shifts so ASIC synthesis has no multiply.
    // For diagonal movement, fill_has_second selects the side pixel's old Y;
    // after that write it clears, so the second pass naturally uses endpoint Y.
    wire [9:0] active_draw_x = active_x_fp[15:FRAC_BITS];
    wire [8:0] active_draw_y = active_y_fp[14:FRAC_BITS];
    wire [8:0] target_y = fill_has_second ? active_draw_y : calc_next_y;
    wire [16:0] target_row_byte_addr =
        (FRAME_W == 64) ? {3'd0, target_y, 4'b0} :
                          ({target_y, 7'b0} + {target_y, 5'b0});
    // calc_next_x is stable through READ/WRITE because the movement pipeline
    // does not advance until the next ANGLE state; no fill_x register needed.
    wire [16:0] target_burst_base_addr =
        target_row_byte_addr + {9'd0, calc_next_x[9:5], 3'b000};
    wire [2:0] target_byte_sel = calc_next_x[4:2];
    wire [1:0] target_pair_sel = calc_next_x[1:0];

    assign game_addr = state_clear ? {clear_burst, 3'b000} :
                                     target_burst_base_addr;

    function [7:0] burst_byte;
        input [DATA_WIDTH-1:0] burst_data;
        input [2:0] byte_sel;
        begin
            burst_byte = burst_data[{byte_sel, 3'b000} +: 8];
        end
    endfunction

    function [1:0] pixel_from_byte;
        input [7:0] byte_data;
        input [1:0] pair_sel;
        begin
            pixel_from_byte = byte_data[{pair_sel, 1'b0} +: 2];
        end
    endfunction

    function [7:0] patch_pixel_byte;
        input [7:0] byte_data;
        input [1:0] pair_sel;
        input [1:0] color;
        begin
            patch_pixel_byte = byte_data;
            patch_pixel_byte[{pair_sel, 1'b0} +: 2] = color;
        end
    endfunction

    function [DATA_WIDTH-1:0] patch_burst_byte;
        input [DATA_WIDTH-1:0] burst_data;
        input [2:0] byte_sel;
        input [7:0] byte_data;
        begin
            patch_burst_byte = burst_data;
            patch_burst_byte[{byte_sel, 3'b000} +: 8] = byte_data;
        end
    endfunction

    wire [7:0] target_byte_data = burst_byte(game_rdata, target_byte_sel);
    wire [1:0] target_pixel_data = pixel_from_byte(target_byte_data, target_pair_sel);
    // Each 256-pixel period ends with a 32-pixel passable gap. The bit
    // expression below is exactly counter >= 224, without putting a wide
    // comparator on the write path.
    wire active_gap = active_player ? p2_gap : p1_gap;
    // During a gap, patch the selected pixel back to the value just read.
    // This is equivalent to writing the whole burst back unchanged, but keeps
    // the gap select out of a timing-critical DATA_WIDTH-bit output mux.
    wire [1:0] trail_write_color = active_gap ? target_pixel_data : active_color;
    wire [DATA_WIDTH-1:0] active_patched_wdata =
        patch_burst_byte(game_rdata, target_byte_sel,
                         patch_pixel_byte(target_byte_data, target_pair_sel, trail_write_color));
    assign game_wdata = state_clear ? {DATA_WIDTH{1'b0}} :
                                      active_patched_wdata;

    // -------------------------------------------------------------------------
    // Main FSM
    // -------------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state               <= S_LOBBY;
            clear_burst         <= 14'd0;
            p1_color_id         <= 3'd0;
            p2_color_id         <= 3'd1;
            p1_pick_id          <= 3'd0;
            p2_pick_id          <= 3'd1;
            p1_selected         <= 1'b0;
            p2_selected         <= 1'b0;
            p1_menu_start_prev  <= 1'b0;
            p2_menu_start_prev  <= 1'b0;
            p1_menu_select_prev <= 1'b0;
            p2_menu_select_prev <= 1'b0;
            p1_pick_col_prev    <= 1'b0;
            p1_pick_row_prev    <= 1'b0;
            p1_pick_select_prev <= 1'b0;
            p2_pick_col_prev    <= 1'b0;
            p2_pick_row_prev    <= 1'b0;
            p2_pick_select_prev <= 1'b0;
            move_dx             <= 8'sd0;
            move_dy             <= 8'sd0;
        end else begin
            p1_menu_start_prev  <= p1_menu_start;
            p2_menu_start_prev  <= p2_menu_start;
            p1_menu_select_prev <= p1_menu_select;
            p2_menu_select_prev <= p2_menu_select;
            p1_pick_col_prev    <= p1_pick_col;
            p1_pick_row_prev    <= p1_pick_row;
            p1_pick_select_prev <= p1_pick_select;
            p2_pick_col_prev    <= p2_pick_col;
            p2_pick_row_prev    <= p2_pick_row;
            p2_pick_select_prev <= p2_pick_select;

            case (state)
                S_LOBBY: begin
                    // The lobby is a VGA overlay. The D-pad moves through
                    // a 3x2 palette; A confirms if the color is free.
                    if (p1_pick_col_pulse)
                        p1_pick_id <= pick_col_step(p1_pick_id, p1_pick_col_inc);
                    if (p1_pick_row_pulse)
                        p1_pick_id <= (p1_pick_id < 3'd3) ? (p1_pick_id + 3'd3) : (p1_pick_id - 3'd3);
                    if (p2_pick_col_pulse)
                        p2_pick_id <= pick_col_step(p2_pick_id, p2_pick_col_inc);
                    if (p2_pick_row_pulse)
                        p2_pick_id <= (p2_pick_id < 3'd3) ? (p2_pick_id + 3'd3) : (p2_pick_id - 3'd3);
                    // A locks the hovered colour, unless the *other* player
                    // has already locked that same colour.
                    if (p1_pick_sel_pulse && p1_pick_can_lock) begin
                        p1_color_id <= p1_pick_id;
                        p1_selected <= 1'b1;
                    end
                    if (p2_pick_sel_pulse && p2_pick_can_lock &&
                        !simultaneous_color_claim) begin
                        p2_color_id <= p2_pick_id;
                        p2_selected <= 1'b1;
                    end
                    // Select deselects that player's colour, which blocks
                    // starting until they lock a colour again.
                    if (p1_menu_select_pulse)
                        p1_selected <= 1'b0;
                    if (p2_menu_select_pulse)
                        p2_selected <= 1'b0;
                    // Both players locked in => a single Start press goes.
                    if (start_now)
                        start_new_game;
                end

                S_OVER: begin
                    // Select returns to the lobby and drops that player's
                    // colour lock, so they must re-pick before a restart.
                    if (p1_menu_select_pulse || p2_menu_select_pulse) begin
                        state        <= S_LOBBY;
                        if (p1_menu_select_pulse)
                            p1_selected <= 1'b0;
                        if (p2_menu_select_pulse)
                            p2_selected <= 1'b0;
                    end else if (start_now) begin
                        // Both colours still locked: a single Start rematches.
                        start_new_game;
                    end
                end

                IDLE: begin
                    if (frame_start) begin
                        turn_phase <= ~turn_phase;
                        active_player <= 1'b0;
                        boost_used <= 1'b0;
                        if (p1_alive) begin
                            state <= ANGLE;
                        end else if (p2_alive) begin
                            active_player <= 1'b1;
                            boost_used <= 1'b0;
                            state <= ANGLE;
                        end
                    end
                end

                ANGLE: begin
                    if (!vblank) begin
                        state <= IDLE;
                    end else begin
                        // Update only the selected player's angle. Position is
                        // committed later, once the move is known to be valid.
                        if (!active_player) begin
                            if (steer_left)
                                p1_angle <= p1_angle - TURN_RATE;
                            else if (steer_right)
                                p1_angle <= p1_angle + TURN_RATE;
                        end else begin
                            if (steer_left)
                                p2_angle <= p2_angle - TURN_RATE;
                            else if (steer_right)
                                p2_angle <= p2_angle + TURN_RATE;
                        end
                        // Register this move's decoded vector before the long
                        // position/address/RAM/collision cone. This keeps the
                        // high-fanout player and angle selectors off that path.
                        move_dx <= vec_dx;
                        move_dy <= vec_dy;
                        state <= CHECK;
                    end
                end

                CHECK: begin
                    if (!vblank) begin
                        state <= IDLE;
                    end else begin
                        if (hit_wall) begin
                            if (!active_player) begin
                                p1_alive <= 1'b0;
                                // P1 moved first this frame. Let P2 take the
                                // same-frame breaker move before deciding the
                                // result; if P2 also dies it becomes a draw.
                                if (p2_alive) begin
                                    active_player <= 1'b1;
                                    boost_used <= 1'b0;
                                    state <= ANGLE;
                                end else begin
                                    state     <= S_OVER;
                                end
                            end else begin
                                p2_alive <= 1'b0;
                                state     <= S_OVER;
                            end
                        end else if (calc_next_x == active_draw_x && calc_next_y == active_draw_y) begin
                            if (!active_player) begin
                                p1_x_fp <= calc_next_x_fp;
                                p1_y_fp <= calc_next_y_fp[14:0];
                            end else begin
                                p2_x_fp <= calc_next_x_fp;
                                p2_y_fp <= calc_next_y_fp[14:0];
                            end
                            // If the first mover died, the breaker move must
                            // finish the frame even when it stays inside the
                            // same integer pixel. Do not return to IDLE and
                            // grant the survivor an extra frame.
                            if ((!active_player && !p2_alive) ||
                                (active_player && !p1_alive)) begin
                                active_player <= 1'b0;
                                state <= S_OVER;
                            end else if (active_boost && !boost_used) begin
                                boost_used <= 1'b1;
                                state <= ANGLE;
                            end else if (!active_player && p2_alive) begin
                                active_player <= 1'b1;
                                boost_used <= 1'b0;
                                state <= ANGLE;
                            end else begin
                                active_player <= 1'b0;
                                state <= IDLE;
                            end
                        end else begin
                            if (calc_next_x != active_draw_x && calc_next_y != active_draw_y) begin
                                // Diagonal movement crosses a corner. Draw one
                                // side pixel first, then the endpoint, so the
                                // visible/collision trail has no holes.
                                fill_has_second <= 1'b1;
                            end else begin
                                fill_has_second <= 1'b0;
                            end
                            state <= READ;
                        end
                    end
                end

                READ: begin
                    if (!vblank) begin
                        state    <= IDLE;
                    end else begin
                        if (game_ack) begin
                            if (target_pixel_data != 2'b00) begin
                                if (!active_player) begin
                                    p1_alive <= 1'b0;
                                    // Same breaker as wall collision: P2 gets
                                    // its move before P1's crash becomes final.
                                    if (p2_alive) begin
                                        active_player <= 1'b1;
                                        boost_used <= 1'b0;
                                        state <= ANGLE;
                                    end else begin
                                    state     <= S_OVER;
                                    end
                                end else begin
                                    p2_alive <= 1'b0;
                                    // If P2 hits P1's just-written endpoint,
                                    // both players chose the same cell this
                                    // frame: draw. Old P1 trail still means
                                    // P1 wins.
                                    if (p1_alive && target_pixel_data == 2'b01 &&
                                        calc_next_x == p1_draw_x && target_y == p1_draw_y)
                                        p1_alive <= 1'b0;
                                    state     <= S_OVER;
                                end
                            end else begin
                                state      <= WRITE;
                            end
                        end
                    end
                end

                WRITE: begin
                    if (!vblank) begin
                        state    <= IDLE;
                    end else begin
                        if (game_ack) begin
                            // Count distance, not frames. Boosted moves and
                            // diagonal fills therefore keep identical gap
                            // length and spacing on the physical display.
                            if (active_player)
                                p2_gap_counter <= p2_gap_counter + 8'd1;
                            else
                                p1_gap_counter <= p1_gap_counter + 8'd1;
                            if (fill_has_second) begin
                                fill_has_second <= 1'b0;
                                state           <= READ;
                            end else begin
                                if (!active_player) begin
                                    p1_x_fp <= calc_next_x_fp;
                                    p1_y_fp <= calc_next_y_fp[14:0];
                                    if (active_boost && !boost_used && p2_alive) begin
                                        boost_used <= 1'b1;
                                        state <= ANGLE;
                                    end else if (p2_alive) begin
                                        active_player <= 1'b1;
                                        boost_used <= 1'b0;
                                        state <= ANGLE;
                                    end else begin
                                        active_player <= 1'b0;
                                        state <= IDLE;
                                    end
                                end else begin
                                    p2_x_fp <= calc_next_x_fp;
                                    p2_y_fp <= calc_next_y_fp[14:0];
                                    if (!p1_alive) begin
                                        state     <= S_OVER;
                                        active_player <= 1'b0;
                                    end else if (active_boost && !boost_used) begin
                                        boost_used <= 1'b1;
                                        state <= ANGLE;
                                    end else begin
                                        active_player <= 1'b0;
                                        state <= IDLE;
                                    end
                                end
                            end
                        end
                    end
                end

                S_CLEAR: begin
                    // Zero every burst in the framebuffer before the game starts.
                    if (clear_burst != FRAME_BURSTS_COUNT) begin
                        if (game_ack) begin
                            clear_burst <= clear_burst + 1'b1;
                        end
                    end else begin
                        clear_burst <= 14'd0;
                        state    <= IDLE;
                    end
                end

                default: begin
                    state    <= IDLE;
                end
            endcase
        end
    end

endmodule
