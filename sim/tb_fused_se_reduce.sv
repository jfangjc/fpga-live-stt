`timescale 1ns/1ps
module tb_fused_se_reduce;
    reg clk=0; always #5 clk=~clk;
    reg resetn=0, s_valid=0, m_ready=0;
    reg [177:0] beat=0;
    wire s_ready, m_valid, m_error;
    wire [31:0] m_sum, m_count, m_tag;
    // Sized generously; exact counts passed by generated Verilog include.
    `include "counts.vh"
    reg [177:0] inputs [0:INPUT_COUNT-1];
    reg [96:0] expected [0:OUTPUT_COUNT-1];
    integer sent=0, received=0, cycles=0, resets=0, seed=20261009;
    reg accepted=0, was_stalled=0;
    reg [96:0] stalled;
    fused_se_reduce #(.MAX_SAMPLES(1024)) dut(
        .aclk(clk),.aresetn(resetn),.s_data(beat[127:0]),.s_mask(beat[143:128]),
        .s_tag(beat[175:144]),.s_start(beat[176]),.s_last(beat[177]),
        .s_valid(s_valid),.s_ready(s_ready),.m_sum(m_sum),.m_count(m_count),
        .m_tag(m_tag),.m_error(m_error),.m_valid(m_valid),.m_ready(m_ready));
    initial begin
        $readmemh("input.mem", inputs); $readmemh("expected.mem",expected);
        repeat(4) @(negedge clk); resetn=1;
        wait(received>=20);
        @(negedge clk); m_ready=0;
        // Block one terminal response, then reset and replay all fixtures.
        wait(m_valid); @(negedge clk); resetn=0; s_valid=0;
        repeat(3) @(negedge clk); resets=1; resetn=1;
        wait(received==OUTPUT_COUNT);
        @(negedge clk); s_valid=0; m_ready=1;
        repeat(3) @(negedge clk);
        if (m_valid) $fatal(1,"Unexpected terminal output");
        $display("PASS: SE reduction packets, real channels, malformed inputs, stalls and reset");
        $finish;
    end
    always @(negedge clk) begin
        if (resetn) begin
            if (!s_valid || accepted) begin
                s_valid=sent<INPUT_COUNT && (($random(seed)&7)!=0);
                if (sent<INPUT_COUNT) beat=inputs[sent];
            end
            if (resets || received<20) m_ready=($random(seed)&3)!=0;
        end
    end
    always @(posedge clk) begin
        cycles=cycles+1;
        if (cycles>200000) $fatal(1,"Timeout");
        if (!resetn) begin sent=0; received=0; accepted=0; was_stalled=0; end
        else begin
            accepted=s_valid && s_ready;
            if (was_stalled && (!m_valid || {m_tag,m_error,m_count,m_sum} !== stalled))
                $fatal(1,"Output changed while blocked");
            was_stalled=m_valid && !m_ready;
            stalled={m_tag,m_error,m_count,m_sum};
            if (accepted) sent=sent+1;
            if (m_valid && m_ready) begin
                if ({m_tag,m_error,m_count,m_sum} !== expected[received])
                    $fatal(1,"Packet %0d got %h expected %h",received,
                           {m_tag,m_error,m_count,m_sum},expected[received]);
                received=received+1;
            end
        end
    end
endmodule
