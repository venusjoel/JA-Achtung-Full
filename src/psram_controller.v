/*
 * SPDX-FileCopyrightText: 2026 Joel Kaplan and Amit Elmaliach
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns/1ps
// =============================================================================
// psram_controller.v -- APS6404L QPI PSRAM Controller
// =============================================================================
// Board: DE10-Lite  (Altera MAX 10 FPGA)
// RAM  : APS6404L-3SQR  64 Mb QPI PSRAM
// =============================================================================

module psram_controller #(
    parameter integer CLK_FREQ_HZ   = 50000000,
    parameter integer SCLK_FREQ_HZ  = 25000000,  // checked by this build; actual SCLK is clk/2
    parameter integer ADDR_WIDTH    = 17,
    parameter integer BURST_BYTES   = 8,
    parameter integer DATA_WIDTH    = 8 * BURST_BYTES
)(
    input  wire                   clk,
    input  wire                   rst_n,

    input  wire                   i_we,
    input  wire                   i_re,
    input  wire [ADDR_WIDTH-1:0]  i_addr,
    input  wire [DATA_WIDTH-1:0]  i_wdata,
    output reg  [DATA_WIDTH-1:0]  o_rdata,
    output reg                    o_valid,
    output wire                   o_busy,

    output reg                    o_ce_n,
    output reg                    o_sclk,
    output wire [3:0]             o_sio_out,
    output wire [3:0]             o_sio_oe,
    input  wire [3:0]             i_sio_in
);

// =============================================================================
// SIO tri-state helpers
// =============================================================================
reg  [3:0] sio_out_reg;
wire [3:0] sio_in;
reg  [3:0] sio_oe;

assign o_sio_out = sio_out_reg;
assign o_sio_oe  = sio_oe;
assign sio_in    = i_sio_in;

// This design is intentionally fixed at 8-byte bursts. The largest nibble
// count is 15, so 4 bits are enough; the old parameterized width used 5 bits.
localparam [3:0] WRITE_NIBBLES_LAST = 4'd15;  // 8-byte burst = 16 nibbles

// =============================================================================
// SCLK generation
// =============================================================================
// phase toggles every posedge clk, giving a 25 MHz SCLK from a 50 MHz system
// clock. o_sclk is registered so the external PSRAM clock is driven directly
// from a flop instead of through combinational clock-gating logic.
reg phase;
wire sclk_f =  phase;  // phase=1 -> SCLK falling
wire sclk_r = ~phase;  // phase=0 -> SCLK rising

function [3:0] addr_nibble;
    input [13:0] addr_burst;
    input [3:0] remaining;
    begin
        case (remaining)
            4'd5: addr_nibble = {3'b000, addr_burst[13]};
            4'd4: addr_nibble = addr_burst[12:9];
            4'd3: addr_nibble = addr_burst[8:5];
            4'd2: addr_nibble = addr_burst[4:1];
            default: addr_nibble = {addr_burst[0], 3'b000};
        endcase
    end
endfunction

function init_bit;
    input [7:0] cmd;
    input [2:0] bit_count;
    begin
        init_bit = (bit_count == 3'd0) ? 1'b0 : cmd[bit_count - 3'd1];
    end
endfunction

// =============================================================================
// State machine
// =============================================================================
localparam [3:0] S_INIT_QEXIT = 4'd10;
localparam [3:0] S_INIT_RSTEN = 4'd0;
localparam [3:0] S_INIT_RST   = 4'd1;
localparam [3:0] S_INIT_QUAD  = 4'd2;
localparam [3:0] S_GAP        = 4'd3;
localparam [3:0] S_IDLE       = 4'd4;
localparam [3:0] S_CMD        = 4'd5;
localparam [3:0] S_ADDR       = 4'd6;
localparam [3:0] S_WAIT       = 4'd7;
localparam [3:0] S_DATA_WR    = 4'd8;
localparam [3:0] S_DATA_RD    = 4'd9;
localparam [1:0] GN_RSTEN     = 2'd0;
localparam [1:0] GN_RST       = 2'd1;
localparam [1:0] GN_QUAD      = 2'd2;
localparam [1:0] GN_IDLE      = 2'd3;

reg [3:0] state;
reg [1:0] gap_next;

reg started;
reg is_read;
reg [3:0] nibble_cnt;
reg [2:0]  spi_bit_cnt;

reg [2:0]  gap_cnt;
reg [13:0] addr_burst_lat;
reg [3:0]  rx_hi_nibble;

wire [7:0] init_cmd =
    (state == S_INIT_RSTEN) ? 8'h66 :
    (state == S_INIT_RST)   ? 8'h99 :
                               8'h35;
assign o_busy = (state != S_IDLE);
// =============================================================================
// State machine body
// =============================================================================
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        state          <= S_INIT_QEXIT;
        started        <= 1'b0;
        o_ce_n         <= 1'b1;
        // The APS6404L power-up contract requires all SIO pins LOW while
        // CE# is HIGH and SCLK is LOW.  The board must hold rst_n low for at
        // least 150 us after PSRAM VDD is stable; actively drive the pins
        // here so they cannot float during that interval.
        sio_oe         <= 4'b1111;
        sio_out_reg    <= 4'b0000;
        o_valid        <= 1'b0;
        o_sclk         <= 1'b0;
        phase          <= 1'b0;
    end else begin
        phase   <= ~phase;
        o_sclk  <= (state != S_IDLE) ? ~phase : 1'b0;
        o_valid <= 1'b0;

        case (state)

        // QEXIT: send 0xF5 in QPI mode. This exits QPI if the chip was left
        // there by a previous load, then the normal SPI init sequence follows.
        S_INIT_QEXIT: begin
            if (!started) begin
                if (sclk_f) begin
                    started     <= 1'b1;
                    o_ce_n      <= 1'b0;
                    sio_oe      <= 4'b1111;
                    sio_out_reg <= 4'hF;
                    nibble_cnt  <= 4'd1;
                end
            end else begin
                if (sclk_f && nibble_cnt != 4'd0) begin
                    sio_out_reg <= 4'h5;
                    nibble_cnt  <= nibble_cnt - 1'b1;
                end
                if (sclk_r && nibble_cnt == 4'd0) begin
                    sio_oe   <= 4'b0000;
                    started  <= 1'b0;
                    state    <= S_GAP;
                    gap_next <= GN_RSTEN;
                    gap_cnt  <= 3'd1;
                end
            end
        end

        // INIT: send 0x66, 0x99, 0x35 in SPI mode on IO0.
        S_INIT_RSTEN,
        S_INIT_RST,
        S_INIT_QUAD: begin
            if (!started) begin
                if (sclk_f) begin
                    started       <= 1'b1;
                    o_ce_n        <= 1'b0;
                    sio_oe        <= 4'b0001;
                    sio_out_reg   <= {3'b000, init_cmd[7]};
                    spi_bit_cnt   <= 3'd7;
                end
            end

            if (started && sclk_f && spi_bit_cnt != 3'd0) begin
                sio_out_reg <= {3'b000, init_bit(init_cmd, spi_bit_cnt)};
                spi_bit_cnt <= spi_bit_cnt - 3'd1;
            end

            if (started && sclk_r && spi_bit_cnt == 3'd0) begin
                sio_oe  <= 4'b0000;
                started <= 1'b0;
                case (state)
                    S_INIT_RSTEN: begin
                        state    <= S_GAP;
                        gap_next <= GN_RST;
                        gap_cnt  <= 3'd0;
                    end
                    S_INIT_RST: begin
                        state    <= S_GAP;
                        gap_next <= GN_QUAD;
                        gap_cnt  <= 3'd7;
                    end
                    default: begin
                        state    <= S_GAP;
                        gap_next <= GN_IDLE;
                        gap_cnt  <= 3'd0;
                    end
                endcase
            end
        end

        // GAP: CE# high for at least one rising SCLK edge.
        S_GAP: begin
            o_ce_n <= 1'b1;
            sio_oe <= 4'b0000;
            if (sclk_r) begin
                if (gap_cnt == 3'd0) begin
                    case (gap_next)
                        GN_RSTEN: state <= S_INIT_RSTEN;
                        GN_RST:   state <= S_INIT_RST;
                        GN_QUAD:  state <= S_INIT_QUAD;
                        default:  state <= S_IDLE;
                    endcase
                end else begin
                    gap_cnt <= gap_cnt - 3'd1;
                end
            end
        end

        // IDLE: wait for host read/write request.
        S_IDLE: begin
            o_ce_n  <= 1'b1;
            sio_oe  <= 4'b0000;
            started <= 1'b0;
            if (i_we || i_re) begin
                addr_burst_lat <= i_addr[16:3];
                is_read  <= i_re & ~i_we;
                state    <= S_CMD;
            end
        end

        // CMD: send command byte (0x38 write / 0xEB read).
        S_CMD: begin
            if (!started) begin
                if (sclk_f) begin
                    started    <= 1'b1;
                    o_ce_n     <= 1'b0;
                    sio_oe     <= 4'b1111;
                    nibble_cnt <= 4'd1;
                    sio_out_reg <= {is_read, is_read, 1'b1, ~is_read};
                end
            end else if (sclk_f) begin
                if (nibble_cnt == 4'd0) begin
                    state       <= S_ADDR;
                    started     <= 1'b1;
                    nibble_cnt  <= 4'd5;
                    sio_out_reg <= 4'h0;
                end else begin
                    sio_out_reg <= {2'b10, is_read, is_read};
                    nibble_cnt  <= nibble_cnt - 4'd1;
                end
            end
        end

        // ADDR: send 24-bit address.
        S_ADDR: begin
            if (sclk_f) begin
                if (nibble_cnt == 4'd0) begin
                    if (is_read) begin
                        state      <= S_WAIT;
                        sio_oe     <= 4'b0000;
                        nibble_cnt <= 4'd5;
                    end else begin
                        state       <= S_DATA_WR;
                        started     <= 1'b1;
                        nibble_cnt  <= WRITE_NIBBLES_LAST;
                        // Reuse o_rdata as the write shifter. During writes
                        // the host only waits for o_valid, so this avoids a
                        // separate 64-bit mux for selecting i_wdata nibbles.
                        o_rdata     <= i_wdata;
                        sio_out_reg <= i_wdata[7:4];
                    end
                end else begin
                    sio_out_reg <= addr_nibble(addr_burst_lat, nibble_cnt);
                    nibble_cnt  <= nibble_cnt - 4'd1;
                end
            end
        end

        // WAIT: 6 dummy SCLK rising edges, SIO tristated.
        S_WAIT: begin
            sio_oe <= 4'b0000;
            if (sclk_f) begin
                if (nibble_cnt == 4'd0) begin
                    state          <= S_DATA_RD;
                    nibble_cnt     <= WRITE_NIBBLES_LAST;
                    o_rdata        <= {DATA_WIDTH{1'b0}};
                end else begin
                    nibble_cnt <= nibble_cnt - 4'd1;
                end
            end
        end

        // DATA_WR: send burst data.
        S_DATA_WR: begin
            if (sclk_f && nibble_cnt != 4'd0) begin
                if (!nibble_cnt[0]) begin
                    sio_out_reg <= o_rdata[7:4];
                end else begin
                    sio_out_reg <= o_rdata[3:0];
                    o_rdata     <= {{8{1'b0}}, o_rdata[DATA_WIDTH-1:8]};
                end
                nibble_cnt     <= nibble_cnt - 4'd1;
            end
            if (sclk_r && nibble_cnt == 4'd0) begin
                o_valid  <= 1'b1;
                started  <= 1'b0;
                state    <= S_GAP;
                gap_next <= GN_IDLE;
                gap_cnt  <= 3'd0;
            end
        end

        // DATA_RD: capture burst data.
        S_DATA_RD: begin
            sio_oe <= 4'b0000;
            if (sclk_r) begin
                if (nibble_cnt[0]) begin
                    rx_hi_nibble <= sio_in;
                end else begin
                    // PSRAM returns high nibble then low nibble for each byte.
                    // Shift completed bytes down so byte 0 ends in o_rdata[7:0].
                    o_rdata <= {{rx_hi_nibble, sio_in}, o_rdata[DATA_WIDTH-1:8]};
                end

                if (nibble_cnt == 4'd0) begin
                    o_valid  <= 1'b1;
                    state    <= S_GAP;
                    gap_next <= GN_IDLE;
                    gap_cnt  <= 3'd0;
                end else begin
                    nibble_cnt <= nibble_cnt - 4'd1;
                end
            end
        end

        default: state <= S_IDLE;

        endcase
end
end

endmodule
