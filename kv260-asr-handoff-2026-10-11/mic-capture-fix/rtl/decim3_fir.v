`timescale 1ns/1ps
// 3:1 decimating FIR, 48 kHz -> 16 kHz, both channels, one time-shared multiplier.
// Audio clock domain. Coefficients: rtl/decim3_coeffs.vh (96 taps, signed Q1.17, sum 2^17).
//
// Every third input frame starts a dot product over the newest 96 samples:
//   y[m] = sat20( (sum_k h[k] * x[3m+2-k] + 2^16) >>> 17 ),  x[n<0] = 0
// This computes only the kept outputs, so it is arithmetically identical to a polyphase
// decimator. Cost: 2 x 96 = 192 multiply-accumulates per output, about 195 clk.
// At 24.576 MHz there are 512 clk between 48 kHz input frames, so a run always
// finishes before the next input. overlap_err goes sticky if that is ever violated.
// Pipeline: operand registers -> product register -> accumulator, which maps onto one
// DSP48E2 with AREG/BREG, MREG and PREG used (the DRC pipelining warnings in the old design).
module decim3_fir (
    input  wire               clk,
    input  wire               rst,
    input  wire               in_valid,
    input  wire signed [17:0] in_l,
    input  wire signed [17:0] in_r,
    output reg                out_valid,
    output reg  signed [19:0] out_l,
    output reg  signed [19:0] out_r,
    output reg                overlap_err
);
    `include "decim3_coeffs.vh"
    localparam [6:0] LAST = 7'd95;

    // Sample history, one entry per input frame (maps to distributed RAM; no reset needed
    // because 'filled' masks entries that have not been written since reset).
    reg [35:0] hist [0:95];
    reg [6:0] wp;
    reg [6:0] filled;
    reg [1:0] phase3;

    reg       running;
    reg       ch;
    reg [6:0] k;
    reg [6:0] newest;

    // newest + 96 - k lies in 1..95 when newest < k, so 7-bit modular arithmetic is exact.
    wire [6:0] wrap_idx = newest + 7'd96 - k;
    wire [6:0] rd_idx = (newest >= k) ? (newest - k) : wrap_idx;
    wire [35:0] rd_word = hist[rd_idx];

    reg signed [17:0] a_s, b_c;
    reg s1_vld, s1_first, s1_last, s1_ch;
    reg signed [35:0] m;
    reg s2_vld, s2_first, s2_last, s2_ch;
    reg signed [43:0] acc;

    wire signed [43:0] m_ext = {{8{m[35]}}, m};
    wire signed [43:0] acc_next = s2_first ? m_ext : acc + m_ext;
    wire signed [43:0] rounded = (acc_next + 44'sd65536) >>> 17;

    function signed [19:0] sat20;
        input signed [43:0] v;
        begin
            if (v > 44'sd524287) sat20 = 20'sd524287;
            else if (v < -44'sd524288) sat20 = -20'sd524288;
            else sat20 = v[19:0];
        end
    endfunction

    always @(posedge clk) begin
        if (in_valid) hist[wp] <= {in_r, in_l};
    end

    always @(posedge clk) begin
        if (rst) begin
            wp <= 7'd0;
            filled <= 7'd0;
            phase3 <= 2'd0;
            running <= 1'b0;
            ch <= 1'b0;
            k <= 7'd0;
            newest <= 7'd0;
            a_s <= 18'sd0;
            b_c <= 18'sd0;
            s1_vld <= 1'b0; s1_first <= 1'b0; s1_last <= 1'b0; s1_ch <= 1'b0;
            m <= 36'sd0;
            s2_vld <= 1'b0; s2_first <= 1'b0; s2_last <= 1'b0; s2_ch <= 1'b0;
            acc <= 44'sd0;
            out_valid <= 1'b0;
            out_l <= 20'sd0;
            out_r <= 20'sd0;
            overlap_err <= 1'b0;
        end else begin
            out_valid <= 1'b0;

            // Stage 1: issue one tap per cycle.
            s1_vld <= running;
            s1_first <= running && (k == 7'd0);
            s1_last <= running && (k == LAST);
            s1_ch <= ch;
            if (running) begin
                if (k < filled) a_s <= ch ? $signed(rd_word[35:18]) : $signed(rd_word[17:0]);
                else a_s <= 18'sd0;
                b_c <= decim3_coeff(k);
                if (k == LAST) begin
                    k <= 7'd0;
                    if (ch) running <= 1'b0;
                    else ch <= 1'b1;
                end else begin
                    k <= k + 7'd1;
                end
            end

            // Stage 2: product.
            m <= a_s * b_c;
            s2_vld <= s1_vld; s2_first <= s1_first; s2_last <= s1_last; s2_ch <= s1_ch;

            // Stage 3: accumulate; round and saturate at the last tap.
            if (s2_vld) begin
                acc <= acc_next;
                if (s2_last) begin
                    if (s2_ch) begin
                        out_r <= sat20(rounded);
                        out_valid <= 1'b1;
                    end else begin
                        out_l <= sat20(rounded);
                    end
                end
            end

            // Input bookkeeping (after the issue logic so a new start takes priority).
            if (in_valid) begin
                wp <= (wp == LAST) ? 7'd0 : wp + 7'd1;
                if (filled != 7'd96) filled <= filled + 7'd1;
                if (running) overlap_err <= 1'b1;
                if (phase3 == 2'd2) begin
                    phase3 <= 2'd0;
                    running <= 1'b1;
                    ch <= 1'b0;
                    k <= 7'd0;
                    newest <= wp;
                end else begin
                    phase3 <= phase3 + 2'd1;
                end
            end
        end
    end
endmodule
