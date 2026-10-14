"""Independent float32 fixtures for the one-channel / four-channel schedule."""
import hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];dest=ROOT/'verification/adaptive-dw';dest.mkdir(parents=True,exist_ok=True)
rng=np.random.default_rng(20261012);configs=[];metadata=[];inputs=[];expected=[];rows=[]
for t in (1,7,13,16,17,51,65,101,256):
 for kernel in (1,11,21,39,41):
  for valid in (0,t//2,t):
   w=rng.integers(-128,128,(4,41),dtype=np.int16).astype(np.int8);w[:,kernel:]=0
   bias=rng.integers(-20000,20001,4,dtype=np.int32)
   mult=(rng.integers(1<<22,1<<24,4,dtype=np.int32).astype(np.int64)*128).astype(np.int32)
   shifts=rng.integers(35,46,4,dtype=np.uint8);xz=rng.integers(0,256,4,dtype=np.uint8);yz=rng.integers(0,256,4,dtype=np.uint8)
   packed=int.from_bytes(w.tobytes(),'little');offset=1312
   for data,width in ((bias.astype('<i4').tobytes(),128),(mult.astype('<i4').tobytes(),128),
                      (sum(int(s)<<(6*i) for i,s in enumerate(shifts)).to_bytes(3,'little'),24),
                      (xz.tobytes(),32),(yz.tobytes(),32)):
    packed|=int.from_bytes(data,'little')<<offset;offset+=width
   assert offset==1656
   configs.append(packed)
   channels=4 if t<=16 else 1;x=rng.integers(0,256,(channels,t),dtype=np.uint8)
   output=np.empty_like(x)
   for c in range(channels):
    acc=np.full(t,int(bias[c]),dtype=np.int64)
    for tap in range(kernel):
     shift=tap-kernel//2;left=max(0,-shift);right=min(t,t-shift)
     if left<right:acc[left:right]+=(x[c,left+shift:right+shift].astype(np.int64)-int(xz[c]))*int(w[c,tap])
    ratio=np.float32(np.ldexp(float(mult[c]),-int(shifts[c])))
    output[c]=np.clip(np.rint(acc.astype(np.float32)*ratio).astype(np.int64)+int(yz[c]),0,255)
    output[c,valid:]=yz[c]
   beats=1 if channels==4 else (t+63)//64
   metadata.append(t|(valid<<16)|(kernel<<32)|(beats<<40))
   for tile in range(beats):
    src=bytearray(64);ref=bytearray(64)
    for b in range(64):
     c=b//16 if channels==4 else 0;p=b%16 if channels==4 else tile*64+b
     src[b]=int(x[c,p]) if p<t else 0;ref[b]=int(output[c,p]) if p<t else int(yz[c])
    inputs.append(int.from_bytes(src,'little'));expected.append(int.from_bytes(ref,'little'))
   rows.append({'times':t,'valid_times':valid,'kernel':kernel,'channels':channels,'beats':beats})
for name,values,bits in (('config',configs,1664),('metadata',metadata,64),('input',inputs,512),('expected',expected,512)):
 (dest/(name+'.mem')).write_text('\n'.join(f'{v:0{bits//4}x}' for v in values)+'\n')
tb=r'''`timescale 1ns/1ps
module tb_adaptive_dw;
 reg clk=0;always #5 clk=~clk;
 reg resetn=0,cv=0,sv=0;wire cr,sr,mv,ml,err,done;
 reg [12:0] times,valid_times;reg [6:0] kernel;
 reg [1663:0] config_data;reg [511:0] data;wire [511:0] result;
 integer cycle=0,received=0,cases_done=0,offset=0;
 wire ready=cycle%11!=3 && cycle%11!=4;
 reg checking=0;
 reg [1663:0] configs[0:134];reg [63:0] metadata[0:134];
 reg [511:0] in_mem[0:251],out_mem[0:251];
 fused_depthwise_adaptive dut(.aclk(clk),.aresetn(resetn),.cfg_valid(cv),.cfg_ready(cr),
  .cfg_times(times),.cfg_valid_times(valid_times),.cfg_kernel(kernel),
  .cfg_weights(config_data[1311:0]),.cfg_bias(config_data[1439:1312]),.cfg_multiplier(config_data[1567:1440]),
  .cfg_shift(config_data[1591:1568]),.cfg_xzero(config_data[1623:1592]),.cfg_yzero(config_data[1655:1624]),
  .s_data(data),.s_valid(sv),.s_ready(sr),.m_data(result),.m_valid(mv),.m_ready(ready),.m_last(ml),.error(err),.done(done));
 always @(posedge clk)begin
  cycle<=cycle+1;
  if(resetn && checking && mv && ready)begin
   if(err || result!==out_mem[received])$fatal(1,"Adaptive DW mismatch at beat %0d",received);
   received<=received+1;
  end
  if(cycle>100000)$fatal(1,"Adaptive DW timeout");
 end
 task cfg(input integer index);begin
  @(negedge clk);config_data=configs[index];times=metadata[index][15:0];valid_times=metadata[index][31:16];kernel=metadata[index][39:32];cv=1;
  @(posedge clk);while(!cr)@(posedge clk);
  @(negedge clk);cv=0;
 end endtask
 task send(input [511:0] value);begin
  @(negedge clk);data=value;sv=1;
  @(posedge clk);while(!sr)@(posedge clk);
  @(negedge clk);sv=0;
 end endtask
 initial begin
  $readmemh("CONFIG",configs);$readmemh("META",metadata);
  $readmemh("INPUT",in_mem);$readmemh("EXPECTED",out_mem);
  repeat(5)@(negedge clk);resetn=1;
  // Reset during a long-kernel four-channel MAC operation.
  cfg(44);send(in_mem[44]);repeat(10)@(negedge clk);resetn=0;
  repeat(4)@(negedge clk);resetn=1;repeat(4)@(negedge clk);
  if(mv || !cr)$fatal(1,"Adaptive DW reset did not flush transaction");
  checking=1;
  for(integer i=0;i<135;i=i+1)begin
   cfg(i);
   for(integer b=0;b<metadata[i][47:40];b=b+1)begin
    if(cycle%7==0)repeat(2)@(negedge clk);
    send(in_mem[offset+b]);
   end
   wait(done);@(negedge clk);
   offset=offset+metadata[i][47:40];
   if(received!=offset || err)$fatal(1,"Adaptive DW boundary mismatch case %0d",i);
   cases_done=cases_done+1;
  end
  checking=0;
  // Invalid parameters on a secondary channel must be rejected in short mode.
  @(negedge clk);config_data=configs[0];times=7;valid_times=7;kernel=11;
  config_data[1591:1586]=0;cv=1;@(posedge clk);@(negedge clk);cv=0;
  if(!done || !err)$fatal(1,"Secondary channel invalid shift accepted");
  $display("PASS: %0d adaptive DW float32 cases, %0d beats, 16/17 boundary, channel scales, stalls and mid-MAC reset",cases_done,received);
  $finish;
 end
endmodule
'''
# The packed configuration uses four 32-bit biases, four multipliers, then
# four six-bit shifts and two four-byte zero-point vectors.
assert len(inputs)==len(expected)
tb=tb.replace('in_mem[0:251],out_mem[0:251]',f'in_mem[0:{len(inputs)-1}],out_mem[0:{len(inputs)-1}]')
for token,name in (('CONFIG','config'),('META','metadata'),('INPUT','input'),('EXPECTED','expected')):
 tb=tb.replace('"'+token+'"','"'+(dest/(name+'.mem')).as_posix()+'"')
(ROOT/'sim/tb_adaptive_dw.sv').write_bytes(tb.encode())
manifest={'complete':True,'hardware_execution':False,'cases':rows,'beats':len(inputs),
          'fixtures_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.glob('*.mem')}}
(dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Created',len(rows),'adaptive schedule cases;',len(inputs),'beats')
