`timescale 1ns/1ps
module tb_fused_affine_quant;
    reg clk=0;always #5 clk=~clk;
    reg rstn=0,valid=0,ready=0;
    reg [109:0] beat=0;
    wire in_ready,out_valid,error;
    wire [7:0] result;
    reg [109:0] inputs[0:1023];reg [8:0] expected[0:1023];
    integer sent=0,received=0,cycles=0,seed=20261009,resets=0;
    reg accepted=0,was_stalled=0;reg [8:0] stalled;
    fused_affine_quant #(.LANES(1)) dut(.aclk(clk),.aresetn(rstn),
        .s_acc(beat[31:0]),.s_bias(beat[63:32]),.s_multiplier(beat[95:64]),
        .s_shift(beat[101:96]),.s_zero(beat[109:102]),.s_valid(valid),.s_ready(in_ready),
        .m_data(result),.m_valid(out_valid),.m_ready(ready),.m_error(error));
    initial begin
        $readmemh("input.mem",inputs);$readmemh("expected.mem",expected);
        repeat(4)@(negedge clk);rstn=1;
        wait(sent>=100);@(negedge clk);ready=0;
        repeat(3)@(negedge clk);rstn=0;valid=0;
        repeat(3)@(negedge clk);resets=1;rstn=1;
        wait(received==1024);@(negedge clk);valid=0;ready=1;
        repeat(3)@(negedge clk);if(out_valid)$fatal(1,"Unexpected affine output");
        $display("PASS: 1024 independent affine bias/rounding/overflow vectors, stalls and reset");$finish;
    end
    always @(negedge clk) if(rstn) begin
        if(!valid||accepted) begin valid=sent<1024 && (($random(seed)&7)!=0);if(sent<1024)beat=inputs[sent];end
        if(resets||sent<100)ready=($random(seed)&3)!=0;
    end
    always @(posedge clk) begin
        cycles=cycles+1;if(cycles>20000)$fatal(1,"Timeout");
        if(!rstn)begin sent=0;received=0;accepted=0;was_stalled=0;end
        else begin
            accepted=valid&&in_ready;
            if(was_stalled&&(!out_valid||{error,result}!==stalled))$fatal(1,"Affine response changed under backpressure");
            was_stalled=out_valid&&!ready;stalled={error,result};
            if(accepted)sent=sent+1;
            if(out_valid&&ready)begin
                if({error,result}!==expected[received])$fatal(1,"Affine vector %0d got %h expected %h",received,{error,result},expected[received]);
                received=received+1;
            end
        end
    end
endmodule
