`timescale 1ns/1ps
module tb_sph0645;
    reg clk=0, rst=1, mic_data=0;
    always #5 clk=~clk;
    wire bclk, ws, valid;
    wire [23:0] sample;
    sph0645_rx dut(.clk(clk),.rst(rst),.mic_data(mic_data),
        .mic_bclk(bclk),.mic_ws(ws),.sample_data(sample),.sample_valid(valid));
    reg previous_ws=1;
    integer slot_bit=0, frame=-1, received=0;
    reg [23:0] value;
    function [23:0] expected;
        input integer n;
        begin
            case(n % 4)
                0: expected=24'h007fff;
                1: expected=24'h800000;
                2: expected=24'habcdef;
                3: expected=24'h123456;
            endcase
        end
    endfunction
    // Model maximum DATA propagation delay of 66 ns from BCLK rising.
    // Right channel deliberately differs, so accidental right capture fails.
    always @(posedge bclk) begin
        if (ws != previous_ws) begin
            slot_bit=0;
            if (!ws) frame=frame+1;
        end else slot_bit=slot_bit+1;
        previous_ws=ws;
        value=ws ? 24'hdeadbe : expected(frame);
        if (slot_bit >=1 && slot_bit <=24) mic_data <= #66 value[24-slot_bit];
        else mic_data <= #66 1'b1;
    end
    always @(negedge clk) begin
        if (valid) begin
            if (sample !== expected(received)) begin
                $display("FAIL frame %0d expected %h got %h",received,expected(received),sample);
                $fatal(1);
            end
            received=received+1;
            if (received==8) begin
                $display("PASS: eight left-channel samples; I2S delay and right-channel rejection verified");
                $finish;
            end
        end
    end
    initial begin #200 rst=0; #1000000; $fatal(1,"audio timeout"); end
endmodule
