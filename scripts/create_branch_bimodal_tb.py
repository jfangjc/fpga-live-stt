"""Independent NumPy two-output fixtures, INT32-wrap cases and actual op18 RTL packets."""
from pathlib import Path
import hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1];dest=ROOT/'verification/bimodal-branch-vectors';dest.mkdir(parents=True,exist_ok=True)
cases=((1,1,1,1),(13,7,3,11),(17,17,7,1),(65,0,2,41),(65,63,5,29),(31,30,3,41),(32,31,3,11),(33,33,3,39))
c=np.arange(256,dtype=np.int64)
def rq(value,z):return np.clip(np.rint(value.astype(np.float32)*np.float32(1/128)).astype(np.int64)+z,0,255)
for t,v,n,kbase in cases:
    padded=(t+15)//16*16;x=(c[:,None]*17+np.arange(t)[None,:]*7+11)%256;x[:,v:]=128
    w=(c[:,None]*31+c[None,:]*13+27)%256-128
    b=np.where(c%3==0,-(1<<31)+1024,np.where(c%3==1,(1<<31)-1025,c*57-231))
    identity=np.full((256,padded),128,np.int64);identity[:,:v]=x[:,:v]
    total=w.T@(identity-128)+b[:,None];wrapped=(total+(1<<31))%(1<<32)-(1<<31)
    residual=rq(wrapped,137)
    for stage in range(n):
        kernel=(kbase-1+stage*2)%42+1;seed=11+stage*5;zx=128+stage*17;dzy=127-stage*17;pzy=128+stage*13
        total=np.broadcast_to((c*3-57)[:,None],(256,padded)).copy()
        for d in range(kernel):
            idx=np.arange(padded)+d-kernel//2;inside=(idx>=0)&(idx<t);w=(d*31+c*13+seed*3)%256-128
            total[:,inside]+=w[:,None]*(x[:,idx[inside]]-zx)
        intermediate=rq(total,dzy);intermediate[:,v:]=dzy
        w=(c[:,None]*31+c[None,:]*13+seed*3)%256-128
        y=rq(w.T@(intermediate-dzy)+(c*57-231)[:,None],pzy)
        if stage+1<n:x=(y[:,:t]*3+stage*7)%256;x[:,v:]=17+stage*10
    def packed(a):return a.reshape(16,16,padded//16,16).transpose(2,0,3,1).reshape(-1)
    vector=np.concatenate((packed(residual),packed(y)))
    (dest/f'branch_{t}_{v}_{n}_{kbase}.mem').write_text(''.join(f'{int(q):02x}\n' for q in vector))
tb=(ROOT/'sim/tb_qn_quad_compact_axis.sv').read_text().replace('tb_qn_quad_compact_axis','tb_qn_branch_bimodal_axis')
tb=tb.replace('integer case_start=0;','integer case_start=0,branch_payload=0;reg branch_case=0;')
tb=tb.replace('if(received==0)begin if(out_data', 'if(received==0 || (branch_case && received==branch_payload+1))begin if(out_data')
tb=tb.replace('expected[(received-1)*16+j]', 'expected[(received-1-((branch_case && received>branch_payload+1)?1:0))*16+j]')
tb=tb.replace('   payload=n;bulk=b;', '   branch_case=0;payload=n;bulk=b;')
tb=tb.replace("send(header(17,256,256,17,901),0);send(128'h10011,0);send(128'h00000065000b1100,0);",
              "send(header(18,256,256,17,901),0);send(128'h20011,0);send(128'h0000006500018000,0);send(128'h00000066000b1101,0);")
position=tb.index(' task reset_core;')
task=r'''
 task residual_case(input integer t,v,n,kbase);
  integer stage,i,kernel,seed,zx,dzy,pzy,g,k,o,c,p,tile,part,nt,sum,bias_value;reg [127:0] beat;
  begin
   nt=(t+15)/16;test_slot=0;
   if(!inject_bad)begin
    $readmemh($sformatf("BRANCH_ROOT/branch_%0d_%0d_%0d_%0d.mem",t,v,n,kbase),expected,0,nt*8192-1);
    expected_mac=(n+1)*nt*4*256;expect_ack(0,256,256,901,nt*512+1,1,1);branch_case=1;branch_payload=nt*256;
   end else expect_ack(3,256,256,901,0,0,0);
   send(header(18,256,256,t,901),0);beat=0;beat[12:0]=v;beat[23:16]=n+1;send(beat,0);
   for(stage=0;stage<=n;stage=stage+1)begin
    i=stage-1;kernel=stage==0?1:(kbase-1+i*2)%42+1;
    beat=0;beat[4:0]=stage;beat[15:8]=stage==0?128:17+i*10;beat[21:16]=kernel;beat[63:32]=101+stage;send(beat,0);
   end
   for(stage=0;stage<=n;stage=stage+1)begin
    i=stage-1;kernel=stage==0?1:(kbase-1+i*2)%42+1;seed=stage==0?9:11+i*5;
    zx=stage==0?128:128+i*17;dzy=stage==0?128:127-i*17;pzy=stage==0?137:128+i*13;
    for(g=0;g<16;g=g+1)for(k=0;k<256;k=k+1)begin
     beat=0;for(o=0;o<16;o=o+1)beat[o*8+:8]=wv(k,g*16+o,seed);send(beat,0);
    end
    for(g=0;g<16;g=g+1)for(o=0;o<16;o=o+1)begin
     sum=0;for(k=0;k<256;k=k+1)sum=sum+wv(k,g*16+o,seed);
     c=g*16+o;bias_value=stage==0?(c%3==0?32'h80000400:c%3==1?32'h7ffffbff:c*57-231):c*57-231;
     beat=0;beat[31:0]=(128-dzy)*sum+bias_value;beat[63:32]=32'h40000000;beat[69:64]=37;beat[79:72]=pzy;
     if(inject_bad && stage==0 && g==0 && o==0)beat[32]=1;send(beat,0);
    end
    for(c=0;c<256;c=c+1)for(part=0;part<3;part=part+1)begin
     beat=0;for(p=0;p<16;p=p+1)if(part*16+p<kernel)beat[p*8+:8]=stage==0?1:wv(part*16+p,c,seed);send(beat,0);
    end
    for(c=0;c<256;c=c+1)begin
     beat=0;beat[31:0]=stage==0?0:c*3-57;beat[63:32]=32'h40000000;beat[69:64]=stage==0?30:37;
     beat[79:72]=dzy;beat[103:96]=zx;send(beat,0);
    end
   end
   for(stage=0;stage<n;stage=stage+1)for(g=0;g<16;g=g+1)begin
    beat=0;for(p=0;p<16;p=p+1)beat[p*8+:8]=stage==0?g*16+p:((g*16+p)*3+(stage-1)*7)%256;send(beat,0);
   end
   for(c=0;c<256;c=c+1)for(tile=0;tile<nt;tile=tile+1)begin
    beat=0;for(p=0;p<16;p=p+1)beat[p*8+:8]=(tile*16+p<v)?xv(c,tile*16+p,11):128;
    send(beat,c==255 && tile==nt-1);
   end
   finish(inject_bad);
  end
 endtask
'''.replace('BRANCH_ROOT',dest.as_posix())
tb=tb[:position]+task+tb[position:]
start=tb.index('  stream_case(1,1,1,1);');end=tb.index('  $display("PASS:',start)
tb=tb[:start]+'''  stream_case(7,7,5,29);
  residual_case(1,1,1,1);
  residual_case(13,7,3,11);
  residual_case(17,17,7,1);
  residual_case(65,0,2,41);
  residual_case(65,63,5,29);
  inject_bad=1;residual_case(13,7,3,11);inject_bad=0;reset_core;
  expect_ack(1,256,256,901,0,0,0);send(header(18,256,256,13,901),0);send(128'h1000d,1);finish(1);reset_core;
  expect_ack(1,256,256,901,0,0,0);send(header(18,256,256,0,901),1);finish(1);reset_core;
'''+tb[end:]
tb=tb.replace('streamed block arithmetic, eight slots, kernel 1..41, masks, counters, backpressure, malformed packets and mid-weight reset',
              'two-output residual branches, original-input replay, INT32 bias wrap, masks, eight slots, stalls and malformed packets')
(ROOT/'sim/tb_qn_branch_bimodal_axis.sv').write_text(tb)
tcl=(ROOT/'scripts/quad_compact_sim.tcl').read_text().replace('quad_compact_sim','branch_sim').replace('tb_qn_quad_compact_axis','tb_qn_branch_bimodal_axis')
tcl=tcl.replace('qn_quad_axis.sv qn_quad_inner.sv qn_quad_pw_core.v fused_depthwise_quad.sv fused_affine_quant_compact.sv',
    'qn_branch_axis.sv qn_branch_inner.sv qn_branch_pw_core.v fused_depthwise_quad.sv fused_affine_quant_compact.sv fused_affine_quant_select_wrap.sv')
tcl=tcl.replace('PASS: 14 streamed block arithmetic','PASS: 9 two-output residual branches')
(ROOT/'scripts/branch_bimodal_sim.tcl').write_text(tcl)
paths=list(dest.glob('*.mem'))+[ROOT/'sim/tb_qn_branch_bimodal_axis.sv',ROOT/'scripts/branch_bimodal_sim.tcl',Path(__file__)]
(ROOT/'reports/fused/branch_bimodal_rtl_fixtures.json').write_text(json.dumps({'complete':True,'hardware_execution':False,
    'simulation_passed':False,'arithmetic_cases':len(cases),'total_cases':9,
    'sources_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
print('Generated independent two-output fixtures; FPGA simulation remains pending')
