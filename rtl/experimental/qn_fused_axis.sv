// Isolated QNC2 extension: original 512-MAC bulk core plus retained DW11 stage.
// LOAD_DW=7: K=channels, M=11, T=0. K weight beats then K parameter beats.
// Parameter words: bias, multiplier, shift|(yzero<<8), xzero. Tag matches PW.
// RUN_PAIR=8: same header as RUN_BULK, then valid_times in a metadata beat,
// then channel-major padded UINT8 inputs. Intermediate output stays in FPGA.
module qn_cached_axis #(parameter MAX_K=1024,parameter MAX_M=1024)(
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
 localparam HEADER=0,PASS=1,DWWEIGHTS=2,DWPARAMS=3,ACK=4,DRAIN=5,META=6,CONFIG=7,CHANNEL=8,WAITCORE=9,COREHEADER=10;
 reg [3:0] state;
 reg dw_cache,local_error;
 reg [15:0] cached_channels,channels,outputs;
 reg [31:0] dw_tag,tag,status;
 reg [12:0] times,valid_times;
 reg [9:0] channel;
 reg [12:0] received_tiles;
 reg [31:0] pair_cycles,cycles_snapshot;
 wire [7:0] op=s_axis_tdata[39:32];
 wire [15:0] hk=s_axis_tdata[79:64],hm=s_axis_tdata[63:48],ht=s_axis_tdata[95:80];
 wire dw_header_valid=s_axis_tdata[31:0]==32'h32434e51 && s_axis_tdata[47:40]==0 &&
  hk>0 && hk<=MAX_K && hm==11 && ht==0 && s_axis_tdata[127:96]!=0 && !s_axis_tlast;
 wire pair_header_valid=s_axis_tdata[31:0]==32'h32434e51 && s_axis_tdata[47:40]==0 &&
  hk>0 && hk<=MAX_K && hm>0 && hm<=MAX_M && ht>0 && ht<=4096 &&
  hk*((ht+15)>>4)<=65536 && !s_axis_tlast && dw_cache && hk==cached_channels && s_axis_tdata[127:96]==dw_tag;
 wire intercepted=op==7 || op==8;
 wire accept=s_axis_tvalid && s_axis_tready;
 wire cs_ready,cm_valid,cm_last,core_busy,core_done,core_error;
 wire [127:0] cm_data;
 wire dc_ready,ds_ready,dm_valid,dm_last,dw_error,dw_done;
 wire [127:0] dm_data;
 (* ram_style="distributed" *) reg [87:0] dw_weights[0:MAX_K-1];
 (* ram_style="distributed" *) reg [109:0] dw_params[0:MAX_K-1];
 wire [109:0] params=dw_params[channel];
 wire in_pair=state==CONFIG || state==CHANNEL || state==WAITCORE;
 wire local_response=state==ACK;
 wire trailer_ready=!(in_pair && cm_last && cycles_snapshot==0);
 wire cs_valid=state==HEADER && !intercepted?s_axis_tvalid:state==COREHEADER?1'b1:
               state==PASS?s_axis_tvalid:in_pair?dm_valid:1'b0;
 wire [127:0] cs_data=state==COREHEADER?{tag,3'b0,times,channels,outputs,8'b0,8'd6,32'h32434e51}:
                     in_pair?dm_data:s_axis_tdata;
 wire cs_last=state==COREHEADER?1'b0:in_pair?(dm_last && channel==channels-1):s_axis_tlast;
 assign s_axis_tready=aresetn && (state==HEADER?(op==7 || (op==8 && !pair_header_valid)?1'b1:cs_ready):
  state==PASS?cs_ready:state==DWWEIGHTS || state==DWPARAMS || state==DRAIN || state==META?1'b1:
  state==CHANNEL?ds_ready:1'b0);
 assign m_axis_tvalid=aresetn && (local_response || ((state==PASS || in_pair) && cm_valid && trailer_ready));
 assign m_axis_tdata=local_response?{tag,outputs,channels,status,32'h32524e51}:
                    state==WAITCORE && cm_last?{cycles_snapshot,cm_data[95:0]}:cm_data;
 assign m_axis_tlast=local_response || cm_last;
 assign busy=state!=HEADER;
 assign error=local_error || core_error || dw_error;
 qn_bulk_core #(.MAX_K(MAX_K),.MAX_M(MAX_M)) pointwise(
  .aclk(aclk),.aresetn(aresetn),.s_axis_tdata(cs_data),.s_axis_tvalid(cs_valid),.s_axis_tready(cs_ready),.s_axis_tlast(cs_last),
  .m_axis_tdata(cm_data),.m_axis_tvalid(cm_valid),.m_axis_tready(m_axis_tready && (state==PASS || in_pair) && trailer_ready),.m_axis_tlast(cm_last),
  .busy(core_busy),.done(core_done),.error(core_error));
 fused_depthwise_channel #(.MAX_KERNEL(11)) depthwise(
  .aclk(aclk),.aresetn(aresetn),.cfg_valid(state==CONFIG),.cfg_ready(dc_ready),
  .cfg_times(times),.cfg_valid_times(valid_times),.cfg_kernel(7'd11),.cfg_weights(dw_weights[channel]),
  .cfg_bias(params[31:0]),.cfg_multiplier(params[63:32]),.cfg_shift(params[69:64]),
  .cfg_xzero(params[109:102]),.cfg_yzero(params[77:70]),
  .s_data(s_axis_tdata),.s_valid(state==CHANNEL && s_axis_tvalid),.s_ready(ds_ready),
  .m_data(dm_data),.m_valid(dm_valid),.m_ready(cs_ready && in_pair),.m_last(dm_last),.error(dw_error),.done(dw_done));
 always @(posedge aclk)begin
  if(!aresetn)begin
   state<=HEADER;dw_cache<=0;local_error<=0;cached_channels<=0;channels<=0;outputs<=0;
   dw_tag<=0;tag<=0;status<=0;times<=0;valid_times<=0;channel<=0;received_tiles<=0;
   pair_cycles<=0;cycles_snapshot<=0;done<=0;
  end else begin
   done<=0;
   if(state==META || in_pair)pair_cycles<=pair_cycles+1;
   // Snapshot once the core presents its final beat, so stalls cannot change it.
   if(in_pair && cm_valid && cm_last && cycles_snapshot==0)cycles_snapshot<=pair_cycles+1;
   case(state)
    HEADER:if(accept)begin
     channels<=hk;outputs<=hm;tag<=s_axis_tdata[127:96];status<=0;local_error<=0;channel<=0;
     if(op==7)begin
      dw_cache<=0;
      if(dw_header_valid)state<=DWWEIGHTS;
      else begin status<=1;local_error<=1;state<=s_axis_tlast?ACK:DRAIN;end
     end else if(op==8)begin
      if(pair_header_valid)begin times<=ht;pair_cycles<=0;cycles_snapshot<=0;state<=META;end
      else begin status<=3;local_error<=1;state<=s_axis_tlast?ACK:DRAIN;end
     end else begin
      // Any pointwise weight load/invalidation invalidates the paired DW cache.
      if(op==1 || op==3 || op==4)dw_cache<=0;
      state<=PASS;
     end
    end
    PASS:if(core_done)begin state<=HEADER;done<=1;end
    DWWEIGHTS:if(accept)begin
     dw_weights[channel]<=s_axis_tdata[87:0];
     if(s_axis_tdata[127:88]!=0 || s_axis_tlast)begin status<=2;local_error<=1;state<=s_axis_tlast?ACK:DRAIN;end
     else if(channel==channels-1)begin channel<=0;state<=DWPARAMS;end
     else channel<=channel+1;
    end
    DWPARAMS:if(accept)begin
     dw_params[channel]<={s_axis_tdata[103:96],24'b0,s_axis_tdata[79:72],s_axis_tdata[69:64],s_axis_tdata[63:0]};
     if(s_axis_tdata[127:104]!=0 || s_axis_tdata[95:80]!=0 || s_axis_tdata[71:70]!=0 ||
        s_axis_tdata[63] || s_axis_tdata[69:64]==0 || s_axis_tdata[69:64]==63 ||
        s_axis_tlast!=(channel==channels-1))begin
      status<=2;local_error<=1;state<=s_axis_tlast?ACK:DRAIN;
     end else if(channel==channels-1)begin cached_channels<=channels;dw_tag<=tag;dw_cache<=1;state<=ACK;end
     else channel<=channel+1;
    end
    ACK:if(m_axis_tready)begin state<=HEADER;done<=1;end
    DRAIN:if(accept && s_axis_tlast)state<=ACK;
    META:if(accept)begin
     if(s_axis_tdata[127:13]!=0 || s_axis_tdata[12:0]>times || s_axis_tlast)begin
      local_error<=1;dw_cache<=0;status<=1;state<=s_axis_tlast?ACK:DRAIN;
     end else begin valid_times<=s_axis_tdata[12:0];received_tiles<=0;state<=COREHEADER;end
    end
    COREHEADER:if(cs_ready)state<=CONFIG;
    CONFIG:if(dc_ready)begin received_tiles<=0;state<=CHANNEL;end
    CHANNEL:begin
     if(accept)begin
      if(s_axis_tlast!=(channel==channels-1 && received_tiles==((times+15)>>4)-1))begin local_error<=1;dw_cache<=0;end
      received_tiles<=received_tiles+1;
     end
     if(dw_done)begin
      if(dw_error)begin local_error<=1;dw_cache<=0;end
      if(channel==channels-1)state<=WAITCORE;
      else begin channel<=channel+1;state<=CONFIG;end
     end
    end
    WAITCORE:if(core_done)begin state<=HEADER;done<=1;end
    default:begin state<=HEADER;local_error<=1;dw_cache<=0;end
   endcase
  end
 end
endmodule
