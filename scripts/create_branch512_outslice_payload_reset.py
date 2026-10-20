"""Exercise a full output-data buffer, beyond the internal load ACK tests."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
tb=(ROOT/'sim/tb_qn_branch512_outslice_reset.sv').read_text().replace('tb_qn_branch512_outslice_reset','tb_qn_branch512_outslice_payload_reset')
tb=tb.replace("   force dut.inner_output_ready=1'b0;", "   // Wait for real output data rather than stopping at the first load ACK.\n   // The force is applied by the monitor after the transaction begins.")
tb=tb.replace('     wait(dut.inner_valid);@(negedge clk);', "     wait(dut.state==15 && dut.inner_valid);force_stall=1;@(negedge clk);\n     force dut.inner_output_ready=1'b0;")
a=tb.index(' initial begin\n  test_slot=0;')
tb=tb[:a]+''' initial begin
  test_slot=0;repeat(5)@(negedge clk);rstn=1;
  interrupt_output(1);
  residual_case(13,7,3,11);
  interrupt_output(0);
  stream_case(17,13,2,11);
  $display("PASS: 2 full output-data buffer reset/replay cases");$finish;
 end
endmodule
'''
dest=ROOT/'sim/tb_qn_branch512_outslice_payload_reset.sv'
if dest.exists():assert dest.read_text()==tb
else:dest.write_text(tb,newline='\n')
tcl=(ROOT/'scripts/branch512_outslice_reset_sim.tcl').read_text().replace('branch512_outslice_reset','branch512_outslice_payload_reset').replace('PASS: 6 full-pipeline reset/replay cases','PASS: 2 full output-data buffer reset/replay cases')
dest=ROOT/'scripts/branch512_outslice_payload_reset_sim.tcl'
if dest.exists():assert dest.read_text()==tcl
else:dest.write_text(tcl,newline='\n')
print('Prepared normal and residual output-data reset tests')
