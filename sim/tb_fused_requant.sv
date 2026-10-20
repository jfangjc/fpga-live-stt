`timescale 1ns/1ps
module tb_fused_requant;
    reg clk=0; always #5 clk=~clk;
    reg resetn=0, s_valid=0, m_ready=0;
    reg [320:0] input_beat=0;
    wire [31:0] m_data, m_tag;
    wire s_ready, m_last, m_error, m_valid;
    reg [320:0] inputs [0:1023];
    reg [65:0] expected [0:1023];
    integer sent=0, received=0, cycles=0, resets=0;
    integer seed=20261009;
    reg [65:0] stalled;
    reg was_stalled=0;
    reg accepted_last=0;
    fused_requant dut(.aclk(clk), .aresetn(resetn),
        .s_acc(input_beat[127:0]), .s_multiplier(input_beat[255:128]),
        .s_shift(input_beat[279:256]), .s_mask(input_beat[283:280]),
        .s_relu(input_beat[287:284]), .s_last(input_beat[288]),
        .s_tag(input_beat[320:289]), .s_valid(s_valid), .s_ready(s_ready),
        .m_data(m_data), .m_tag(m_tag), .m_last(m_last), .m_error(m_error),
        .m_valid(m_valid), .m_ready(m_ready));

    initial begin
        $readmemh("input.mem", inputs);
        $readmemh("expected.mem", expected);
        repeat(4) @(negedge clk);
        resetn=1;
        wait(sent>=100);
        // Force a blocked response before reset, with pending beats to discard.
        @(negedge clk); m_ready=0;
        repeat(3) @(negedge clk);
        resetn=0; s_valid=0;
        repeat(3) @(negedge clk);
        resets=1; resetn=1;
        wait(received==1024);
        @(negedge clk); s_valid=0; m_ready=1;
        repeat(3) @(negedge clk);
        if (m_valid) $fatal(1,"Unexpected output after final vector");
        $display("PASS: 1024 four-lane requant vectors, stalls, reset flush and sidebands");
        $finish;
    end

    always @(negedge clk) begin
        if (resetn) begin
            // Preserve a stalled request; randomized bubbles otherwise.
            if (!s_valid || accepted_last) begin
                s_valid = sent<1024 && (($random(seed)&7)!=0);
                if (sent<1024) input_beat=inputs[sent];
            end
            if (resets || sent<100) m_ready=($random(seed)&3)!=0;
        end
    end
    always @(posedge clk) begin
        cycles=cycles+1;
        if (cycles>20000) $fatal(1,"Timeout");
        if (!resetn) begin sent=0; received=0; was_stalled=0; accepted_last=0; end
        else begin
            accepted_last=s_valid && s_ready;
            if (was_stalled && {m_tag,m_last,m_error,m_data} !== stalled)
                $fatal(1,"Output/sidebands changed while stalled");
            if (was_stalled && !m_valid) $fatal(1,"Valid disappeared while stalled");
            was_stalled=m_valid && !m_ready;
            stalled={m_tag,m_last,m_error,m_data};
            if (s_valid && s_ready) sent=sent+1;
            if (m_valid && m_ready) begin
                if ({m_tag,m_last,m_error,m_data} !== expected[received])
                    $fatal(1,"Vector %0d differs: got %h expected %h", received,
                           {m_tag,m_last,m_error,m_data}, expected[received]);
                received=received+1;
            end
        end
    end
endmodule
