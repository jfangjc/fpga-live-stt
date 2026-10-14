// Isolated 32-slot protocol-compatible experiment: 512 PW MACs, 64 DW time lanes.
module qn_cached_axis #(parameter MAX_K=256,parameter MAX_M=256)(
 (* X_INTERFACE_PARAMETER="ASSOCIATED_BUSIF S_AXIS:M_AXIS, ASSOCIATED_RESET aresetn" *)
 (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 aclk CLK" *) input wire aclk,
 (* X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *)
 (* X_INTERFACE_INFO="xilinx.com:signal:reset:1.0 aresetn RST" *) input wire aresetn,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TDATA" *) input wire [127:0] s_axis_tdata,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TVALID" *) input wire s_axis_tvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TREADY" *) output wire s_axis_tready,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TLAST" *) input wire s_axis_tlast,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TDATA" *) output wire [127:0] m_axis_tdata,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TVALID" *) output wire m_axis_tvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TREADY" *) input wire m_axis_tready,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TLAST" *) output wire m_axis_tlast,
 output wire busy,output reg done,output wire error
);
 localparam HEADER=0,PASS=1,DWWEIGHTS=2,DWPARAMS=3,ACK=4,DRAIN=5,META=6,CONFIG=7,CHANNEL=8,WAITCORE=9,COREHEADER=10,FETCH=11;
 reg [3:0] state;
 reg [31:0] slot_dw_valid;reg [31:0] slot_dw_tag[0:31];
 reg [4:0] slot;wire [4:0] header_slot=s_axis_tdata[44:40];
 reg [4:0] slot_kernel[0:31];reg [4:0] kernel;reg weight_half;reg [127:0] weight_low;
 wire [4:0] core_slot=state==HEADER?header_slot:slot;
 wire dw_cache=slot_dw_valid[header_slot];wire [31:0] dw_tag=slot_dw_tag[header_slot];
 reg local_error;
 reg [15:0] cached_channels,channels,outputs;
 reg [31:0] tag,status;
 reg [12:0] times,valid_times;
 reg [9:0] channel;
 reg [12:0] received_tiles;
 reg [31:0] pair_cycles,cycles_snapshot;
 wire [7:0] op=s_axis_tdata[39:32];
 wire [15:0] hk=s_axis_tdata[79:64],hm=s_axis_tdata[63:48],ht=s_axis_tdata[95:80];
 wire dw_header_valid=s_axis_tdata[31:0]==32'h32434e51 && s_axis_tdata[47:45]==0 &&
  hk==256 && (hm>=11 && hm<=21 && hm[0]) && ht==0 && s_axis_tdata[127:96]!=0 && !s_axis_tlast;
 wire pair_header_valid=s_axis_tdata[31:0]==32'h32434e51 && s_axis_tdata[47:45]==0 &&
  hk==256 && hm==256 && ht>0 && ht<=256 &&
  hk*((ht+15)>>4)<=4096 && !s_axis_tlast && dw_cache && s_axis_tdata[127:96]==dw_tag;
 wire load_header_valid=op==12 && s_axis_tdata[31:0]==32'h32434e51 && s_axis_tdata[47:45]==0 && hk==256 && hm==256 && ht==0 && s_axis_tdata[127:96]!=0 && !s_axis_tlast;
 wire intercepted=!load_header_valid;
 wire accept=s_axis_tvalid && s_axis_tready;
 wire cs_ready,cm_valid,cm_last,core_busy,core_done,core_error;
 wire [127:0] cm_data;
 wire dc_ready,ds_ready,dm_valid,dm_last,dw_error,dw_done;
 wire [511:0] dw_wide_data;
 reg [511:0] input_pack;
 reg [1:0] input_part,output_part;
 reg input_pending;
 reg [12:0] output_word;
 wire [127:0] dm_data=dw_wide_data[output_part*128+:128];
 wire output_part_final=output_part==3 || output_word==((times+15)>>4)-1;
 always @(posedge aclk)begin
  if(!aresetn || (state==CONFIG && dc_ready))begin
   input_pack<=0;input_part<=0;input_pending<=0;output_part<=0;output_word<=0;
  end else begin
   if(state==CHANNEL && accept)begin
    input_pack[input_part*128+:128]<=s_axis_tdata;
    if(input_part==3 || received_tiles==((times+15)>>4)-1)begin input_pending<=1;input_part<=0;end
    else input_part<=input_part+1;
   end
   if(state==CHANNEL && input_pending && ds_ready)begin input_pending<=0;input_pack<=0;end
   if(in_pair && dm_valid && cs_ready)begin
    output_word<=output_word+1;
    if(output_part_final)output_part<=0;else output_part<=output_part+1;
   end
  end
 end
 (* ram_style="block" *) reg [167:0] dw_weights[0:8191];
 (* ram_style="block" *) reg [109:0] dw_params[0:8191];
 reg [109:0] params;reg [167:0] current_weights;
 always @(posedge aclk)begin params<=dw_params[{slot,channel[7:0]}];current_weights<=dw_weights[{slot,channel[7:0]}];end
 wire in_pair=state==FETCH || state==CONFIG || state==CHANNEL || state==WAITCORE;
 wire local_response=state==ACK;
 wire trailer_ready=!(in_pair && cm_last && cycles_snapshot==0);
 wire cs_valid=state==HEADER && !intercepted?s_axis_tvalid:state==COREHEADER?1'b1:
               state==PASS?s_axis_tvalid:in_pair?dm_valid:1'b0;
 wire [127:0] cs_data=state==COREHEADER?{tag,3'b0,times,channels,outputs,8'b0,8'd6,32'h32434e51}:
                     in_pair?dm_data:state==HEADER?{s_axis_tdata[127:48],8'b0,8'd4,s_axis_tdata[31:0]}:s_axis_tdata;
 wire cs_last=state==COREHEADER?1'b0:in_pair?(dm_last && output_part_final && channel==channels-1):s_axis_tlast;
 assign s_axis_tready=aresetn && (state==HEADER?(intercepted?1'b1:cs_ready):
  state==PASS?cs_ready:state==DWWEIGHTS || state==DWPARAMS || state==DRAIN || state==META?1'b1:
  state==CHANNEL?(ds_ready && !input_pending):1'b0);
 assign m_axis_tvalid=aresetn && (local_response || ((state==PASS || in_pair) && cm_valid && trailer_ready));
 assign m_axis_tdata=local_response?{tag,outputs,channels,status,32'h32524e51}:
                    state==WAITCORE && cm_last?{cycles_snapshot,cm_data[95:0]}:cm_data;
 assign m_axis_tlast=local_response || cm_last;
 assign busy=state!=HEADER;
 assign error=local_error || core_error || dw_error;
 qn_short_cache_core #(.MAX_K(MAX_K),.MAX_M(MAX_M)) pointwise(
  .aclk(aclk),.aresetn(aresetn),.cache_select(core_slot),.s_axis_tdata(cs_data),.s_axis_tvalid(cs_valid),.s_axis_tready(cs_ready),.s_axis_tlast(cs_last),
  .m_axis_tdata(cm_data),.m_axis_tvalid(cm_valid),.m_axis_tready(m_axis_tready && (state==PASS || in_pair) && trailer_ready),.m_axis_tlast(cm_last),
  .busy(core_busy),.done(core_done),.error(core_error));
 fused_depthwise_channel_wide #(.MAX_T(256),.MAX_KERNEL(21),.LANES(64)) depthwise(
  .aclk(aclk),.aresetn(aresetn),.cfg_valid(state==CONFIG),.cfg_ready(dc_ready),
  .cfg_times(times),.cfg_valid_times(valid_times),.cfg_kernel({2'b0,slot_kernel[slot]}),.cfg_weights(current_weights),
  .cfg_bias(params[31:0]),.cfg_multiplier(params[63:32]),.cfg_shift(params[69:64]),
  .cfg_xzero(params[109:102]),.cfg_yzero(params[77:70]),
  .s_data(input_pack),.s_valid(state==CHANNEL && input_pending),.s_ready(ds_ready),
  .m_data(dw_wide_data),.m_valid(dm_valid),.m_ready(cs_ready && in_pair && output_part_final),.m_last(dm_last),.error(dw_error),.done(dw_done));
 always @(posedge aclk)begin
  if(!aresetn)begin
   state<=HEADER;slot_dw_valid<=0;slot<=0;local_error<=0;cached_channels<=0;channels<=0;outputs<=0;
   for(integer reset_slot=0;reset_slot<32;reset_slot=reset_slot+1)slot_dw_tag[reset_slot]<=0;tag<=0;status<=0;times<=0;valid_times<=0;channel<=0;received_tiles<=0;
   pair_cycles<=0;cycles_snapshot<=0;done<=0;kernel<=0;weight_half<=0;weight_low<=0;
   for(integer r=0;r<32;r=r+1)slot_kernel[r]<=0;
  end else begin
   done<=0;
   if(state==META || in_pair)pair_cycles<=pair_cycles+1;
   // Snapshot once the core presents its final beat, so stalls cannot change it.
   if(in_pair && cm_valid && cm_last && cycles_snapshot==0)cycles_snapshot<=pair_cycles+1;
   case(state)
    HEADER:if(accept)begin
     slot<=header_slot;channels<=hk;outputs<=hm;tag<=s_axis_tdata[127:96];status<=0;local_error<=0;channel<=0;
     if(op==13)begin
      slot_dw_valid[header_slot]<=0;
      if(dw_header_valid)begin kernel<=hm[4:0];weight_half<=0;state<=DWWEIGHTS;end
      else begin status<=1;local_error<=1;state<=s_axis_tlast?ACK:DRAIN;end
     end else if(op==14)begin
      if(pair_header_valid)begin times<=ht;pair_cycles<=0;cycles_snapshot<=0;state<=META;end
      else begin status<=3;local_error<=1;state<=s_axis_tlast?ACK:DRAIN;end
     end else if(load_header_valid)begin
      // Only this slot is invalidated by its pointwise load.
      slot_dw_valid[header_slot]<=0;
      state<=PASS;
     end else begin local_error<=1;status<=1;state<=s_axis_tlast?ACK:DRAIN;end
    end
    PASS:if(core_done)begin state<=HEADER;done<=1;end
    DWWEIGHTS:if(accept)begin
     if(!weight_half)begin
      weight_low<=s_axis_tdata;weight_half<=1;
      for(integer b=0;b<16;b=b+1)if(b>=kernel && s_axis_tdata[b*8+:8]!=0)begin status<=2;local_error<=1;state<=s_axis_tlast?ACK:DRAIN;end
      if(s_axis_tlast)begin status<=2;local_error<=1;state<=ACK;end
     end else begin
      dw_weights[{slot,channel[7:0]}]<={s_axis_tdata[39:0],weight_low};weight_half<=0;
      if(channel==channels-1)begin channel<=0;state<=DWPARAMS;end
      else channel<=channel+1;
      for(integer b=0;b<16;b=b+1)if(b+16>=kernel && s_axis_tdata[b*8+:8]!=0)begin status<=2;local_error<=1;state<=s_axis_tlast?ACK:DRAIN;end
      if(s_axis_tlast)begin status<=2;local_error<=1;state<=ACK;end
     end
    end
    DWPARAMS:if(accept)begin
     dw_params[{slot,channel[7:0]}]<={s_axis_tdata[103:96],24'b0,s_axis_tdata[79:72],s_axis_tdata[69:64],s_axis_tdata[63:0]};
     if(s_axis_tdata[127:104]!=0 || s_axis_tdata[95:80]!=0 || s_axis_tdata[71:70]!=0 ||
        s_axis_tdata[63] || s_axis_tdata[69:64]==0 || s_axis_tdata[69:64]==63 ||
        s_axis_tlast!=(channel==channels-1))begin
      status<=2;local_error<=1;state<=s_axis_tlast?ACK:DRAIN;
     end else if(channel==channels-1)begin cached_channels<=channels;slot_dw_tag[slot]<=tag;slot_dw_valid[slot]<=1;slot_kernel[slot]<=kernel;state<=ACK;end
     else channel<=channel+1;
    end
    ACK:if(m_axis_tready)begin state<=HEADER;done<=1;end
    DRAIN:if(accept && s_axis_tlast)state<=ACK;
    META:if(accept)begin
     if(s_axis_tdata[127:13]!=0 || s_axis_tdata[12:0]>times || s_axis_tlast)begin
      local_error<=1;slot_dw_valid[slot]<=0;status<=1;state<=s_axis_tlast?ACK:DRAIN;
     end else begin valid_times<=s_axis_tdata[12:0];received_tiles<=0;state<=COREHEADER;end
    end
    COREHEADER:if(cs_ready)state<=FETCH;
    FETCH:state<=CONFIG;
    CONFIG:if(dc_ready)begin received_tiles<=0;state<=CHANNEL;end
    CHANNEL:begin
     if(accept)begin
      if(s_axis_tlast!=(channel==channels-1 && received_tiles==((times+15)>>4)-1))begin local_error<=1;slot_dw_valid[slot]<=0;end
      received_tiles<=received_tiles+1;
     end
     if(dw_done)begin
      if(dw_error)begin local_error<=1;slot_dw_valid[slot]<=0;end
      if(channel==channels-1)state<=WAITCORE;
      else begin channel<=channel+1;state<=FETCH;end
     end
    end
    WAITCORE:if(core_done)begin state<=HEADER;done<=1;end
    default:begin state<=HEADER;local_error<=1;slot_dw_valid[slot]<=0;end
   endcase
  end
 end
endmodule
