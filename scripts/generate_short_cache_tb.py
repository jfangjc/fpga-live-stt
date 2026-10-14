"""Exercise slot address boundaries, variable kernels and short-window bounds."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
s=(ROOT/'sim/tb_qn_pair_cache_axis.sv').read_text()
s=s.replace('tb_qn_pair_cache_axis','tb_qn_short_cache_axis')
s=s.replace('integer j,test_slot=0;','integer j,test_slot=0,test_kernel=11,slot_index;\n integer test_slots[0:5];')
s=s.replace('send(header(9,','send(header(12,').replace('send(header(10,','send(header(13,').replace('send(header(11,','send(header(14,')
s=s.replace('expect_ack(0,k,11,tag','expect_ack(0,k,test_kernel,tag').replace('header(13,k,11,','header(13,k,test_kernel,')
s=s.replace('integer c,i;reg [127:0] beat;','integer c,i,h;reg [127:0] beat;')
s=s.replace('''   for(c=0;c<k;c=c+1)begin
    beat=0;for(i=0;i<11;i=i+1)beat[i*8+:8]=wv(i,c,seed);
    send(beat,0);
   end'''.replace('\n+','\n'),'''   for(c=0;c<k;c=c+1)for(h=0;h<2;h=h+1)begin
    beat=0;for(i=0;i<16;i=i+1)if(h*16+i<test_kernel)beat[i*8+:8]=wv(h*16+i,c,seed);
    send(beat,0);
   end'''.replace('\n+','\n'))
s=s.replace('d<11','d<test_kernel').replace('idx=p+d-5','idx=p+d-test_kernel/2')
start=s.index(' initial begin')
s=s[:start]+''' initial begin
  test_slots[0]=0;test_slots[1]=1;test_slots[2]=15;test_slots[3]=16;test_slots[4]=30;test_slots[5]=31;
  repeat(5)@(negedge clk);rstn=1;
  for(slot_index=0;slot_index<6;slot_index=slot_index+1)begin
   test_slot=test_slots[slot_index];test_kernel=11+2*slot_index;
   load(256,256,11+slot_index*5,101+test_slot,127-slot_index*17,128+slot_index*13,1);
   load_dw(256,11+slot_index*5,101+test_slot,128+slot_index*17,127-slot_index*17);
  end
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
  $display("PASS: %0d short-cache retained pair arithmetic, six slot boundaries, six kernels, frame bounds, invalidation, counters, stalls and reset cases",cases);$finish;
 end
endmodule
'''.replace('\n+','\n')
assert 'for(i=0;i<11;' not in s
(ROOT/'sim/tb_qn_short_cache_axis.sv').write_bytes(s.encode())
print('Generated short-cache RTL testbench')
