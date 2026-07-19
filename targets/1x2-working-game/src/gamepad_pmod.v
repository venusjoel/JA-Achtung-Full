/*
 * Copyright (c) 2025 Pat Deegan
 * https://psychogenic.com
 * SPDX-License-Identifier: Apache-2.0
 *
 * Interfacing code for the Gamepad Pmod from Psycogenic Technologies,
 * designed for Tiny Tapeout.
 *
 * There are two high-level modules that most users will be interested in:
 * - gamepad_pmod_single: for a single controller;
 * - gamepad_pmod_dual: for two controllers.
 * 
 * There are also two lower-level modules that you can use if you want to
 * handle the interfacing yourself:
 * - gamepad_pmod_driver: interfaces with the Pmod and provides the raw data;
 * - gamepad_pmod_decoder: decodes the raw data into button states.
 *
 * The docs, schematics, PCB files, and firmware code for the Gamepad Pmod
 * are available at https://github.com/psychogenic/gamepad-pmod.
 */

/**
 * gamepad_pmod_driver -- Serial interface for the Gamepad Pmod.
 *
 * This module reads raw data from the Gamepad Pmod *serially*
 * and stores it in a shift register. When the latch signal is received, 
 * the data is transferred into `data_reg` for further processing.
 *
 * Functionality:
 *   - Synchronizes the `pmod_data`, `pmod_clk`, and `pmod_latch` signals 
 *     to the system clock domain.
 *   - Captures serial data on each falling edge of `pmod_clk`.
 *   - Transfers the shifted data into `data_reg` when `pmod_latch` goes low.
 *
 * Parameters:
 *   - `BIT_WIDTH`: Defines the width of `data_reg` (default: 24 bits).
 *
 * Inputs:
 *   - `rst_n`: Active-low reset.
 *   - `clk`: System clock.
 *   - `pmod_data`: Serial data input from the Pmod.
 *   - `pmod_clk`: Serial clock from the Pmod.
 *   - `pmod_latch`: Latch signal indicating the end of data transmission.
 *
 * Outputs:
 *   - `data_reg`: Captured parallel data after shifting is complete.
 */
module gamepad_pmod_driver #(
    parameter BIT_WIDTH = 24
) (
    input wire rst_n,
    input wire clk,
    input wire pmod_data,
    input wire pmod_clk,
    input wire pmod_latch,
    output reg [BIT_WIDTH-1:0] data_reg
);

  localparam [4:0] FRAME_BITS = BIT_WIDTH;

  reg [BIT_WIDTH-1:0] shift_reg;
  reg [4:0] bit_count;

  // Sync Pmod signals to the clk domain:
  (* async_reg = "true" *) reg [1:0] pmod_data_sync;
  (* async_reg = "true" *) reg [1:0] pmod_clk_sync;
  (* async_reg = "true" *) reg [1:0] pmod_latch_sync;
  reg pmod_clk_prev;
  reg pmod_latch_prev;

  wire pmod_clk_rise = pmod_clk_sync[1] & ~pmod_clk_prev;
  wire pmod_latch_rise = pmod_latch_sync[1] & ~pmod_latch_prev;

  always @(posedge clk) begin
    if (~rst_n) begin
      pmod_data_sync  <= 2'b0;
      pmod_clk_sync   <= 2'b0;
      pmod_latch_sync <= 2'b0;
      pmod_clk_prev   <= 1'b0;
      pmod_latch_prev <= 1'b0;
    end else begin
      pmod_data_sync  <= {pmod_data_sync[0], pmod_data};
      pmod_clk_sync   <= {pmod_clk_sync[0], pmod_clk};
      pmod_latch_sync <= {pmod_latch_sync[0], pmod_latch};
      pmod_clk_prev   <= pmod_clk_sync[1];
      pmod_latch_prev <= pmod_latch_sync[1];
    end
  end

  always @(posedge clk) begin
    if (~rst_n) begin
      /* set data and shift registers to all ones
       * such that it is detected as "not present" yet.
       */
      data_reg <= {BIT_WIDTH{1'b1}};
      shift_reg <= {BIT_WIDTH{1'b1}};
      bit_count <= 5'd0;
    end else begin
      // Capture data only after a complete serial frame.
      if (pmod_latch_rise) begin
        if (bit_count == FRAME_BITS) begin
          data_reg <= shift_reg;
        end
        bit_count <= 5'd0;
      end

      // Sample data on rising edge of pmod_clk:
      else if (pmod_clk_rise) begin
        shift_reg <= {shift_reg[BIT_WIDTH-2:0], pmod_data_sync[1]};
        if (bit_count != FRAME_BITS) begin
          bit_count <= bit_count + 5'd1;
        end
      end
    end
  end

endmodule


/**
 * gamepad_pmod_decoder -- Decodes raw data from the Gamepad Pmod.
 *
 * This module takes a 12-bit parallel data register (`data_reg`) 
 * and decodes it into individual button states. It also determines
 * whether a controller is connected.
 *
 * Functionality:
 *   - If `data_reg` contains all `1's` (`0xFFF`), it indicates that no controller is connected.
 *   - Otherwise, it extracts individual button states from `data_reg`.
 *
 * Inputs:
 *   - `data_reg [11:0]`: Captured button state data from the gamepad.
 *
 * Outputs:
 *   - `b, y, select, start, up, down, left, right, a, x, l, r`: Individual button states (`1` = pressed, `0` = released).
 *   - `is_present`: Indicates whether a controller is connected (`1` = connected, `0` = not connected).
 */
module gamepad_pmod_decoder (
    input wire [11:0] data_reg,
    output wire b,
    output wire y,
    output wire select,
    output wire start,
    output wire up,
    output wire down,
    output wire left,
    output wire right,
    output wire a,
    output wire x,
    output wire l,
    output wire r,
    output wire is_present
);

  // When the controller is not connected, the data register will be all 1's
  wire reg_empty = (data_reg == 12'hfff);
  assign is_present = !reg_empty;
  assign {b, y, select, start, up, down, left, right, a, x, l, r} =
      is_present ? data_reg : 12'b0;

endmodule


/**
 * gamepad_pmod_single -- Main interface for a single Gamepad Pmod controller.
 * 
 * This module provides button states for a **single controller**, reducing 
 * resource usage (fewer flip-flops) compared to a dual-controller version.
 * 
 * Inputs:
 *   - `pmod_data`, `pmod_clk`, and `pmod_latch` are the signals from the PMOD interface.
 * 
 * Outputs:
 *   - Each button's state is provided as a single-bit wire (e.g., `start`, `up`, etc.).
 *   - `is_present` indicates whether the controller is connected (`1` = connected, `0` = not detected).
 */
module gamepad_pmod_single (
    input wire rst_n,
    input wire clk,
    input wire pmod_data,
    input wire pmod_clk,
    input wire pmod_latch,

    output wire b,
    output wire y,
    output wire select,
    output wire start,
    output wire up,
    output wire down,
    output wire left,
    output wire right,
    output wire a,
    output wire x,
    output wire l,
    output wire r,
    output wire is_present
);

  wire [11:0] gamepad_pmod_data;

  gamepad_pmod_driver #(
      .BIT_WIDTH(12)
  ) driver (
      .rst_n(rst_n),
      .clk(clk),
      .pmod_data(pmod_data),
      .pmod_clk(pmod_clk),
      .pmod_latch(pmod_latch),
      .data_reg(gamepad_pmod_data)
  );

  gamepad_pmod_decoder decoder (
      .data_reg(gamepad_pmod_data),
      .b(b),
      .y(y),
      .select(select),
      .start(start),
      .up(up),
      .down(down),
      .left(left),
      .right(right),
      .a(a),
      .x(x),
      .l(l),
      .r(r),
      .is_present(is_present)
  );

endmodule


/**
 * gamepad_pmod_dual -- Main interface for the Pmod gamepad.
 * This module provides button states for two controllers using
 * 2-bit vectors for each button (e.g., start[1:0], up[1:0], etc.).
 * 
 * Each button state is represented as a 2-bit vector:
 *   - Index 0 corresponds to the first controller (e.g., up[0], y[0], etc.).
 *   - Index 1 corresponds to the second controller (e.g., up[1], y[1], etc.).
 *
 * The `is_present` signal indicates whether a controller is connected:
 *   - `is_present[0] == 1` when the first controller is connected.
 *   - `is_present[1] == 1` when the second controller is connected.
 *
 * Inputs:
 *   - `pmod_data`, `pmod_clk`, and `pmod_latch` are the 3 wires coming from the Pmod interface.
 *
 * Outputs:
 *   - Button state vectors for each controller.
 *   - Presence detection via `is_present`.
 */
module gamepad_pmod_dual (
    input wire rst_n,
    input wire clk,
    input wire pmod_data,
    input wire pmod_clk,
    input wire pmod_latch,

    output wire [1:0] select,
    output wire [1:0] start,
    output wire [1:0] up,
    output wire [1:0] down,
    output wire [1:0] left,
    output wire [1:0] right,
    output wire [1:0] a,
    output wire [1:0] l,
    output wire [1:0] r
);

  localparam [4:0] FRAME_BITS = 5'd24;

  reg [4:0] bit_count;
  (* async_reg = "true" *) reg [1:0] pmod_data_sync;
  (* async_reg = "true" *) reg [1:0] pmod_clk_sync;
  (* async_reg = "true" *) reg [1:0] pmod_latch_sync;
  reg pmod_clk_prev;
  reg pmod_latch_prev;

  wire pmod_clk_rise = pmod_clk_sync[1] & ~pmod_clk_prev;
  wire pmod_latch_rise = pmod_latch_sync[1] & ~pmod_latch_prev;

  // Pending frame bits for the buttons the game actually uses. B/Y/X are not
  // connected to gameplay, so they are not stored.
  reg [1:0] next_select, next_start, next_up, next_down;
  reg [1:0] next_left, next_right, next_a, next_l, next_r;
  reg [1:0] next_present;

  reg [1:0] select_reg, start_reg, up_reg, down_reg;
  reg [1:0] left_reg, right_reg, a_reg, l_reg, r_reg;

  assign select = select_reg;
  assign start = start_reg;
  assign up = up_reg;
  assign down = down_reg;
  assign left = left_reg;
  assign right = right_reg;
  assign a = a_reg;
  assign l = l_reg;
  assign r = r_reg;

  always @(posedge clk) begin
    if (~rst_n) begin
      pmod_data_sync  <= 2'b0;
      pmod_clk_sync   <= 2'b0;
      pmod_latch_sync <= 2'b0;
      pmod_clk_prev   <= 1'b0;
      pmod_latch_prev <= 1'b0;
    end else begin
      pmod_data_sync  <= {pmod_data_sync[0], pmod_data};
      pmod_clk_sync   <= {pmod_clk_sync[0], pmod_clk};
      pmod_latch_sync <= {pmod_latch_sync[0], pmod_latch};
      pmod_clk_prev   <= pmod_clk_sync[1];
      pmod_latch_prev <= pmod_latch_sync[1];
    end
  end

  always @(posedge clk) begin
    if (~rst_n) begin
      bit_count    <= 5'd0;
      next_present <= 2'b00;
      select_reg   <= 2'b00;
      start_reg    <= 2'b00;
      up_reg       <= 2'b00;
      down_reg     <= 2'b00;
      left_reg     <= 2'b00;
      right_reg    <= 2'b00;
      a_reg        <= 2'b00;
      l_reg        <= 2'b00;
      r_reg        <= 2'b00;
    end else begin
      if (pmod_latch_rise) begin
        if (bit_count == FRAME_BITS) begin
          select_reg  <= next_present & next_select;
          start_reg   <= next_present & next_start;
          up_reg      <= next_present & next_up;
          down_reg    <= next_present & next_down;
          left_reg    <= next_present & next_left;
          right_reg   <= next_present & next_right;
          a_reg       <= next_present & next_a;
          l_reg       <= next_present & next_l;
          r_reg       <= next_present & next_r;
        end
        bit_count    <= 5'd0;
        next_present <= 2'b00;
      end else if (pmod_clk_rise) begin
        if (bit_count != FRAME_BITS) begin
          // Presence must still consider every bit. A disconnected controller
          // reads as all ones, so any zero in that 12-bit half means present.
          if (!pmod_data_sync[1]) begin
            if (bit_count < 5'd12)
              next_present[1] <= 1'b1;
            else
              next_present[0] <= 1'b1;
          end
          case (bit_count)
            5'd2:  next_select[1] <= pmod_data_sync[1];
            5'd3:  next_start[1]  <= pmod_data_sync[1];
            5'd4:  next_up[1]     <= pmod_data_sync[1];
            5'd5:  next_down[1]   <= pmod_data_sync[1];
            5'd6:  next_left[1]   <= pmod_data_sync[1];
            5'd7:  next_right[1]  <= pmod_data_sync[1];
            5'd8:  next_a[1]      <= pmod_data_sync[1];
            5'd10: next_l[1]      <= pmod_data_sync[1];
            5'd11: next_r[1]      <= pmod_data_sync[1];
            5'd14: next_select[0] <= pmod_data_sync[1];
            5'd15: next_start[0]  <= pmod_data_sync[1];
            5'd16: next_up[0]     <= pmod_data_sync[1];
            5'd17: next_down[0]   <= pmod_data_sync[1];
            5'd18: next_left[0]   <= pmod_data_sync[1];
            5'd19: next_right[0]  <= pmod_data_sync[1];
            5'd20: next_a[0]      <= pmod_data_sync[1];
            5'd22: next_l[0]      <= pmod_data_sync[1];
            5'd23: next_r[0]      <= pmod_data_sync[1];
            default: begin end
          endcase

          bit_count <= bit_count + 5'd1;
        end
      end
    end
  end

endmodule
