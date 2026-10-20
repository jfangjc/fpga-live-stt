`timescale 1ns/1ps
// Standalone experimental post-MAC component; not part of deployed firmware.
// Four channels/time samples per beat, checked positive Q31 multiplier, shift
// 1..62, nearest-even signed rounding, symmetric INT8 saturation then mask/ReLU.
// Two elastic pipeline stages retain all sidebands under backpressure.
module fused_requant #(
    parameter LANES = 4
) (
    input wire aclk, input wire aresetn,
    input wire [LANES*32-1:0] s_acc,
    input wire [LANES*32-1:0] s_multiplier,
    input wire [LANES*6-1:0] s_shift,
    input wire [LANES-1:0] s_mask, s_relu,
    input wire [31:0] s_tag,
    input wire s_last, s_valid,
    output wire s_ready,
    output reg [LANES*8-1:0] m_data,
    output reg [31:0] m_tag,
    output reg m_last, m_error,
    output wire m_valid,
    input wire m_ready
);
    reg product_valid, output_valid;
    reg signed [63:0] products [0:LANES-1];
    reg [5:0] shifts [0:LANES-1];
    reg [LANES-1:0] masks, relus, invalid;
    reg [31:0] product_tag;
    reg product_last;
    wire output_ready = !output_valid || m_ready;
    wire product_ready = !product_valid || output_ready;
    assign s_ready = aresetn && product_ready;
    assign m_valid = aresetn && output_valid;

    function [7:0] quantized;
        input signed [63:0] product;
        input [5:0] shift;
        input mask, relu, bad;
        reg signed [63:0] quotient, rounded;
        reg [63:0] remainder, half, low_mask;
        begin
            if (!mask || bad) quantized = 8'd0;
            else begin
                quotient = product >>> shift;
                low_mask = (64'd1 << shift) - 1;
                remainder = product & low_mask;
                half = 64'd1 << (shift-1);
                rounded = quotient + ((remainder > half) ||
                                     ((remainder == half) && quotient[0]));
                if (relu && rounded < 0) quantized = 8'd0;
                else if (rounded > 127) quantized = 8'd127;
                else if (rounded < -127) quantized = -8'sd127;
                else quantized = rounded[7:0];
            end
        end
    endfunction

    integer lane;
    always @(posedge aclk) begin
        if (!aresetn) begin
            product_valid <= 1'b0;
            output_valid <= 1'b0;
            m_data <= 0; m_tag <= 0; m_last <= 0; m_error <= 0;
        end else begin
            if (output_ready) begin
                output_valid <= product_valid;
                if (product_valid) begin
                    for (lane=0; lane<LANES; lane=lane+1)
                        m_data[lane*8+:8] <= quantized(products[lane], shifts[lane],
                                                      masks[lane], relus[lane], invalid[lane]);
                    m_tag <= product_tag;
                    m_last <= product_last;
                    m_error <= |invalid;
                end
            end
            if (product_ready) begin
                product_valid <= s_valid;
                if (s_valid) begin
                    for (lane=0; lane<LANES; lane=lane+1) begin
                        products[lane] <= $signed(s_acc[lane*32+:32]) *
                                          $signed(s_multiplier[lane*32+:32]);
                        shifts[lane] <= s_shift[lane*6+:6];
                        invalid[lane] <= s_multiplier[lane*32+31] ||
                                         s_shift[lane*6+:6]==0 || s_shift[lane*6+:6]==63;
                    end
                    masks <= s_mask; relus <= s_relu;
                    product_tag <= s_tag; product_last <= s_last;
                end
            end
        end
    end
endmodule
