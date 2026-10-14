"""Extend verified pair tests with retained-chain arithmetic and protocol cases."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
s=(ROOT/'sim/tb_qn_short_cache_axis.sv').read_text()
s=s.replace('tb_qn_short_cache_axis','tb_qn_chain_axis').replace('>400000','>1200000')
s=s.replace(' integer case_start=0;', ' integer case_start=0;\n integer chain_x[0:65535],chain_y[0:65535];')
task=r'''
 task chain_case(input integer t,v,n);
  integer stage,seed,kernel,zx,dzy,pzy,c,p,d,idx,o,tile,g,nt,ss,tag,masked;
  reg signed[63:0] total;reg [127:0] beat;
  begin
   nt=(t+15)/16;
   for(c=0;c<256;c=c+1)for(p=0;p<t;p=p+1)chain_x[c*t+p]=xv(c,p,11);
   for(stage=0;stage<n;stage=stage+1)begin
    ss=stage%3;
    seed=ss==0?11:ss==1?16:26;kernel=ss==0?11:ss==1?13:17;
    zx=ss==0?128:ss==1?145:179;dzy=ss==0?127:ss==1?110:76;pzy=ss==0?128:ss==1?141:167;
    for(c=0;c<256;c=c+1)for(p=0;p<nt*16;p=p+1)begin
     total=c*3-57;
     for(d=0;d<kernel;d=d+1)begin idx=p+d-kernel/2;
      if(idx>=0 && idx<t)total=total+wv(d,c,seed)*(chain_x[c*t+idx]-zx);
     end
     intermediate[c*nt*16+p]=p>=v?dzy:requant(total,dzy);
    end
    for(o=0;o<256;o=o+1)for(p=0;p<nt*16;p=p+1)begin
     total=o*57-231;
     for(c=0;c<256;c=c+1)total=total+wv(c,o,seed)*(intermediate[c*nt*16+p]-dzy);
     if(stage==n-1)expected[((p/16*16+o/16)*16+p%16)*16+o%16]=requant(total,pzy);
     else if(p<t)chain_y[o*t+p]=p>=v?(17+stage*10):((requant(total,pzy)*3+stage*7)%256);
    end
    if(stage<n-1)for(c=0;c<256;c=c+1)for(p=0;p<t;p=p+1)chain_x[c*t+p]=chain_y[c*t+p];
   end
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
'''
s=s.replace(' initial begin',task+'\n initial begin',1)
marker='  for(slot_index=5;slot_index>=0;slot_index=slot_index-1)begin'
s=s.replace(marker,'''  chain_case(1,1,1);
  chain_case(17,13,2);
  chain_case(51,51,3);
  chain_case(101,99,5);
  chain_case(256,255,3);
  chain_case(65,0,2);
  test_slot=0;expect_ack(1,256,256,901,0,0,0);send(header(15,256,256,257,901),1);finish(1);
  expect_ack(1,256,256,901,0,0,0);send(header(15,256,256,17,901),0);send(128'h1000000,1);finish(1);
'''+marker)
s=s.replace('PASS: %0d short-cache retained pair arithmetic','PASS: %0d retained chain and pair arithmetic')
(ROOT/'sim/tb_qn_chain_axis.sv').write_text(s)
print('Generated retained-chain RTL sign-off tests')
