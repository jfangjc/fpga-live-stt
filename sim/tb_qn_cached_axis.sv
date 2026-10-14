`timescale 1ns/1ps
// Independent signed reference arithmetic and adversarial AXI-stream framing.
module tb_qn_cached_axis;
    reg clk=0;
    always #5 clk=~clk;
    reg rstn=0, valid=0, last=0, ready=0, force_stall=0;
    reg [127:0] data=0;
    wire in_ready, out_valid, out_last, busy, done, error;
    wire [127:0] out_data;
    qn_cached_axis dut(clk,rstn,data,valid,in_ready,last,out_data,out_valid,ready,out_last,busy,done,error);
    integer expected [0:16383];
    integer received=0, cycle=0, cases=0, payload_beats=0;
    reg [127:0] expected_header;
    reg checking=0, previous_stall=0, legacy_response=0;
    reg [127:0] held_data;
    reg held_last;
    integer j;
    always @(negedge clk) begin
        cycle=cycle+1;
        ready=!force_stall && cycle%11!=0 && cycle%11!=1 && cycle%11!=2;
    end
    always @(posedge clk) begin
        if (!rstn) begin
            previous_stall=0;
            received=0;
        end else begin
            if (previous_stall && (!out_valid || out_data!==held_data || out_last!==held_last))
                $fatal(1,"Cached output changed while stalled");
            previous_stall=out_valid && !ready;
            held_data=out_data;
            held_last=out_last;
            if (out_valid && ready && checking) begin
                if (received>payload_beats) $fatal(1,"Excess output beat");
                if (received==0 && !legacy_response) begin
                    if(out_data!==expected_header) $fatal(1,"Response actual %h expected %h",out_data,expected_header);
                end else begin
                    for(j=0;j<4;j=j+1)
                        if($signed(out_data[j*32+:32])!==expected[(received-(legacy_response?0:1))*4+j])
                            $fatal(1,"Cached arithmetic beat %0d lane %0d",received,j);
                end
                if(out_last!==(received==payload_beats)) $fatal(1,"Wrong response TLAST at %0d",received);
                received=received+1;
            end
        end
    end
    function automatic [127:0] header(input integer op,k,m,tag);
        header={tag[31:0],16'b0,k[15:0],m[15:0],8'b0,op[7:0],32'h32434e51};
    endfunction
    function automatic integer x(input integer k,t,seed);
        x=(k*17+t*7+seed)%256-128;
    endfunction
    function automatic integer w(input integer k,o,seed);
        w=(k*31+o*13+seed*3)%256-128;
    endfunction
    task send(input reg [127:0] value,input reg ending);
        begin
            @(negedge clk);data=value;valid=1;last=ending;
            do @(posedge clk);while(!in_ready);
            @(negedge clk);valid=0;last=0;
        end
    endtask
    task expect_response(input integer status,k,m,tag,beats,input reg zeros);
        integer i;
        begin
            expected_header={tag[31:0],m[15:0],k[15:0],status[31:0],32'h32524e51};
            payload_beats=beats;received=0;checking=1;legacy_response=0;
            if(zeros) for(i=0;i<16384;i=i+1)expected[i]=0;
        end
    endtask
    task finish_case(input reg should_error);
        begin
            wait(done);@(negedge clk);
            if(received!=payload_beats+1 || error!==should_error || busy)
                $fatal(1,"Completion mismatch received %0d expected %0d error %b busy %b",received,payload_beats+1,error,busy);
            checking=0;cases=cases+1;
        end
    endtask
    task load(input integer k,m,tag,seed);
        integer g,i,o;
        reg [127:0] row;
        begin
            expect_response(0,k,m,tag,0,0);
            send(header(1,k,m,tag),0);
            for(g=0;g<(m+15)/16;g=g+1)for(i=0;i<k;i=i+1)begin
                for(o=0;o<16;o=o+1)row[o*8+:8]=w(i,g*16+o,seed);
                if(i%13==0)repeat(2)@(negedge clk);
                send(row,g==(m+15)/16-1 && i==k-1);
            end
            finish_case(0);
        end
    endtask
    task run_block(input integer k,m,tag,wseed,xseed);
        integer i,g,t,o,sum;
        reg [127:0] row;
        begin
            expect_response(0,k,m,tag,64*((m+15)/16),0);
            for(g=0;g<(m+15)/16;g=g+1)for(t=0;t<16;t=t+1)for(o=0;o<16;o=o+1)begin
                sum=0;for(i=0;i<k;i=i+1)sum=sum+x(i,t,xseed)*w(i,g*16+o,wseed);
                expected[g*256+t*16+o]=sum;
            end
            send(header(2,k,m,tag),0);
            for(i=0;i<k;i=i+1)begin
                for(t=0;t<16;t=t+1)row[t*8+:8]=x(i,t,xseed);
                if(i%3==0)repeat(2)@(negedge clk);
                send(row,i==k-1);
            end
            finish_case(0);
        end
    endtask
    task missing_cache(input integer k,m,tag);
        integer i;
        begin
            expect_response(3,k,m,tag,64*((m+15)/16),1);
            send(header(2,k,m,tag),0);
            for(i=0;i<k;i=i+1)send(0,i==k-1);
            finish_case(1);
        end
    endtask
    task reset_core;
        begin
            @(negedge clk);rstn=0;valid=0;last=0;checking=0;
            repeat(3)@(negedge clk);rstn=1;force_stall=0;
        end
    endtask
    task legacy_tile;
        integer i,t,o,sum;
        reg [127:0] row;
        begin
            received=0;payload_beats=63;checking=1;legacy_response=1;
            for(t=0;t<16;t=t+1)for(o=0;o<16;o=o+1)begin
                sum=0;for(i=0;i<17;i=i+1)sum=sum+x(i,t,19)*w(i,o,31);
                expected[t*16+o]=sum;
            end
            send({64'b0,32'd17,32'h31544e51},0);
            for(i=0;i<17;i=i+1)begin
                for(t=0;t<16;t=t+1)row[t*8+:8]=x(i,t,19);
                send(row,0);
            end
            for(i=0;i<17;i=i+1)begin
                for(o=0;o<16;o=o+1)row[o*8+:8]=w(i,o,31);
                send(row,i==16);
            end
            finish_case(0);
        end
    endtask
    integer random_seed=32'h428715, random_case, rk,rm,ws,xs;
    initial begin
        repeat(5)@(negedge clk);rstn=1;
        missing_cache(1,1,1);
        load(1,1,11,0);run_block(1,1,11,0,0);run_block(1,1,11,0,255);
        load(17,17,12,9);run_block(17,17,12,9,3);run_block(17,17,12,9,127);
        load(257,64,13,19);run_block(257,64,13,19,20);
        load(1024,64,14,255);run_block(1024,64,14,255,255);
        load(1,1024,15,31);run_block(1,1024,15,31,17);
        for(random_case=0;random_case<8;random_case=random_case+1)begin
            rk=1+($random(random_seed)&127);rm=1+($random(random_seed)&63);
            ws=$random(random_seed)&255;xs=$random(random_seed)&255;
            load(rk,rm,100+random_case,ws);run_block(rk,rm,100+random_case,ws,xs);
        end
        load(17,17,16,3);legacy_tile();missing_cache(17,17,16);
        // Explicit invalidation must remove a valid cached layer.
        expect_response(0,0,0,0,0,0);send(header(3,0,0,0),1);finish_case(0);
        missing_cache(1,1024,15);
        // Cache tag/shape mismatches invalidate, rather than silently reusing data.
        load(17,17,20,2);missing_cache(17,17,21);missing_cache(17,17,20);
        load(17,17,22,2);missing_cache(1,17,22);
        // A truncated replacement cannot expose old or partly written weights.
        load(17,17,30,7);
        expect_response(2,17,17,31,0,0);send(header(1,17,17,31),0);send(0,1);finish_case(1);
        missing_cache(17,17,30);missing_cache(17,17,31);
        // Missing TLAST at expected boundary: drain trailing beats before ACK.
        expect_response(2,1,1,32,0,0);send(header(1,1,1,32),0);send(0,0);send(0,1);finish_case(1);
        missing_cache(1,1,32);
        load(17,17,40,4);
        expect_response(2,17,17,40,128,1);send(header(2,17,17,40),0);send(0,1);finish_case(1);
        missing_cache(17,17,40);
        load(1,1,41,4);
        expect_response(2,1,1,41,64,1);send(header(2,1,1,41),0);send(0,0);send(0,1);finish_case(1);
        // Zero/oversize shape, nonzero reserved bits and unknown operation.
        expect_response(1,0,1,50,0,0);send(header(1,0,1,50),0);send(0,1);finish_case(1);
        expect_response(1,1025,1,51,0,0);send(header(1,1025,1,51),0);send(0,1);finish_case(1);
        expect_response(1,1,1025,52,0,0);send(header(1,1,1025,52),0);send(0,1);finish_case(1);
        expect_response(1,1,1,53,0,0);send(header(1,1,1,53)|128'h00000000000000000000010000000000,0);send(0,1);finish_case(1);
        expect_response(1,1,1,54,0,0);send(header(99,1,1,54),1);finish_case(1);
        expect_response(1,1,1,55,0,0);send(header(1,1,1,55)^128'h00000000000000000000000001000000,0);send(0,1);finish_case(1);
        expect_response(1,1,1,0,0,0);send(header(1,1,1,0),0);send(0,1);finish_case(1);
        expect_response(2,1,1,56,0,0);send(header(1,1,1,56),1);finish_case(1);
        load(1,1,57,1);
        expect_response(2,1,1,57,64,1);send(header(2,1,1,57),1);finish_case(1);
        missing_cache(1,1,57);
        expect_response(2,0,0,0,0,0);send(header(3,0,0,0),0);send(0,1);finish_case(1);
        // Reset during an incomplete LOAD, active MAC pipeline and stalled output.
        send(header(1,17,17,60),0);send(0,0);reset_core();missing_cache(17,17,60);
        load(17,17,61,2);send(header(2,17,17,61),0);repeat(16)send(0,0);send(0,1);
        repeat(4)@(negedge clk);reset_core();missing_cache(17,17,61);
        load(1,1,62,2);force_stall=1;send(header(2,1,1,62),0);send(0,1);
        wait(out_valid);repeat(3)@(negedge clk);reset_core();missing_cache(1,1,62);
        load(17,17,70,3);run_block(17,17,70,3,5);
        $display("PASS: %0d cached arithmetic/protocol/reset cases",cases);$finish;
    end
    initial begin
        repeat(1000000)@(posedge clk);$fatal(1,"Cached simulation timeout");
    end
endmodule
