`timescale 1ns/1ps
module tb_fused_depthwise_channel;
 reg clk=0;always #5 clk=~clk;
 reg rstn=0,cv=0,sv=0,mr=0;
 wire cr,sr,mv,ml,error,done;
 reg [12:0] times=0,valid_times=0;
 reg [6:0] kernel=0;
 reg [1015:0] weights=0;
 reg signed [31:0] bias=0,multiplier=32'h40000000;
 reg [5:0] shift=37;
 reg [7:0] xzero=0,yzero=0;
 reg [127:0] sd=0;
 wire [127:0] md;
 fused_depthwise_channel dut(clk,rstn,cv,cr,times,valid_times,kernel,weights,bias,multiplier,shift,xzero,yzero,sd,sv,sr,md,mv,mr,ml,error,done);
 integer cycle=0,received=0,cases=0,start_cycle=0;
 integer expected[0:4095];
 reg checking=0,held=0;
 reg [127:0] held_data;reg held_last;
 integer j;
 always @(negedge clk)begin cycle=cycle+1;mr=cycle%13>3;end
 always @(posedge clk)begin
  if(!rstn)begin held=0;received=0;end
  else begin
   if(held && (!mv || md!==held_data || ml!==held_last))$fatal(1,"Backpressure changed output");
   held=mv && !mr;held_data=md;held_last=ml;
   if(checking && cycle-start_cycle>100000)$fatal(1,"Watchdog state=%d",dut.state);
   if(checking && mv && mr)begin
    for(j=0;j<16;j=j+1)if(md[j*8+:8]!==expected[received*16+j][7:0])
     $fatal(1,"Arithmetic case %d t=%d got=%d expected=%d",cases,received*16+j,md[j*8+:8],expected[received*16+j]);
    if(ml!==(received==(times+15)/16-1))$fatal(1,"Last mismatch");
    received=received+1;
   end
  end
 end
 function automatic integer xv(input integer t,seed);xv=(t*37+seed*17)%256;endfunction
 function automatic integer wv(input integer t,seed);wv=(t*31+seed*11)%255-127;endfunction
 function automatic integer rq(input reg signed[63:0] a);
  reg signed[63:0] p,q,r,half;
  begin p=a*$signed(multiplier);q=p>>>shift;r=p-(q<<<shift);half=64'sd1<<(shift-1);
   if(r>half || (r==half && q[0]))q=q+1;
   q=q+yzero;rq=q<0?0:q>255?255:q;
  end
 endfunction
 task test_case(input integer t,v,k,zx,zy,seed,bi);
  integer i,p,idx;reg signed[63:0] total;
  begin
   times=t;valid_times=v;kernel=k;xzero=zx;yzero=zy;bias=bi;
   weights=0;for(i=0;i<k;i=i+1)weights[i*8+:8]=wv(i,seed);
   for(p=0;p<(t+15)/16*16;p=p+1)begin
    total=bi;
    for(i=0;i<k;i=i+1)begin idx=p+i-k/2;if(idx>=0 && idx<t)total=total+(xv(idx,seed)-zx)*wv(i,seed);end
    expected[p]=p<v?rq(total):zy;
   end
   received=0;start_cycle=cycle;checking=1;
   @(negedge clk);cv=1;do @(posedge clk);while(!cr);@(negedge clk);cv=0;
   for(p=0;p<(t+15)/16;p=p+1)begin
    repeat(p%3)@(negedge clk);
    for(i=0;i<16;i=i+1)sd[i*8+:8]=xv(p*16+i,seed);
    sv=1;do @(posedge clk);while(!sr);@(negedge clk);sv=0;
   end
   wait(done);@(negedge clk);
   if(error || received!=(t+15)/16)$fatal(1,"Unexpected completion/error");
   checking=0;cases=cases+1;
  end
 endtask
 initial begin
  repeat(5)@(negedge clk);rstn=1;
  test_case(1,1,1,0,255,3,123);
  test_case(7,5,11,255,0,4,-451);
  test_case(16,16,5,128,127,5,17);
  test_case(17,13,11,37,129,7,-97);
  test_case(51,51,11,220,7,11,0);
  test_case(101,99,31,127,128,13,231);
  test_case(4096,4093,127,255,255,17,-177);
  test_case(33,0,87,0,0,19,999);
  // Explicit nearest-even positive/negative ties and saturation.
  shift=31;multiplier=32'h40000000;
  test_case(31,31,1,128,128,0,1);
  // seed58 produces weight +1; 256 positions cover every UINT8 input,
  // exercising unsaturated positive/negative half ties at ratio 0.5.
  test_case(256,256,1,128,128,58,0);
  test_case(256,256,1,128,128,58,1);
  // Configuration bounds rejected before input acceptance.
  times=0;kernel=11;@(negedge clk);cv=1;@(posedge clk);@(negedge clk);cv=0;
  if(!error || !done || sr)$fatal(1,"Invalid configuration accepted");
  rstn=0;repeat(3)@(negedge clk);rstn=1;
  // Abort a real operation after channel input, during the tap pipeline.
  times=16;valid_times=16;kernel=11;bias=0;
  @(negedge clk);cv=1;@(posedge clk);@(negedge clk);cv=0;
  sd=128'hffffffffffffffffffffffffffffffff;sv=1;
  do @(posedge clk);while(!sr);@(negedge clk);sv=0;
  wait(dut.state==3);@(negedge clk);rstn=0;
  repeat(3)@(negedge clk);if(mv || sr)$fatal(1,"Reset leaked valid/ready");rstn=1;
  shift=37;test_case(51,51,11,128,128,23,37);
  // Bias addition is checked rather than wrapping INT32 on the FPGA.
  times=1;valid_times=1;kernel=1;xzero=0;yzero=0;bias=32'h7fffffff;
  weights=1;multiplier=32'h40000000;shift=31;
  @(negedge clk);cv=1;@(posedge clk);@(negedge clk);cv=0;
  sd=128'hffffffffffffffffffffffffffffffff;sv=1;
  do @(posedge clk);while(!sr);@(negedge clk);sv=0;
  wait(done);@(negedge clk);if(!error)$fatal(1,"INT32 overflow was not reported");
  rstn=0;repeat(3)@(negedge clk);rstn=1;
  multiplier=32'h40000000;shift=37;test_case(17,17,11,128,127,29,0);
  $display("PASS: %0d depthwise channel arithmetic, asymmetric zero, padding, mask, stalls and reset cases",cases);$finish;
 end
endmodule
