/*
 * SPDX-FileCopyrightText: 2026 Joel Kaplan and Amit Elmaliach
 * SPDX-License-Identifier: Apache-2.0
 */

module display_streamer #(
    parameter integer FRAME_W = 640,
    parameter integer FRAME_H = 480,
    parameter integer BURST_BYTES = 8,
    parameter integer DATA_WIDTH = 8 * BURST_BYTES
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        pixel_tick,
    input  wire [4:0]  pixel_idx,
    input  wire        active_video,
    input  wire        vblank,
    input  wire        frame_start,
    output reg         disp_req,
    output wire [16:0] disp_addr,
    input  wire [DATA_WIDTH-1:0] disp_rdata,
    input  wire        disp_ack,
    output wire [1:0]  pixel_color
);

    // Framebuffer is packed as 2 bits per pixel. With the fixed 8-byte burst,
    // h_count[4:0] is 31 on the last pixel of each 32-pixel burst.
    // Current display burst. The old design kept two full 64-bit buffers; this
    // register holds the burst actively being consumed by VGA.
    reg [DATA_WIDTH-1:0] display_shift;
    reg        display_shift_valid;
    // When set, disp_rdata/psram_rdata is being used as the next-burst holder.
    // This is only allowed outside vblank, where the display owns PSRAM.
    reg        next_burst_valid;
    // Byte address of the next burst to request from PSRAM.
    reg [13:0] next_fetch_burst;
    // A read launched for the burst after the last visible row can still be
    // in flight when frame_start rewinds the fetcher. Its completion must not
    // be mistaken for the freshly requested first burst, so frame_start arms
    // this flag whenever it interrupts an unanswered request, and the next
    // ack is dropped instead of loaded.
    reg        stale_read_pending;

    wire burst_last_pixel = &pixel_idx;
    assign pixel_color =
        (active_video && display_shift_valid) ?
        display_shift[{pixel_idx, 1'b0} +: 2] : 2'b00;
    wire display_read_done = disp_req && disp_ack && !stale_read_pending;
    wire current_burst_last_pixel =
        pixel_tick && active_video && display_shift_valid &&
        burst_last_pixel;
    wire [13:0] next_fetch_burst_after_done = next_fetch_burst + 1'b1;
    wire can_request_burst =
        !disp_req && (!display_shift_valid || (!vblank && !next_burst_valid));
    assign disp_addr = {next_fetch_burst, 3'b000};

    wire load_display_burst =
        display_read_done && (!display_shift_valid ||
                              (current_burst_last_pixel && !vblank)) ||
        (current_burst_last_pixel && next_burst_valid);

    // Wide pixel data does not need reset: display_shift_valid is reset and
    // gates all use of this register until a real PSRAM burst has been loaded.
    always @(posedge clk) begin
        if (rst_n && !frame_start) begin
            if (load_display_burst) begin
                display_shift <= disp_rdata;
            end
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            display_shift_valid <= 1'b0;
            next_burst_valid    <= 1'b0;
            next_fetch_burst    <= 14'd0;
            disp_req            <= 1'b0;
            stale_read_pending  <= 1'b0;
        end else begin
            if (frame_start) begin
                // End of visible frame: rewind the fetcher so the next frame
                // starts streaming again from the top-left pixel. Any pending
                // next burst in psram_rdata is discarded here so vblank game
                // reads are free to overwrite o_rdata.
                display_shift_valid <= 1'b0;
                next_burst_valid    <= 1'b0;
                next_fetch_burst    <= 14'd0;
                disp_req            <= 1'b0;
                stale_read_pending  <= disp_req && !disp_ack;
            end else begin
                if (disp_ack) begin
                    stale_read_pending <= 1'b0;
                end
                if (display_read_done) begin
                    disp_req        <= 1'b0;
                    next_fetch_burst <= next_fetch_burst_after_done;

                    if (!display_shift_valid) begin
                        // No current burst is being displayed, so copy the
                        // completed PSRAM read into the display shift register.
                        display_shift_valid <= 1'b1;
                        next_burst_valid    <= 1'b0;
                    end else if (!vblank && !current_burst_last_pixel) begin
                        // Keep the next burst in psram_rdata until the current
                        // burst is exhausted. Do this only outside vblank; in
                        // vblank the game may legitimately read PSRAM next.
                        next_burst_valid <= 1'b1;
                    end
                end else if (can_request_burst) begin
                    disp_req  <= 1'b1;
                end

                if (pixel_tick && active_video) begin
                    if (display_shift_valid) begin
                        if (burst_last_pixel) begin
                            if (next_burst_valid) begin
                                next_burst_valid    <= 1'b0;
                                disp_req            <= 1'b1;
                            end else if (display_read_done && !vblank) begin
                                next_burst_valid    <= 1'b0;
                                disp_req            <= 1'b1;
                            end else begin
                                display_shift_valid <= 1'b0;
                                next_burst_valid    <= 1'b0;
                            end
                        end
                    end
                end
            end
        end
    end

endmodule
