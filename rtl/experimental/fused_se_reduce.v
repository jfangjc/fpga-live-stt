`timescale 1ns/1ps
// Experimental channel-at-a-time INT8 SE reduction. Each beat contains
// consecutive time samples; mask bits identify valid samples. Start/last bound
// a channel packet. Count is returned with the exact sum for the CPU SE gate.
// Errors drain through last and return zero sum/count with error set. No
// tensor storage or host protocol is provided by this standalone primitive.
module fused_se_reduce #(
    parameter LANES = 16,
    parameter MAX_SAMPLES = 65535
) (
    input wire aclk, aresetn,
    input wire [LANES*8-1:0] s_data,
    input wire [LANES-1:0] s_mask,
    input wire [31:0] s_tag,
    input wire s_start, s_last, s_valid,
    output wire s_ready,
    output reg signed [31:0] m_sum,
    output reg [31:0] m_count, m_tag,
    output reg m_error,
    output wire m_valid,
    input wire m_ready
);
    reg active, packet_error, output_valid;
    reg signed [31:0] accumulator;
    reg [31:0] count, tag;
    reg signed [31:0] beat_sum, next_sum;
    reg [31:0] beat_count, next_count;
    reg beat_error, next_error;
    integer lane;
    assign s_ready = aresetn && (!output_valid || m_ready);
    assign m_valid = aresetn && output_valid;

    always @* begin
        beat_sum = 0; beat_count = 0; beat_error = 0;
        for (lane=0; lane<LANES; lane=lane+1) begin
            if (s_mask[lane]) begin
                beat_sum = beat_sum + $signed(s_data[lane*8+:8]);
                beat_count = beat_count + 1;
                if (s_data[lane*8+:8] == 8'h80) beat_error = 1;
            end
        end
        next_sum = (active ? accumulator : 32'sd0) + beat_sum;
        next_count = (active ? count : 32'd0) + beat_count;
        next_error = beat_error || (active ? packet_error : !s_start) ||
                     (active && (s_start || s_tag != tag)) ||
                     next_count > MAX_SAMPLES;
    end

    always @(posedge aclk) begin
        if (!aresetn) begin
            active <= 0; packet_error <= 0; output_valid <= 0;
            accumulator <= 0; count <= 0; tag <= 0;
            m_sum <= 0; m_count <= 0; m_tag <= 0; m_error <= 0;
        end else begin
            if (m_ready) output_valid <= 0;
            if (s_valid && s_ready) begin
                if (!active) tag <= s_tag;
                if (s_last) begin
                    active <= 0; accumulator <= 0; count <= 0; packet_error <= 0;
                    output_valid <= 1;
                    m_sum <= next_error ? 32'sd0 : next_sum;
                    m_count <= next_error ? 32'd0 : next_count;
                    m_tag <= active ? tag : s_tag;
                    m_error <= next_error;
                end else begin
                    active <= 1;
                    // Saturate state after an error to avoid overflow while
                    // draining an arbitrarily long malformed packet.
                    accumulator <= next_error ? 32'sd0 : next_sum;
                    count <= next_error ? 32'd0 : next_count;
                    packet_error <= next_error;
                end
            end
        end
    end
endmodule
