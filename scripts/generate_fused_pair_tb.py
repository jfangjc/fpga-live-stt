"""Reuse the accepted pointwise transport checker for the paired extension."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
s = (root/'sim/tb_qn_bulk_axis.sv').read_text()
s = s.replace('module tb_qn_bulk_axis;', 'module tb_qn_fused_axis;')
s = s.replace('integer expected[0:1048575];', 'integer expected[0:1048575];\n integer intermediate[0:65535];')
s = s[:s.index(' initial begin')] + ''' task load_dw(input integer k,seed,tag,zx,zy);
  integer c,i;reg [127:0] beat;
  begin
   expect_ack(0,k,11,tag,0,0,0);send(header(7,k,11,0,tag),0);
   for(c=0;c<k;c=c+1)begin
    beat=0;for(i=0;i<11;i=i+1)beat[i*8+:8]=wv(i,c,seed);
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
   for(i=0;i<k;i=i+1)for(p=0;p<nt*16;p=p+1)begin
     inner=i*3-57;
     for(d=0;d<11;d=d+1)begin idx=p+d-5;
      if(idx>=0 && idx<t)inner=inner+wv(d,i,seed)*(xv(i,idx,seed)-zx);
     end
     intermediate[i*nt*16+p]=p>=v?dzy:requant(inner,dzy);
   end
   for(tile=0;tile<nt;tile=tile+1)for(g=0;g<groups;g=g+1)for(p=0;p<16;p=p+1)for(o=0;o<16;o=o+1)begin
    channel=g*16+o;total=channel*57-231;
    for(i=0;i<k;i=i+1)total=total+wv(i,channel,seed)*(intermediate[i*nt*16+tile*16+p]-dzy);
    expected[((tile*groups+g)*16+p)*16+o]=channel<m?requant(total,pzy):0;
   end
   expected_mac=nt*((groups+1)/2)*k;
   expect_ack(0,k,m,tag,nt*groups*16,1,1);send(header(8,k,m,t,tag),0);
   send(v,0);
   for(i=0;i<k;i=i+1)for(tile=0;tile<nt;tile=tile+1)begin
    beat=0;for(p=0;p<16;p=p+1)beat[p*8+:8]=xv(i,tile*16+p,seed);
    send(beat,i==k-1 && tile==nt-1);
   end
   finish(0);
  end
 endtask
 initial begin
  repeat(5)@(negedge clk);rstn=1;
  load(3,17,7,11,37,129,1);load_dw(3,7,11,220,37);
  pair_case(3,17,17,13,7,11,220,37,129);
  pair_case(3,17,51,51,7,11,220,37,129);
  load(256,256,11,12,127,128,1);load_dw(256,11,12,128,127);
  pair_case(256,256,51,51,11,12,128,127,128);
  pair_case(256,256,101,99,11,12,128,127,128);
  load(31,17,17,13,0,0,0);run_case(31,17,16,17,13,0,0,0,0);
  load(31,17,19,14,255,0,1);run_case(31,17,33,19,14,255,0,1,1);
  expect_ack(3,31,17,14,0,0,0);send(header(8,31,17,33,14),0);send(0,1);finish(1);
  load(3,17,7,15,37,129,1);load_dw(3,7,15,220,37);
  expect_ack(1,3,17,15,0,0,0);send(header(8,3,17,17,15),0);send(99,0);send(0,1);finish(1);
  rstn=0;repeat(3)@(negedge clk);rstn=1;
  load(3,17,7,16,37,129,1);load_dw(3,7,16,220,37);
  pair_case(3,17,17,13,7,16,220,37,129);
  $display("PASS: %0d fused depthwise/pointwise arithmetic, retained intermediate, counters, stalls and reset cases",cases);$finish;
 end
endmodule
'''
(root/'sim/tb_qn_fused_axis.sv').write_text(s, encoding='utf-8')
