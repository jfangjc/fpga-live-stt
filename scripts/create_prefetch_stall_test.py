"""Exercise replay FIFO fullness, held beats and reset using the actual engine."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'sim/tb_qn_chain_axis.sv').read_text()
text=text.replace('module tb_qn_chain_axis;', 'module tb_qn_chain_prefetch_stalls;')
insert='''
 integer replay_stalls=0,replay_full=0;
 reg replay_was_stalled=0;
 reg [127:0] replay_held;
 reg replay_held_last;
 // Block both sides of the internal handshake together. The sequencer and
 // actual engine therefore agree on precisely which beats were accepted.
 always @(negedge clk)begin
   if(rstn && dut.state==13 && cycle%19<9)begin
     force dut.inner_ready=0;
     force dut.engine.s_axis_tvalid=0;
     replay_stalls=replay_stalls+1;
   end else begin
     release dut.inner_ready;
     release dut.engine.s_axis_tvalid;
   end
 end
 always @(posedge clk)begin
   if(!rstn)replay_was_stalled=0;
   else begin
     if(dut.replay_count==2)replay_full=replay_full+1;
     if(replay_was_stalled && (dut.replay_head!==replay_held || dut.inner_input_last!==replay_held_last))
       $fatal(1,"Retained replay changed while consumer stalled");
     replay_was_stalled=dut.state==13 && dut.replay_count!=0 && !dut.inner_ready;
     replay_held=dut.replay_head;replay_held_last=dut.inner_input_last;
   end
 end
'''
text=text.replace(' initial begin\n  test_slots[0]', insert+' initial begin\n  test_slots[0]')
start=text.index(' initial begin\n  test_slots[0]')
text=text[:start]+''' initial begin
  repeat(5)@(negedge clk);rstn=1;
  test_slot=0;test_kernel=11;load(256,256,11,101,127,128,1);load_dw(256,11,101,128,127);
  test_slot=1;test_kernel=13;load(256,256,16,102,110,141,1);load_dw(256,16,102,145,110);
  test_slot=16;test_kernel=17;load(256,256,26,117,76,167,1);load_dw(256,26,117,179,76);
  // Interrupt a populated replay FIFO, then reload invalidated cache slots.
  fork
    chain_case(17,13,2);
    begin
      wait(dut.state==13 && dut.read_index==9);
      @(negedge clk);rstn=0;checking=0;
      repeat(3)@(negedge clk);
    end
  join_any
  disable fork;
  valid=0;last=0;release dut.inner_ready;release dut.engine.s_axis_tvalid;
  repeat(3)@(negedge clk);rstn=1;
  test_slot=0;test_kernel=11;load(256,256,11,101,127,128,1);load_dw(256,11,101,128,127);
  test_slot=1;test_kernel=13;load(256,256,16,102,110,141,1);load_dw(256,16,102,145,110);
  test_slot=16;test_kernel=17;load(256,256,26,117,76,167,1);load_dw(256,26,117,179,76);
  chain_case(1,1,2);
  chain_case(17,13,3);
  chain_case(65,0,2);
  if(replay_stalls<100 || replay_full<100)$fatal(1,"Replay stall/full coverage absent");
  $display("PASS: prefetch replay stalls=%0d full=%0d held beats, arithmetic and mid-replay reset",replay_stalls,replay_full);$finish;
 end
endmodule
'''
(ROOT/'sim/tb_qn_chain_prefetch_stalls.sv').write_text(text)
script=(ROOT/'scripts/chain_prefetch_sim.tcl').read_text()
script=script.replace('chain_prefetch_sim','chain_prefetch_stall_sim')
script=script.replace('tb_qn_chain_axis','tb_qn_chain_prefetch_stalls')
script=script.replace('{PASS: [0-9]+ retained chain and pair arithmetic}', '{PASS: prefetch replay stalls=}')
(ROOT/'scripts/chain_prefetch_stall_sim.tcl').write_text(script)
print('Created primitive FIFO stall/reset test')
