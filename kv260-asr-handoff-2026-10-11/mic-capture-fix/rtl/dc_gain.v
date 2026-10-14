`timescale 1ns/1ps
// DC blocker + gain + round/saturate to 16-bit, one channel, 16 kHz.
//
// The SPH0645 output carries a large DC offset (the snapshot's user recording has a mean
// of -0.096 FS). It must be removed before any gain, or the gain would saturate on DC.
//   y[n] = x[n] - x[n-1] + a*y[n-1],  a = 1 - 2^-K  (K=9: corner ~5 Hz at 16 kHz)
// State s holds y scaled by 2^K, so the leak term is a shift and needs no multiplier:
//   s' = s + ((x - x_prev) << K) - (s >>> K);   y_dc = (s' + 2^(K-1)) >>> K
// Gain: out = sat16( ((y_dc << g) + 2) >>> 2 ), g = gain_shift clamped to 0..8.
//   g = 0 maps the mic's 18-bit full scale to 16-bit full scale; each step adds 6.02 dB.
//   Default g = 4 (+24 dB): normal speech at about -55 dBFS lands near -31 dBFS, and the
//   mic's own noise floor (-91 dBFS) stays well above 16-bit quantisation (-98 dBFS).
// Golden model: sim/golden.py:dc_gain (same integer formulas, Python >> = floor).
module dc_gain #(
    parameter K = 9
) (
    input  wire               clk,
    input  wire               rst,
    input  wire               in_valid,
    input  wire signed [19:0] x,
    input  wire        [3:0]  gain_shift,
    output reg                out_valid,
    output reg  signed [15:0] y,
    output reg                sat
);
    reg signed [19:0] x_prev;
    reg signed [39:0] s;

    wire signed [20:0] diff = {x[19], x} - {x_prev[19], x_prev};
    wire signed [39:0] diff_ext = {{19{diff[20]}}, diff};
    wire signed [39:0] s_next = s + (diff_ext <<< K) - (s >>> K);
    wire signed [39:0] y_dc = (s_next + (40'sd1 <<< (K - 1))) >>> K;
    wire        [3:0]  g = (gain_shift > 4'd8) ? 4'd8 : gain_shift;
    wire signed [39:0] t = y_dc <<< g;
    wire signed [39:0] r = (t + 40'sd2) >>> 2;

    always @(posedge clk) begin
        if (rst) begin
            x_prev <= 20'sd0;
            s <= 40'sd0;
            y <= 16'sd0;
            sat <= 1'b0;
            out_valid <= 1'b0;
        end else begin
            out_valid <= in_valid;
            if (in_valid) begin
                x_prev <= x;
                s <= s_next;
                if (r > 40'sd32767) begin
                    y <= 16'sd32767;
                    sat <= 1'b1;
                end else if (r < -40'sd32768) begin
                    y <= -16'sd32768;
                    sat <= 1'b1;
                end else begin
                    y <= r[15:0];
                    sat <= 1'b0;
                end
            end
        end
    end
endmodule
