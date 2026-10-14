`timescale 1ns/1ps
module tb_qn_chain_prefetch_vectors;
 reg clk=0;always #5 clk=~clk;
 reg rstn=0,valid=0,last=0,ready=0,force_stall=0;
 reg [127:0] data=0;
 wire in_ready,out_valid,out_last,busy,done,error;
 wire [127:0] out_data;
 qn_cached_axis dut(clk,rstn,data,valid,in_ready,last,out_data,out_valid,ready,out_last,busy,done,error);
 integer expected[0:1048575];
 integer intermediate[0:65535];
 integer received=0,cycle=0,cases=0,payload=0,expected_mac=0;
 integer case_start=0;
 integer chain_x[0:65535],chain_y[0:65535];
 reg checking=0,bulk=0,quantized=0,previous_stall=0;
 reg [127:0] held_data,expected_header;
 reg held_last;
 integer j,test_slot=0,test_kernel=11,slot_index;
 integer test_slots[0:5];
 always @(negedge clk)begin cycle=cycle+1;ready=!force_stall && cycle%11>2;end
 always @(posedge clk)begin
  if(!rstn)begin previous_stall=0;received=0;end
  else begin
   if(checking && cycle-case_start>1200000)$fatal(1,"Case watchdog cases=%0d state=%0d received=%0d expected=%0d",cases,dut.state,received,payload);
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
  header={tag[31:0],t[15:0],k[15:0],m[15:0],test_slot[7:0],op[7:0],32'h32434e51};
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
   expect_ack(0,k,m,tag,0,0,0);send(header(12,k,m,0,tag),0);
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
   expected_mac=nt*((groups+1)/2)*k;
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
 task load_dw(input integer k,seed,tag,zx,zy);
  integer c,i,h;reg [127:0] beat;
  begin
   expect_ack(0,k,test_kernel,tag,0,0,0);send(header(13,k,test_kernel,0,tag),0);
   for(c=0;c<k;c=c+1)for(h=0;h<2;h=h+1)begin
    beat=0;for(i=0;i<16;i=i+1)if(h*16+i<test_kernel)beat[i*8+:8]=wv(h*16+i,c,seed);
    send(beat,0);
   end
   for(c=0;c<k;c=c+1)begin
    beat=0;beat[31:0]=c*3-57;beat[63:32]=32'h40000000;beat[69:64]=37;
    beat[79:72]=zy;beat[103:96]=zx;send(beat,c==k-1);
   end
   finish(0);
  end
 endtask
 task pair_case(input integer k,m,t,v,seed,tag,zx,dzy,pzy);
  integer nt,groups,tile,g,p,o,i,d,idx,channel;reg signed[63:0] total,inner;
  reg[127:0] beat;
  begin
   nt=(t+15)/16;groups=(m+15)/16;
   $readmemh($sformatf("C:/Users/jfang/Documents/Vivado/Prototype_v2/verification/chain-prefetch-vectors/pair_%0d_%0d_%0d_%0d_%0d_%0d_%0d.mem",t,v,seed,test_kernel,zx,dzy,pzy),expected,0,nt*groups*16*16-1);
   expected_mac=nt*((groups+1)/2)*k;
   expect_ack(0,k,m,tag,nt*groups*16,1,1);send(header(14,k,m,t,tag),0);
   send(v,0);
   for(i=0;i<k;i=i+1)for(tile=0;tile<nt;tile=tile+1)begin
    beat=0;for(p=0;p<16;p=p+1)beat[p*8+:8]=xv(i,tile*16+p,seed);
    send(beat,i==k-1 && tile==nt-1);
   end
   finish(0);
  end
 endtask

 task chain_case(input integer t,v,n);
  integer stage,seed,kernel,zx,dzy,pzy,c,p,d,idx,o,tile,g,nt,ss,tag,masked;
  reg signed[63:0] total;reg [127:0] beat;
  begin
   nt=(t+15)/16;
   $readmemh($sformatf("C:/Users/jfang/Documents/Vivado/Prototype_v2/verification/chain-prefetch-vectors/chain_%0d_%0d_%0d.mem",t,v,n),expected,0,nt*16*16*16-1);
   expected_mac=n*nt*8*256;test_slot=0;
   expect_ack(0,256,256,901,nt*16*16,1,1);send(header(15,256,256,t,901),0);
   beat=0;beat[12:0]=v;beat[23:16]=n;send(beat,0);
   for(stage=0;stage<n;stage=stage+1)begin
    ss=stage%3;beat=0;beat[4:0]=ss==0?0:ss==1?1:16;
    beat[15:8]=17+stage*10;beat[63:32]=ss==0?101:ss==1?102:117;send(beat,0);
   end
   for(stage=0;stage<n-1;stage=stage+1)for(g=0;g<16;g=g+1)begin
    beat=0;for(p=0;p<16;p=p+1)beat[p*8+:8]=((g*16+p)*3+stage*7)%256;send(beat,0);
   end
   for(c=0;c<256;c=c+1)for(tile=0;tile<nt;tile=tile+1)begin
    beat=0;for(p=0;p<16;p=p+1)beat[p*8+:8]=xv(c,tile*16+p,11);
    send(beat,c==255 && tile==nt-1);
   end
   finish(0);
  end
 endtask

 initial begin
  test_slots[0]=0;test_slots[1]=1;test_slots[2]=15;test_slots[3]=16;test_slots[4]=30;test_slots[5]=31;
  repeat(5)@(negedge clk);rstn=1;
  for(slot_index=0;slot_index<6;slot_index=slot_index+1)begin
   test_slot=test_slots[slot_index];test_kernel=11+2*slot_index;
   load(256,256,11+slot_index*5,101+test_slot,127-slot_index*17,128+slot_index*13,1);
   load_dw(256,11+slot_index*5,101+test_slot,128+slot_index*17,127-slot_index*17);
  end
  chain_case(1,1,1);
  chain_case(17,13,2);
  chain_case(51,51,3);
  chain_case(101,99,5);
  chain_case(256,255,3);
  chain_case(65,0,2);
  test_slot=0;expect_ack(1,256,256,901,0,0,0);send(header(15,256,256,257,901),1);finish(1);
  expect_ack(1,256,256,901,0,0,0);send(header(15,256,256,17,901),0);send(128'h1000000,1);finish(1);
  for(slot_index=5;slot_index>=0;slot_index=slot_index-1)begin
   test_slot=test_slots[slot_index];test_kernel=11+2*slot_index;
   pair_case(256,256,17,13,11+slot_index*5,101+test_slot,128+slot_index*17,127-slot_index*17,128+slot_index*13);
  end
  test_slot=0;test_kernel=11;pair_case(256,256,51,51,11,101,128,127,128);
  test_slot=16;test_kernel=17;pair_case(256,256,101,99,26,117,179,76,167);
  pair_case(256,256,256,255,26,117,179,76,167);
  // Frame 257 exceeds the retained input bank; no truncated addressing allowed.
  expect_ack(3,256,256,117,0,0,0);send(header(14,256,256,257,117),0);send(0,1);finish(1);
  test_slot=31;load(256,256,44,202,37,129,1);
  expect_ack(3,256,256,202,0,0,0);send(header(14,256,256,17,202),0);send(0,1);finish(1);
  test_slot=1;test_kernel=13;pair_case(256,256,17,0,16,102,145,110,141);
  test_slot=31;test_kernel=17;load_dw(256,44,202,220,37);pair_case(256,256,17,13,44,202,220,37,129);
  expect_ack(1,256,18,202,0,0,0);send(header(13,256,18,0,202),1);finish(1);
  // A reserved byte in the second DW beat must reject the packet.
  test_slot=30;expect_ack(2,256,11,131,0,0,0);send(header(13,256,11,0,131),0);send(0,0);send(128'h10000000000000000,1);finish(1);
  rstn=0;repeat(3)@(negedge clk);rstn=1;
  for(test_slot=0;test_slot<32;test_slot=test_slot+1)begin
   expect_ack(3,256,256,101+test_slot,0,0,0);
   send(header(14,256,256,17,101+test_slot),0);send(0,1);finish(1);
  end
  test_slot=31;test_kernel=15;load(256,256,11,301,127,128,1);load_dw(256,11,301,128,127);
  pair_case(256,256,17,13,11,301,128,127,128);
  $display("PASS: %0d retained chain and pair arithmetic, six slot boundaries, six kernels, frame bounds, invalidation, counters, stalls and reset cases",cases);$finish;
 end
endmodule
