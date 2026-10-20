`timescale 1ns/1ps
// Stereo I2S master/receiver for up to two Knowles SPH0645LM4H microphones on one bus.
// Audio clock domain. clk = 24.576 MHz -> BCLK = clk/8 = 3.072 MHz, WS = BCLK/64 = 48 kHz.
//
// Datasheet facts this relies on (SPH0645LM4H-B):
//  - f_CLOCK 2.048 / 3.072 / 4.096 MHz min/typ/max; the mic sleeps below 0.9 MHz.
//    (The old receiver ran BCLK at 1.024 MHz, below the minimum.)
//  - I2S, 24-bit two's complement, MSB first, one BCLK delay after WS changes;
//    18-bit precision (bits [5:0] are zero).
//  - SELECT=GND drives DATA while WS=0 (left), SELECT=VDD while WS=1 (right),
//    tri-state otherwise, so two mics share BCLK/WS/DATA.
//  - DATA changes after the BCLK rising edge (t_DC <= ~66 ns).
//
// Timing of one BCLK period (8 clk cycles, ph = 0..7). Edges are named by ph before the edge:
//   e7: BCLK rises, period index bitn advances.
//   e3: BCLK falls; WS changes here (bitn 63 -> WS=0, bitn 31 -> WS=1). The DATA pad is
//       sampled by data_meta at this same edge, 4 clk = 162.8 ns after the rise.
//   e5: data_sync now holds the e3 pad sample (two-flop synchroniser); shift it in.
// The sample point sits 162.8 ns after the rise, so any t_DC up to ~160 ns is captured
// (test_i2s_rx.py sweeps 0..150 ns and shows failure at 200 ns).
// Left data bits are periods 1..24, right data bits 33..56.
module i2s_rx_stereo (
    input  wire               clk,
    input  wire               rst,        // synchronous, active high; BCLK held low
    input  wire               mic_data,   // asynchronous pad input (shared by both mics)
    output reg                mic_bclk,
    output reg                mic_ws,
    output reg signed [17:0]  left,       // 18-bit samples (24-bit word >>> 6)
    output reg signed [17:0]  right,
    output reg                valid,      // one-cycle strobe per stereo frame (48 kHz)
    output reg  [31:0]        frames      // stereo frames emitted since reset
);
    reg [2:0] ph;
    reg [5:0] bitn;
    (* ASYNC_REG = "TRUE" *) reg data_meta;
    (* ASYNC_REG = "TRUE" *) reg data_sync;
    reg [22:0] shift;          // 23 stored bits + the incoming bit form one 24-bit word
    reg [17:0] left_word;
    reg have_left;

    wire [23:0] shifted = {shift[22:0], data_sync};

    always @(posedge clk) begin
        if (rst) begin
            ph <= 3'd0;
            // Start inside the right half-frame (WS high) so the first left word follows a
            // proper WS falling edge. The partial right slot before it is discarded.
            bitn <= 6'd32;
            mic_bclk <= 1'b0;
            mic_ws <= 1'b1;
            data_meta <= 1'b0;
            data_sync <= 1'b0;
            shift <= 23'd0;
            left_word <= 18'd0;
            have_left <= 1'b0;
            left <= 18'sd0;
            right <= 18'sd0;
            valid <= 1'b0;
            frames <= 32'd0;
        end else begin
            data_meta <= mic_data;
            data_sync <= data_meta;
            ph <= ph + 3'd1;
            valid <= 1'b0;
            case (ph)
                3'd7: begin
                    mic_bclk <= 1'b1;
                    bitn <= bitn + 6'd1;
                end
                3'd3: begin
                    mic_bclk <= 1'b0;
                    if (bitn == 6'd63) mic_ws <= 1'b0;
                    if (bitn == 6'd31) mic_ws <= 1'b1;
                end
                3'd5: begin
                    if ((bitn >= 6'd1 && bitn <= 6'd24) || (bitn >= 6'd33 && bitn <= 6'd56))
                        shift <= shifted[22:0];
                    if (bitn == 6'd24) begin
                        left_word <= shifted[23:6];
                        have_left <= 1'b1;
                    end
                    if (bitn == 6'd56 && have_left) begin
                        left <= left_word;
                        right <= shifted[23:6];
                        valid <= 1'b1;
                        frames <= frames + 32'd1;
                    end
                end
                default: ;
            endcase
        end
    end
endmodule
