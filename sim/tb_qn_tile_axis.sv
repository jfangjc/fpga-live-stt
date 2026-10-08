`timescale 1ns/1ps
module tb_qn_tile_axis;
    reg clk=0;
    always #5 clk=~clk;
    reg rstn=0, valid=0, last=0, ready=0;
    reg [127:0] data=0;
    wire in_ready, out_valid, out_last, busy, done, error;
    wire [127:0] out_data;
    qn_tile_axis dut(clk,rstn,data,valid,in_ready,last,out_data,out_valid,ready,out_last,busy,done,error);
    integer expected [0:255];
    integer received=0, cycle=0, cases=0;
    reg previous_stall=0;
    reg [127:0] held_data;
    reg held_last;
    integer j;

    always @(negedge clk) begin
        cycle=cycle+1;
        ready = cycle % 7 != 0 && cycle % 7 != 1;
    end
    always @(posedge clk) begin
        if (!rstn) begin
            previous_stall=0;
            received=0;
        end else begin
            if (previous_stall && (!out_valid || out_data !== held_data || out_last !== held_last))
                $fatal(1,"Output changed under backpressure");
            previous_stall = out_valid && !ready;
            held_data=out_data;
            held_last=out_last;
            if (out_valid && ready) begin
                if (received >= 64) $fatal(1,"Too many output beats");
                for (j=0;j<4;j=j+1)
                    if ($signed(out_data[j*32 +:32]) !== expected[received*4+j])
                        $fatal(1,"Mismatch beat%0d lane%0d actual%0d expected%0d",received,j,$signed(out_data[j*32 +:32]),expected[received*4+j]);
                if (out_last !== (received==63)) $fatal(1,"Incorrect output TLAST");
                received=received+1;
            end
        end
    end

    task send(input reg [127:0] value, input reg ending);
        begin
            @(negedge clk);
            data=value; valid=1; last=ending;
            do @(posedge clk); while(!in_ready);
            @(negedge clk);
            valid=0; last=0;
        end
    endtask
    task finish_case(input reg should_error);
        begin
            wait(done);
            @(negedge clk);
            if (received!=64 || error!==should_error || busy) $fatal(1,"Bad completion");
            cases=cases+1;
            received=0;
        end
    endtask
    function automatic integer x(input integer k,t,seed);
        x=(k*17+t*7+seed)%256-128;
    endfunction
    function automatic integer w(input integer k,o,seed);
        w=(k*31+o*13+seed*3)%256-128;
    endfunction
    task tile(input integer length,seed);
        integer k,t,o;
        reg [127:0] row_data;
        begin
            $readmemh($sformatf("sim/tile_vectors/k%0d_s%0d.hex",length,seed), expected);
            send({64'd0,length[31:0],32'h31544e51},0);
            for(k=0;k<length;k=k+1) begin
                if(k%3==0) repeat(2) @(negedge clk);
                for(t=0;t<16;t=t+1) row_data[t*8 +:8]=x(k,t,seed);
                send(row_data,0);
            end
            for(k=0;k<length;k=k+1) begin
                for(o=0;o<16;o=o+1) row_data[o*8 +:8]=w(k,o,seed);
                send(row_data,k==length-1);
            end
            finish_case(0);
        end
    endtask
    task zeros;
        integer i;
        for(i=0;i<256;i=i+1) expected[i]=0;
    endtask

    initial begin
        repeat(5) @(negedge clk);
        rstn=1;
        tile(1,0); tile(17,9); tile(257,19); tile(1024,255);
        zeros(); send({64'd0,32'd0,32'h31544e51},0); send(0,1); finish_case(1);
        zeros(); send({64'd0,32'd1025,32'h31544e51},0); send(0,1); finish_case(1);
        zeros(); send({64'd0,32'd17,32'h31544e51},0); send(0,1); finish_case(1);
        zeros(); send({64'd0,32'd1,32'h31544e51},0); send(0,0); send(0,0); send(0,1); finish_case(1);
        zeros(); send({64'd0,32'd1,32'h31544e51},1); finish_case(1);
        zeros(); send({64'd0,32'd1,32'hdeadbeef},0); send(0,1); finish_case(1);
        zeros(); send({64'd0,32'd2,32'h31544e51},0); send(0,0); send(0,0); send(0,1); finish_case(1);
        // Reset an accepted incomplete packet, then prove recovery.
        send({64'd0,32'd17,32'h31544e51},0); send(0,0);
        @(negedge clk); rstn=0;
        repeat(3) @(negedge clk); rstn=1;
        tile(17,11);
        // Reset after the compute pipeline has started; no stale products
        // may enter the next command's accumulators.
        zeros(); send({64'd0,32'd17,32'h31544e51},0);
        repeat(17) send({16{8'h7f}},0);
        repeat(16) send({16{8'h80}},0);
        send({16{8'h80}},1);
        repeat(3) @(negedge clk); rstn=0;
        repeat(3) @(negedge clk); rstn=1;
        tile(1,0);
        $display("PASS: %0d tile/protocol cases; signed arithmetic, K limits, stalls, TLAST, reset recovery",cases);
        $finish;
    end
    initial begin
        repeat(100000) @(posedge clk);
        $fatal(1,"Simulation timeout");
    end
endmodule
