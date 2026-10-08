`timescale 1ns/1ps
module tb_qn_mac;
    reg clk=0;
    always #5 clk=~clk;
    reg rst=1, wr_en=0;
    reg [15:0] rd_addr=0, wr_addr=0;
    reg [31:0] wr_data=0;
    wire [31:0] rd_data;
    qn_mac dut(.clk(clk),.rst(rst),.wr_en(wr_en),.rd_addr(rd_addr),
               .wr_addr(wr_addr),.wr_data(wr_data),.rd_data(rd_data));
    integer errors=0, cases=0;
    integer seed=32'h12345678;
    integer k;

    task write_reg;
        input [15:0] address;
        input [31:0] value;
        begin
            @(negedge clk); wr_en=1; wr_addr=address; wr_data=value;
            @(negedge clk); wr_en=0;
        end
    endtask

    task expect_reg;
        input [15:0] address;
        input [31:0] expected;
        begin
            rd_addr=address; #1;
            if (rd_data !== expected) begin
                $display("FAIL addr=%h expected=%h actual=%h",address,expected,rd_data);
                errors=errors+1;
            end
        end
    endtask

    task run_dot;
        input integer count;
        input integer bias_value;
        input integer shift_value;
        input integer relu;
        input integer pattern; // 0 random; 1 all +127; 2 negative; 3 minima
        integer word, lane, position, x, w, reference_acc, expected, timeout;
        reg [31:0] xv, wv;
        begin
            reference_acc=bias_value;
            for(word=0;word<(count+3)/4;word=word+1) begin
                xv=0; wv=0;
                for(lane=0;lane<4;lane=lane+1) begin
                    position=word*4+lane;
                    x=$random(seed) & 255; if(x>127) x=x-256;
                    w=$random(seed) & 255; if(w>127) w=w-256;
                    if(pattern==1) begin x=127; w=127; end
                    if(pattern==2) begin x=-128; w=127; end
                    if(pattern==3) begin x=-128; w=-128; end
                    // Inactive bytes deliberately nonzero: masking is required.
                    if(position>=count) begin x=127; w=127; end
                    xv[lane*8 +: 8]=x;
                    wv[lane*8 +: 8]=w;
                    if(position<count) reference_acc=reference_acc+x*w;
                end
                write_reg(16'h1000+word*4,xv);
                write_reg(16'h2000+word*4,wv);
            end
            write_reg(16'h0008,count);
            write_reg(16'h000c,bias_value);
            write_reg(16'h0010,shift_value | (relu<<8));
            write_reg(16'h0000,1);
            // Verify software cannot alter a running job.
            if(count>=128) begin
                write_reg(16'h000c,32'h7fffffff);
                write_reg(16'h0010,31);
                write_reg(16'h1000,32'h01010101);
                write_reg(16'h2000,32'h01010101);
            end
            rd_addr=16'h0004;
            timeout=0;
            while(!rd_data[1] && timeout<2200) begin
                @(negedge clk); #1; timeout=timeout+1;
            end
            if(timeout>=2200) begin $display("FAIL timeout"); errors=errors+1; end
            expect_reg(16'h0004,2);
            expect_reg(16'h0018,reference_acc);
            expected=reference_acc >>> shift_value;
            if(relu && expected<0) expected=0;
            if(expected>127) expected=127;
            if(expected< -128) expected=-128;
            expect_reg(16'h0014,expected);
            expect_reg(16'h000c,bias_value);
            expect_reg(16'h0010,shift_value | (relu<<8));
            write_reg(16'h0000,2);
            expect_reg(16'h0004,0);
            cases=cases+1;
        end
    endtask

    initial begin
        repeat(3) @(negedge clk); rst=0;
        expect_reg(16'h0004,0);
        write_reg(16'h0000,1); expect_reg(16'h0004,4);
        write_reg(16'h0000,2); expect_reg(16'h0004,0);
        write_reg(16'h0008,4097); write_reg(16'h0000,1);
        expect_reg(16'h0004,4);
        run_dot(1,0,0,0,1);  // positive clamp
        run_dot(2,0,0,0,2);  // negative clamp + unused lane mask
        run_dot(3,0,8,1,2);  // ReLU
        run_dot(4,0,10,0,3); // -128 * -128 corner
        run_dot(5,-1234,10,0,0);
        run_dot(17,-2,31,0,2); // arithmetic negative shift
        run_dot(31,-44,11,0,0);
        run_dot(32,45,10,0,0);
        run_dot(33,-46,10,1,0);
        run_dot(65,47,11,0,0);
        run_dot(127,-48,12,0,0);
        run_dot(128,49,12,0,0);
        run_dot(4096,12345,20,0,3); // complete RAM address range
        run_dot(4095,-54321,18,1,0); // partial final word at upper bound
        for(k=0;k<32;k=k+1)
            run_dot(k+1,k*17-250,k%16,k%2,0);
        // Reset must abort an active command and clear architectural state.
        write_reg(16'h0008,4096); write_reg(16'h0000,1);
        @(negedge clk); rst=1;
        @(negedge clk); rst=0;
        expect_reg(16'h0004,0);
        expect_reg(16'h0018,0);
        expect_reg(16'h0014,0);
        if(errors==0) $display("PASS tb_qn_mac: %0d dot products plus protocol/reset checks",cases);
        else $fatal(1,"FAIL tb_qn_mac: %0d errors",errors);
        $finish;
    end
endmodule
