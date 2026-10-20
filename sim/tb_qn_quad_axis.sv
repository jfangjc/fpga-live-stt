`timescale 1ns/1ps
module tb_qn_quad_axis;
 reg clk=0;always #5 clk=~clk;
 reg rstn=0,valid=0,last=0,ready=0,force_stall=0;
 reg [127:0] data=0;
 wire in_ready,out_valid,out_last,busy,done,error;
 wire [127:0] out_data;
 qn_cached_axis dut(clk,rstn,data,valid,in_ready,last,out_data,out_valid,ready,out_last,busy,done,error);
 integer expected[0:1048575];
 integer received=0,cycle=0,cases=0,payload=0,expected_mac=0;
 integer case_start=0;
 reg checking=0,bulk=0,quantized=0,previous_stall=0;
 reg [127:0] held_data,expected_header;
 reg held_last;
 integer j;
 always @(negedge clk)begin cycle=cycle+1;ready=!force_stall && cycle%11>2;end
 always @(posedge clk)begin
  if(!rstn)begin previous_stall=0;received=0;end
  else begin
   if(checking && cycle-case_start>400000)$fatal(1,"Case watchdog cases=%0d state=%0d received=%0d expected=%0d",cases,dut.state,received,payload);
   if(previous_stall && (!out_valid || out_data!==held_data || out_last!==held_last))$fatal(1,"Stalled output changed");
   previous_stall=out_valid && !ready;held_data=out_data;held_last=out_last;
   if(checking && out_valid && ready)begin
    if(received==0)begin if(out_data!==expected_header)$fatal(1,"ACK actual %h expected %h",out_data,expected_header);end
    else if(bulk && received==payload+1)begin
     if(out_data[31:0]!==expected_mac || out_data[127:96]<expected_mac)$fatal(1,"Hardware cycle counter mismatch %h expected issues %0d",out_data,expected_mac);
    end else if(quantized)begin
     for(j=0;j<16;j=j+1)if(out_data[j*8+:8]!==expected[(received-1)*16+j][7:0])
      $fatal(1,"Quant output beat %0d byte %0d got %0d expected %0d",received,j,out_data[j*8+:8],expected[(received-1)*16+j]);
    end else for(j=0;j<4;j=j+1)if($signed(out_data[j*32+:32])!==expected[(received-1)*4+j])$fatal(1,"Raw output mismatch beat %0d lane %0d",received,j);
    if(out_last!==(received==payload+(bulk?1:0)))$fatal(1,"TLAST mismatch beat %0d",received);
    received=received+1;
   end
  end
 end
 function automatic [127:0] header(input integer op,k,m,t,tag);
  header={tag[31:0],t[15:0],k[15:0],m[15:0],8'b0,op[7:0],32'h32434e51};
 endfunction
 function automatic integer xv(input integer k,t,seed);xv=(k*17+t*7+seed)%256;endfunction
 function automatic integer wv(input integer k,o,seed);wv=(k*31+o*13+seed*3)%256-128;endfunction
 function automatic integer requant(input reg signed[63:0] total,input integer zero);
  reg signed[63:0] p,q,r,den;
  begin p=total*64'sh40000000;den=64'sh2000000000;q=p>>>37;r=p-(q<<<37);
   if(r>(den>>>1) || (r==(den>>>1) && q[0]))q=q+1;
   q=q+zero;requant=q<0?0:q>255?255:q;
  end
 endfunction
 task send(input reg[127:0] value,input reg ending);
  begin @(negedge clk);data=value;valid=1;last=ending;do @(posedge clk);while(!in_ready);@(negedge clk);valid=0;last=0;end
 endtask
 task expect_ack(input integer stat,k,m,tag,n,input reg b,q);
  begin expected_header={tag[31:0],m[15:0],k[15:0],stat[31:0],32'h32524e51};
   payload=n;bulk=b;quantized=q;received=0;checking=1;case_start=cycle;end
 endtask
 task finish(input reg bad);
  begin wait(done);@(negedge clk);if(received!=payload+1+(bulk?1:0) || busy || error!==bad)$fatal(1,"Completion mismatch received %0d payload %0d error %b",received,payload,error);
   checking=0;cases=cases+1;$display("Completed case %0d at cycle %0d",cases,cycle);end
 endtask
 task load(input integer k,m,seed,tag,zx,zy,input reg q);
  integer g,i,o,sum,correction;reg [127:0] beat;
  begin
   expect_ack(0,k,m,tag,0,0,0);send(header(q?4:1,k,m,0,tag),0);
   for(g=0;g<(m+15)/16;g=g+1)for(i=0;i<k;i=i+1)begin
    beat=0;for(o=0;o<16;o=o+1)if(g*16+o<m)beat[o*8+:8]=wv(i,g*16+o,seed);
    send(beat,!q && g==(m+15)/16-1 && i==k-1);
   end
   if(q)for(g=0;g<(m+15)/16;g=g+1)for(o=0;o<16;o=o+1)begin
    sum=0;for(i=0;i<k;i=i+1)if(g*16+o<m)sum=sum+wv(i,g*16+o,seed);
    correction=(128-zx)*sum+(g*16+o<m?(g*16+o)*57-231:0);
    beat=0;beat[31:0]=correction;beat[63:32]=g*16+o<m?32'h40000000:0;
    beat[69:64]=g*16+o<m?37:1;beat[79:72]=g*16+o<m?zy:0;
    send(beat,g==(m+15)/16-1 && o==15);
   end
   finish(0);
  end
 endtask
 task run_case(input integer k,m,t,seed,tag,zx,zy,input reg b,q);
  integer tile,g,time_index,o,i,idx,n,groups,nt,channel;
  reg signed[63:0] total;reg [127:0] beat;
  begin groups=(m+15)/16;nt=b?(t+15)/16:1;
   n=nt*groups*(q?16:64);
   for(tile=0;tile<nt;tile=tile+1)for(g=0;g<groups;g=g+1)for(time_index=0;time_index<16;time_index=time_index+1)for(o=0;o<16;o=o+1)begin
    channel=g*16+o;total=0;
    if(channel<m)begin
     for(i=0;i<k;i=i+1)total=total+wv(i,channel,seed)*(xv(i,tile*16+time_index,seed)-(q?zx:128));
     if(q)total=total+channel*57-231;
    end
    idx=((tile*groups+g)*16+time_index)*16+o;
    expected[idx]=channel<m?(q?requant(total,zy):total):0;
   end
   expected_mac=nt*((groups+3)/4)*k;
   expect_ack(0,k,m,tag,n,b,q);send(header(b?6:q?5:2,k,m,b?t:0,tag),0);
   if(b)for(i=0;i<k;i=i+1)for(tile=0;tile<nt;tile=tile+1)begin
    beat=0;for(time_index=0;time_index<16;time_index=time_index+1)beat[time_index*8+:8]=xv(i,tile*16+time_index,seed);
    send(beat,i==k-1 && tile==nt-1);
   end else for(i=0;i<k;i=i+1)begin
    beat=0;for(time_index=0;time_index<16;time_index=time_index+1)beat[time_index*8+:8]=xv(i,time_index,seed)-128;
    send(beat,i==k-1);
   end
   finish(0);
  end
 endtask
 initial begin
  repeat(5)@(negedge clk);rstn=1;
  load(1,1,3,1,0,255,1);run_case(1,1,1,3,1,0,255,1,1);
  load(31,49,7,2,255,0,1);run_case(31,49,17,7,2,255,0,1,1);
  run_case(31,49,33,7,2,255,0,1,1);run_case(31,49,16,7,2,255,0,0,1);
  load(3,65,17,11,201,37,1);run_case(3,65,1008,17,11,201,37,1,1);
  load(80,256,19,3,128,127,1);run_case(80,256,129,19,3,128,127,1,1);
  load(256,256,23,4,37,129,1);run_case(256,256,17,23,4,37,129,1,1);
  load(64,640,11,5,220,7,1);run_case(64,640,33,11,5,220,7,1,1);
  load(1024,1024,13,6,128,128,1);run_case(1024,1024,17,13,6,128,128,1,1);
  load(31,49,17,7,0,0,0);run_case(31,49,16,17,7,0,0,0,0);
  // Reset while an ACK is blocked, then require fresh load ownership.
  force_stall=1;checking=0;send(header(3,0,0,0,0),1);wait(out_valid);
  repeat(5)@(negedge clk);rstn=0;repeat(3)@(negedge clk);rstn=1;force_stall=0;
  load(3,33,5,8,61,170,1);run_case(3,33,65,5,8,61,170,1,1);
  expect_ack(0,0,0,0,0,0,0);send(header(3,0,0,0,0),1);finish(0);
  expect_ack(3,3,33,8,0,0,0);send(header(6,3,33,1,8),0);send(0,1);finish(1);
  $display("PASS: %0d four-group raw/quantized/bulk arithmetic, counters, stalls and reset cases",cases);$finish;
 end
 initial begin #500000000;$fatal(1,"Simulation timeout");end
endmodule
