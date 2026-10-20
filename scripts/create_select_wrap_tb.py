"""Check both legacy overflow rejection and explicit residual INT32 wrapping."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
rtl=(ROOT/'rtl/experimental/fused_affine_quant_compact.sv').read_text()
rtl=rtl.replace('module fused_affine_quant_compact','module fused_affine_quant_select_wrap')
rtl=rtl.replace('output reg m_error\n','output reg m_error,input wire s_wrap\n')
assert 'input wire s_wrap' in rtl
rtl=rtl.replace('added[32]!=added[31] ||','(!s_wrap && added[32]!=added[31]) ||')
(ROOT/'rtl/experimental/fused_affine_quant_select_wrap.sv').write_text(rtl)
normal=(ROOT/'verification/exact-requant/quant.mem').read_text().splitlines()
wrapped=(ROOT/'verification/wrapped-requant/quant.mem').read_text().splitlines()
assert len(normal)==len(wrapped)==2400
assert all((int(a,16)&((1<<440)-1))==(int(b,16)&((1<<440)-1)) for a,b in zip(normal,wrapped))
tb=(ROOT/'sim/tb_exact_requant.sv').read_text().replace('tb_exact_requant','tb_select_wrap_requant')
tb=tb.replace('wire sready,mvalid,error;wire [31:0] output_data;',
              'wire sready,mvalid,error,wsready,wmvalid,werror;wire [31:0] output_data,woutput_data;')
tb=tb.replace('reg [511:0] fixture[0:2399];','reg [511:0] fixture[0:2399],wfixture[0:2399];')
tb=tb.replace('reg held=0;reg [31:0] held_data;reg held_error;',
              'reg held=0;reg [31:0] held_data,wheld_data;reg held_error,wheld_error;')
tb=tb.replace('fused_affine_quant_exact','fused_affine_quant_select_wrap')
tb=tb.replace('svalid,sready,output_data,mvalid,mready,error);',
              "svalid,sready,output_data,mvalid,mready,error,1'b0);\n fused_affine_quant_select_wrap #(.LANES(4)) wrap_dut(clk,rstn,row[127:0],row[255:128],row[383:256],row[407:384],row[439:408],svalid,wsready,woutput_data,wmvalid,mready,werror,1'b1);")
tb=tb.replace('   if(held &&',
              '   if(wsready!==sready || wmvalid!==mvalid)$fatal(1,"Wrap mode handshake differs");\n   if(held && (woutput_data!==wheld_data || werror!==wheld_error))$fatal(1,"Stalled wrapped output changed");\n   if(held &&')
tb=tb.replace('held_error=error;','held_error=error;wheld_data=woutput_data;wheld_error=werror;')
tb=tb.replace('    received<=received+1;',
              '    if(woutput_data!==wfixture[received][471:440] || werror!==wfixture[received][472])$fatal(1,"Wrapped quantizer mismatch at row %0d",received);\n    received<=received+1;')
tb=tb.replace('  repeat(4)@(negedge clk);',f'  $readmemh("{(ROOT/"verification/wrapped-requant/quant.mem").as_posix()}",wfixture);\n  repeat(4)@(negedge clk);')
tb=tb.replace('PASS: 9600 float32-equivalent lanes','PASS: 19200 normal and wrapped float32-equivalent lanes')
(ROOT/'sim/tb_select_wrap_requant.sv').write_text(tb)
tcl=(ROOT/'scripts/compact_requant_sim.tcl').read_text().replace('compact_requant_sim','select_wrap_requant_sim')
tcl=tcl.replace('fused_affine_quant_compact','fused_affine_quant_select_wrap').replace('tb_compact_requant','tb_select_wrap_requant')
tcl=tcl.replace('PASS: 9600 float32-equivalent lanes','PASS: 19200 normal and wrapped float32-equivalent lanes')
(ROOT/'scripts/select_wrap_requant_sim.tcl').write_text(tcl)
print('Generated dual-mode regression preserving normal bias-overflow rejection')
