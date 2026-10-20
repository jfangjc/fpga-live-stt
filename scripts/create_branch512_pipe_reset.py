"""Interrupt a full elastic quantizer pipeline, then prove clean replay."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
tb=(ROOT/'sim/tb_qn_branch512_pipe_axis.sv').read_text()
tb=tb[:tb.index(' initial begin\n')]+''' task interrupt_quantizer(input reg branch);
  begin
   fork : interrupted
    begin
     if(branch)residual_case(13,7,3,11);else stream_case(17,13,2,11);
     $fatal(1,"Transaction unexpectedly completed before pipeline reset");
    end
    begin
     wait(dut.engine.pointwise.buffer_valid);
     @(negedge clk);force_stall=1;
     wait(dut.engine.pointwise.buffer_valid && !dut.engine.pointwise.quant_ready);
     if(dut.engine.pointwise.buffer_wrap!==branch)$fatal(1,"Incorrect buffered wrap mode");
     repeat(3)@(negedge clk);
     checking=0;rstn=0;valid=0;last=0;
     disable interrupted;
    end
   join
   repeat(3)@(negedge clk);
   if(dut.engine.pointwise.buffer_valid)$fatal(1,"Buffered quantizer input survived reset");
   rstn=1;force_stall=0;repeat(5)@(negedge clk);
   if(out_valid || busy || error)$fatal(1,"Stale response after quantizer reset");
  end
 endtask
 initial begin
  test_slot=0;repeat(5)@(negedge clk);rstn=1;
  interrupt_quantizer(1);
  residual_case(13,7,3,11);
  interrupt_quantizer(0);
  stream_case(17,13,2,11);
  $display("PASS: 2 full-pipeline reset/replay cases, buffered normal and wrapped arithmetic");$finish;
 end
endmodule
'''
tb=tb.replace('tb_qn_branch512_pipe_axis','tb_qn_branch512_pipe_reset')
(ROOT/'sim/tb_qn_branch512_pipe_reset.sv').write_text(tb)
sim=(ROOT/'scripts/branch512_pipe_fast_sim.tcl').read_text()
sim=sim.replace('branch512_pipe_fast_sim','branch512_pipe_reset_sim').replace('tb_qn_branch512_pipe_axis','tb_qn_branch512_pipe_reset')
sim=sim.replace('PASS: 25 two-output residual branches','PASS: 2 full-pipeline reset/replay cases')
(ROOT/'scripts/branch512_pipe_reset_sim.tcl').write_text(sim)
print('Prepared actual controller/quantizer reset coverage with the conformant simulation MAC')
