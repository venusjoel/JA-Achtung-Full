`timescale 1ns/1ps
// Direct-RAM harness for the 2x1 (two-tile) game engine. The PSRAM
// controller, QSPI pins, VGA sync, and gamepad decoder are bypassed: the game
// FSM talks to a behavioral burst framebuffer with a short fixed-latency
// handshake, and vblank / frame_start / lobby buttons are driven straight
// from the cocotb test.
module tb_game_direct #(
    parameter integer FRAME_W  = 64,
    parameter integer FRAME_H  = 48,
    parameter integer START1_X = 10,
    parameter integer START2_X = 53,
    parameter integer START_Y  = 24
);
    localparam integer BURST_BYTES = 8;
    localparam integer DATA_WIDTH  = 8 * BURST_BYTES;
    localparam integer MEM_BYTES   = (FRAME_W == 64) ? 1024 : 76800;

    reg clk;
    reg rst_n;
    reg p1_left;
    reg p1_right;
    reg p2_left;
    reg p2_right;
    reg p1_boost;
    reg p2_boost;
    reg p1_menu_start;
    reg p2_menu_start;
    reg p1_menu_select;
    reg p2_menu_select;
    reg p1_pick_col;
    reg p1_pick_col_inc;
    reg p1_pick_row;
    reg p1_pick_select;
    reg p2_pick_col;
    reg p2_pick_col_inc;
    reg p2_pick_row;
    reg p2_pick_select;
    reg vblank;
    reg frame_start;

    wire        game_req;
    wire        game_we;
    wire [16:0] game_addr;
    wire [DATA_WIDTH-1:0] game_wdata;
    reg  [DATA_WIDTH-1:0] game_rdata;
    reg         game_ack;

    wire        game_over;
    wire [2:0]  winner_color;
    wire [2:0]  p1_color_id;
    wire [2:0]  p2_color_id;
    wire [2:0]  p1_pick_id;
    wire [2:0]  p2_pick_id;
    wire        p1_selected;
    wire        p2_selected;
    wire        lobby_active;
    wire        clear_active;

    game_fsm #(
        .FRAME_W(FRAME_W),
        .FRAME_H(FRAME_H),
        .START1_X(START1_X),
        .START2_X(START2_X),
        .START_Y(START_Y),
        .BURST_BYTES(BURST_BYTES),
        .DATA_WIDTH(DATA_WIDTH)
    ) u_engine (
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
        .clear_active(clear_active)
    );

    // Behavioral burst framebuffer with the same one-transaction-per-ack
    // handshake as the PSRAM controller: request seen on one edge, whole
    // 8-byte burst transferred with the ack on the next.
    reg [7:0] mem [0:MEM_BYTES-1];
    reg pending;

    integer i;
    initial begin
        for (i = 0; i < MEM_BYTES; i = i + 1)
            mem[i] = 8'h00;
    end

    integer j;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            game_ack <= 1'b0;
            pending  <= 1'b0;
        end else begin
            game_ack <= 1'b0;
            if (pending) begin
                if (game_we) begin
                    for (j = 0; j < BURST_BYTES; j = j + 1)
                        mem[game_addr + j] <= game_wdata[8*j +: 8];
                end else begin
                    for (j = 0; j < BURST_BYTES; j = j + 1)
                        game_rdata[8*j +: 8] <= mem[game_addr + j];
                end
                game_ack <= 1'b1;
                pending  <= 1'b0;
            end else if (game_req && !game_ack) begin
                pending <= 1'b1;
            end
        end
    end
endmodule
