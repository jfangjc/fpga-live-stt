"""Isolate a registered block-output experiment; preserve failed slice166."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def save(name,text):
    path=ROOT/name
    if path.exists(): assert path.read_text()==text,path
    else: path.write_text(text,newline='\n')

axis=(ROOT/'rtl/experimental/qn_branch512_slice_axis.sv').read_text()
axis=axis.replace('wire inner_ready,inner_valid,inner_last,inner_busy,inner_done,inner_error;',
'''wire inner_ready,inner_busy,inner_error;
 wire raw_valid,raw_last,raw_done;wire [127:0] raw_data;
 reg inner_valid,inner_last;reg [127:0] inner_data;
 reg completion_pending;
 wire inner_done=completion_pending || raw_done;
 wire raw_ready=!inner_valid || inner_output_ready;
 // One-beat elastic output buffer cuts the pointwise mux to sequencer path.
 // Completion can precede consumption of the buffered load ACK; retain it.
 always @(posedge aclk)begin
   if(!aresetn)begin
     inner_valid<=0;inner_last<=0;inner_data<=0;completion_pending<=0;
   end else begin
     if(raw_ready)begin
       inner_valid<=raw_valid;
       if(raw_valid)begin inner_data<=raw_data;inner_last<=raw_last;end
     end
     if(raw_done)completion_pending<=1;
     if((state==LOADWAIT && inner_done) || (state==PASS && inner_done) ||
        ((state==LOADHEAD || state==RUNHEAD) && inner_ready))completion_pending<=0;
   end
 end''').replace(' wire [127:0] inner_data;\n','')
axis=axis.replace('.m_axis_tdata(inner_data)', '.m_axis_tdata(raw_data)').replace(
    '.m_axis_tvalid(inner_valid),.m_axis_tready(inner_output_ready),.m_axis_tlast(inner_last)',
    '.m_axis_tvalid(raw_valid),.m_axis_tready(raw_ready),.m_axis_tlast(raw_last)').replace('.done(inner_done)', '.done(raw_done)')
axis=axis.replace('LOADACK:if(inner_valid)', 'LOADACK:if(inner_valid && inner_output_ready)').replace('COUNTER:if(inner_valid)', 'COUNTER:if(inner_valid && inner_output_ready)')
save('rtl/experimental/qn_branch512_outslice_axis.sv',axis)
for kind in ('axis','reset'):
    tb=(ROOT/f'sim/tb_qn_branch512_slice_{kind}.sv').read_text().replace(f'tb_qn_branch512_slice_{kind}',f'tb_qn_branch512_outslice_{kind}')
    if kind=='reset':
        index=tb.index(' initial begin\n  test_slot=0;')
        task=''' task interrupt_output(input reg branch);
  reg [127:0] held;reg held_last;
  begin
   // Block outer consumption, including internal load ACKs.
   force dut.inner_output_ready=1'b0;
   fork : interrupted_output
    begin
     if(branch)residual_case(13,7,3,11);else stream_case(17,13,2,11);
     $fatal(1,"Transaction completed despite blocked output register");
    end
    begin
     wait(dut.inner_valid);@(negedge clk);
     held=dut.inner_data;held_last=dut.inner_last;
     repeat(5)begin
      @(negedge clk);
      if(!dut.inner_valid || dut.inner_data!==held || dut.inner_last!==held_last)
       $fatal(1,"Output register changed under backpressure");
     end
     checking=0;rstn=0;valid=0;last=0;disable interrupted_output;
    end
   join
   repeat(3)@(negedge clk);
   if(dut.inner_valid || dut.completion_pending)$fatal(1,"Output/completion survived reset");
   release dut.inner_output_ready;
   rstn=1;force_stall=0;repeat(5)@(negedge clk);
   if(out_valid || busy || error)$fatal(1,"Stale response after output reset");
  end
 endtask
'''
        tb=tb[:index]+task+tb[index:]
        tb=tb.replace('  interrupt_slice(1);','  interrupt_output(1);\n  residual_case(13,7,3,11);\n  interrupt_output(0);\n  stream_case(17,13,2,11);\n  interrupt_slice(1);')
        tb=tb.replace('PASS: 4 full-pipeline reset/replay cases','PASS: 6 full-pipeline reset/replay cases')
    save(f'sim/tb_qn_branch512_outslice_{kind}.sv',tb)
    source=f'scripts/branch512_slice_{"fast" if kind=="axis" else "reset"}_sim.tcl'
    tcl=(ROOT/source).read_text().replace('branch512_slice_fast','branch512_outslice_fast').replace('branch512_slice_reset','branch512_outslice_reset').replace('qn_branch512_slice_axis.sv','qn_branch512_outslice_axis.sv').replace('tb_qn_branch512_slice_axis','tb_qn_branch512_outslice_axis').replace('PASS: 4 full-pipeline reset/replay cases','PASS: 6 full-pipeline reset/replay cases')
    save(source.replace('branch512_slice_','branch512_outslice_'),tcl)
print('Prepared separate output register and six reset/replay cases')
