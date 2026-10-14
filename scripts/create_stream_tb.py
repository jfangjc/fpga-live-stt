"""Independent NumPy fixtures and actual op17 stream packets for primitive RTL."""
import hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];dest=ROOT/'verification/stream-vectors';dest.mkdir(parents=True,exist_ok=True)
cases=((1,1,1,1),(17,13,2,11),(51,51,3,21),(101,99,5,29),(256,255,3,39),(65,0,2,41),(17,17,8,1))
def rq(x,z):return np.clip(np.rint(x.astype(np.float32)*np.float32(1/128)).astype(np.int64)+z,0,255)
c=np.arange(256,dtype=np.int64)
for t,v,n,kbase in cases:
    padded=(t+15)//16*16;x=(c[:,None]*17+np.arange(t)[None,:]*7+11)%256
    for stage in range(n):
        kernel=(kbase-1+stage*2)%42+1;seed=11+stage*5;zx=128+stage*17;dzy=127-stage*17;pzy=128+stage*13
        total=np.broadcast_to((c*3-57)[:,None],(256,padded)).copy()
        for d in range(kernel):
            idx=np.arange(padded)+d-kernel//2;inside=(idx>=0)&(idx<t);w=(d*31+c*13+seed*3)%256-128
            total[:,inside]+=w[:,None]*(x[:,idx[inside]]-zx)
        intermediate=rq(total,dzy);intermediate[:,v:]=dzy
        w=(c[:,None]*31+c[None,:]*13+seed*3)%256-128
        y=rq(w.T@(intermediate-dzy)+(c*57-231)[:,None],pzy)
        if stage+1<n:
            x=(y[:,:t]*3+stage*7)%256;x[:,v:]=17+stage*10
    y=y.reshape(16,16,padded//16,16).transpose(2,0,3,1).reshape(-1)
    (dest/f'stream_{t}_{v}_{n}_{kbase}.mem').write_text(''.join(f'{int(q):02x}\n' for q in y))
text=(ROOT/'sim/tb_qn_chain_axis.sv').read_text().replace('module tb_qn_chain_axis;','module tb_qn_stream_axis;')
start=text.index(' task chain_case(');text=text[:start]+r'''
 reg inject_bad=0;
 task stream_case(input integer t,v,n,kbase);
  integer stage,kernel,seed,zx,dzy,pzy,g,k,o,c,p,tile,part,nt,sum;reg [127:0] beat;
  begin
   nt=(t+15)/16;test_slot=0;
   if(!inject_bad)begin
    $readmemh($sformatf("VECTOR_ROOT/stream_%0d_%0d_%0d_%0d.mem",t,v,n,kbase),expected,0,nt*16*16*16-1);
    expected_mac=n*nt*8*256;expect_ack(0,256,256,901,nt*16*16,1,1);
   end else expect_ack(3,256,256,901,0,0,0);
   send(header(17,256,256,t,901),0);beat=0;beat[12:0]=v;beat[23:16]=n;send(beat,0);
   for(stage=0;stage<n;stage=stage+1)begin
    kernel=(kbase-1+stage*2)%42+1;beat=0;beat[4:0]=stage;beat[15:8]=17+stage*10;beat[21:16]=kernel;beat[63:32]=101+stage;send(beat,0);
   end
   for(stage=0;stage<n;stage=stage+1)begin
    kernel=(kbase-1+stage*2)%42+1;seed=11+stage*5;zx=128+stage*17;dzy=127-stage*17;pzy=128+stage*13;
    for(g=0;g<16;g=g+1)for(k=0;k<256;k=k+1)begin
     beat=0;for(o=0;o<16;o=o+1)beat[o*8+:8]=wv(k,g*16+o,seed);send(beat,0);
    end
    for(g=0;g<16;g=g+1)for(o=0;o<16;o=o+1)begin
     sum=0;for(k=0;k<256;k=k+1)sum=sum+wv(k,g*16+o,seed);
     beat=0;beat[31:0]=(128-dzy)*sum+(g*16+o)*57-231;
     beat[63:32]=32'h40000000;beat[69:64]=37;beat[79:72]=pzy;
     if(inject_bad && stage==0 && g==0 && o==0)beat[32]=1;
     send(beat,0);
    end
    for(c=0;c<256;c=c+1)for(part=0;part<3;part=part+1)begin
     beat=0;for(p=0;p<16;p=p+1)if(part*16+p<kernel)beat[p*8+:8]=wv(part*16+p,c,seed);send(beat,0);
    end
    for(c=0;c<256;c=c+1)begin
     beat=0;beat[31:0]=c*3-57;beat[63:32]=32'h40000000;beat[69:64]=37;beat[79:72]=dzy;beat[103:96]=zx;send(beat,0);
    end
   end
   for(stage=0;stage<n-1;stage=stage+1)for(g=0;g<16;g=g+1)begin
    beat=0;for(p=0;p<16;p=p+1)beat[p*8+:8]=((g*16+p)*3+stage*7)%256;send(beat,0);
   end
   for(c=0;c<256;c=c+1)for(tile=0;tile<nt;tile=tile+1)begin
    beat=0;for(p=0;p<16;p=p+1)beat[p*8+:8]=xv(c,tile*16+p,11);
    send(beat,c==255 && tile==nt-1);
   end
   finish(inject_bad);
  end
 endtask
 task reset_core;
  begin @(negedge clk);rstn=0;valid=0;last=0;checking=0;repeat(3)@(negedge clk);rstn=1;end
 endtask
 initial begin
  test_slot=0;repeat(5)@(negedge clk);rstn=1;
  // Interrupt a partial weight stream; no cache state may survive reset.
  send(header(17,256,256,17,901),0);send(128'h10011,0);send(128'h00000065000b1100,0);
  repeat(10)send(0,0);reset_core;
  stream_case(1,1,1,1);
  stream_case(17,13,2,11);
  stream_case(51,51,3,21);
  stream_case(101,99,5,29);
  stream_case(256,255,3,39);
  stream_case(65,0,2,41);
  stream_case(17,17,8,1);
  inject_bad=1;stream_case(17,13,1,11);inject_bad=0;reset_core;
  expect_ack(1,256,256,901,0,0,0);send(header(17,256,256,257,901),1);finish(1);reset_core;
  expect_ack(1,256,256,901,0,0,0);send(header(17,256,256,17,901),0);send(128'h90011,1);finish(1);reset_core;
  expect_ack(1,256,256,901,0,0,0);send(header(17,256,256,17,901),0);send(128'h10011,0);send(128'h00000065002a1100,1);finish(1);reset_core;
  $display("PASS: %0d streamed block arithmetic, eight slots, kernel 1..41, masks, counters, backpressure, malformed packets and mid-weight reset",cases);$finish;
 end
endmodule
'''
text=text.replace('VECTOR_ROOT',dest.as_posix())
(ROOT/'sim/tb_qn_stream_axis.sv').write_bytes(text.encode())
manifest={'complete':True,'independent_numpy_reference':True,'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'cases':cases,'files_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(dest.glob('*.mem'))}}
(dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Generated streamed op17 primitive regression and',len(cases),'independent arithmetic fixtures')
