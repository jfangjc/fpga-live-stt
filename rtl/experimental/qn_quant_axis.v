`timescale 1ns/1ps
// QNC2 layer cache. LOAD weights once; RUN reuses K input rows over all
// output groups. Signed INT8 products, unscaled INT32 results, 16 time lanes.
// Protocol is documented in software/CACHED_LAYER_PROTOCOL.md.
// QNT1 packets remain supported and invalidate the layer cache.
module qn_cached_axis #(
    parameter MAX_K = 1024,
    parameter MAX_M = 1024
) (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF S_AXIS:M_AXIS, ASSOCIATED_RESET aresetn" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *) input wire aclk,
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *) input wire aresetn,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TDATA" *) input wire [127:0] s_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TVALID" *) input wire s_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TREADY" *) output wire s_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TLAST" *) input wire s_axis_tlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TDATA" *) output wire [127:0] m_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TVALID" *) output wire m_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TREADY" *) input wire m_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TLAST" *) output wire m_axis_tlast,
    output wire busy, output reg done, output reg error
);
    localparam KW = MAX_K > 1 ? $clog2(MAX_K) : 1;
    localparam MAX_GROUPS = (MAX_M+15)/16;
    localparam GW = MAX_GROUPS > 1 ? $clog2(MAX_GROUPS) : 1;
    localparam HEADER=0, INPUTS=1, WEIGHTS=2, COMPUTE=3,
               DRAIN=4, OUTPUTS=5, RESPONSE=6, CLEAR=7, PARAMS=8, QUANT=9;
    localparam [31:0] QNT1=32'h31544e51, QNC2=32'h32434e51, QNR2=32'h32524e51;
    reg [3:0] state;
    reg legacy, response_payload, cache_valid;
    reg cache_quant,quant_response;
    reg [3:0] param_lane;
    reg [4:0] quant_feed;
    reg signed [31:0] q_bias[0:MAX_GROUPS-1][0:15];
    reg [31:0] q_multiplier[0:MAX_GROUPS-1][0:15];
    reg [5:0] q_shift[0:MAX_GROUPS-1][0:15];
    reg [7:0] q_zero[0:MAX_GROUPS-1][0:15];
    reg [7:0] opcode;
    reg [15:0] request_k, request_m, cache_k, cache_m;
    reg [31:0] tag, cache_tag, status;
    reg [KW:0] length, issued;
    reg [KW-1:0] load_index;
    reg [GW-1:0] load_group, compute_group;
    reg [GW:0] groups;
    reg [5:0] output_beat;
    reg read_stage, read_stage_last, read_valid, read_last;
    reg product_valid, product_last;
    wire [127:0] input_row, weight_row;
    wire signed [31:0] accumulator [0:255];
    wire accept=s_axis_tvalid && s_axis_tready;
    wire issue=state==COMPUTE && issued<length;
    wire [15:0] header_m=s_axis_tdata[63:48];
    wire [15:0] header_k=s_axis_tdata[79:64];
    wire valid_dims=header_k>0 && header_k<=MAX_K && header_m>0 && header_m<=MAX_M;
    wire [7:0] base={output_beat,2'b00};
    wire last_group=compute_group==groups-1;
    wire [KW+GW-1:0] weight_write_address={load_group,load_index};
    wire [KW+GW-1:0] weight_read_address={compute_group,issued[KW-1:0]};
    wire input_write=accept && state==INPUTS;
    wire weight_write=accept && state==WEIGHTS;
    wire [511:0] quant_acc,quant_bias,quant_mult;
    wire [95:0] quant_shift;
    wire [127:0] quant_zero,quant_data;
    wire quant_ready,quant_valid,quant_error;
    genvar q;
    generate for(q=0;q<16;q=q+1) begin: quant_lanes
        assign quant_acc[q*32+:32]=accumulator[{quant_feed[3:0],4'b0}+q];
        assign quant_bias[q*32+:32]=q_bias[compute_group][q];
        assign quant_mult[q*32+:32]=q_multiplier[compute_group][q];
        assign quant_shift[q*6+:6]=q_shift[compute_group][q];
        assign quant_zero[q*8+:8]=q_zero[compute_group][q];
    end endgenerate
    fused_affine_quant #(.LANES(16)) requant(
        .aclk(aclk),.aresetn(aresetn && state!=HEADER && !error),.s_acc(quant_acc),.s_bias(quant_bias),
        .s_multiplier(quant_mult),.s_shift(quant_shift),.s_zero(quant_zero),
        .s_valid(state==QUANT && quant_feed<16 && !error),.s_ready(quant_ready),
        .m_data(quant_data),.m_valid(quant_valid),
        .m_ready(state==QUANT && m_axis_tready && !error),.m_error(quant_error));
    assign s_axis_tready=aresetn && (state==HEADER || state==INPUTS || state==WEIGHTS || state==DRAIN || state==PARAMS);
    assign m_axis_tvalid=aresetn && (state==RESPONSE || state==OUTPUTS || (state==QUANT && (error || quant_valid)));
    assign m_axis_tlast=state==RESPONSE ? !response_payload : output_beat==(quant_response ? 15 : 63) && last_group;
    assign m_axis_tdata=state==RESPONSE ? {tag,request_m,request_k,status,QNR2} :
        error ? 128'b0 : state==QUANT ? quant_data :
        {accumulator[base+3],accumulator[base+2],accumulator[base+1],accumulator[base]};
    assign busy=state!=HEADER;

    // Fixed power-of-two K stride separates output groups. Only committed
    // dimensions may be read; RAM contents themselves are not reset.
    xpm_memory_sdpram #(
        .MEMORY_SIZE((1<<KW)*128), .MEMORY_PRIMITIVE("block"),
        .CLOCKING_MODE("common_clock"), .ECC_MODE("no_ecc"), .USE_MEM_INIT(0),
        .WRITE_DATA_WIDTH_A(128), .BYTE_WRITE_WIDTH_A(128), .ADDR_WIDTH_A(KW),
        .READ_DATA_WIDTH_B(128), .ADDR_WIDTH_B(KW), .READ_LATENCY_B(2),
        .WRITE_MODE_B("read_first"), .SIM_ASSERT_CHK(1)
    ) inputs_memory (
        .clka(aclk), .clkb(aclk), .sleep(1'b0), .ena(input_write), .wea(input_write),
        .addra(load_index), .dina(s_axis_tdata), .injectsbiterra(1'b0), .injectdbiterra(1'b0),
        .rstb(1'b0), .enb(issue), .regceb(1'b1), .addrb(issued[KW-1:0]),
        .doutb(input_row), .sbiterrb(), .dbiterrb()
    );
    xpm_memory_sdpram #(
        .MEMORY_SIZE((1<<(KW+GW))*128), .MEMORY_PRIMITIVE("ultra"),
        .CLOCKING_MODE("common_clock"), .ECC_MODE("no_ecc"), .USE_MEM_INIT(0),
        .WRITE_DATA_WIDTH_A(128), .BYTE_WRITE_WIDTH_A(128), .ADDR_WIDTH_A(KW+GW),
        .READ_DATA_WIDTH_B(128), .ADDR_WIDTH_B(KW+GW), .READ_LATENCY_B(2),
        .WRITE_MODE_B("read_first"), .SIM_ASSERT_CHK(1)
    ) weights_memory (
        .clka(aclk), .clkb(aclk), .sleep(1'b0), .ena(weight_write), .wea(weight_write),
        .addra(weight_write_address), .dina(s_axis_tdata), .injectsbiterra(1'b0), .injectdbiterra(1'b0),
        .rstb(1'b0), .enb(issue), .regceb(1'b1), .addrb(weight_read_address),
        .doutb(weight_row), .sbiterrb(), .dbiterrb()
    );
    genvar t,o;
    generate for(t=0;t<16;t=t+1) begin: times
        for(o=0;o<16;o=o+1) begin: outputs
            wire [47:0] sum;
            assign accumulator[t*16+o]=sum[31:0];
            DSP48E2 #(
                .AREG(0), .ACASCREG(0), .BREG(0), .BCASCREG(0), .ADREG(0), .DREG(0),
                .CREG(0), .MREG(1), .PREG(1), .ALUMODEREG(0), .OPMODEREG(0),
                .INMODEREG(0), .CARRYINREG(0), .CARRYINSELREG(0), .USE_MULT("MULTIPLY")
            ) mac (
                .CLK(aclk), .A({{22{input_row[t*8+7]}},input_row[t*8+:8]}),
                .B({{10{weight_row[o*8+7]}},weight_row[o*8+:8]}),
                .C(48'b0), .D(27'b0), .ACIN(30'b0), .BCIN(18'b0), .PCIN(48'b0),
                .ALUMODE(4'b0), .INMODE(5'b0), .OPMODE(9'b000100101),
                .CARRYIN(1'b0), .CARRYINSEL(3'b0), .CARRYCASCIN(1'b0), .MULTSIGNIN(1'b0),
                .CEA1(1'b0), .CEA2(1'b0), .CEB1(1'b0), .CEB2(1'b0), .CEAD(1'b0),
                .CEC(1'b0), .CED(1'b0), .CEALUMODE(1'b0), .CECTRL(1'b0),
                .CEINMODE(1'b0), .CECARRYIN(1'b0), .CEM(read_valid),
                .CEP(state==COMPUTE && product_valid), .RSTA(1'b0), .RSTB(1'b0),
                .RSTC(1'b0), .RSTD(1'b0), .RSTALUMODE(1'b0), .RSTCTRL(1'b0),
                .RSTINMODE(1'b0), .RSTALLCARRYIN(1'b0), .RSTM(!aresetn),
                .RSTP(!aresetn || state==CLEAR || (accept && state==HEADER)),
                .P(sum), .ACOUT(), .BCOUT(), .PCOUT(), .CARRYCASCOUT(), .CARRYOUT(),
                .MULTSIGNOUT(), .OVERFLOW(), .UNDERFLOW(), .PATTERNDETECT(),
                .PATTERNBDETECT(), .XOROUT()
            );
        end
    end endgenerate

    always @(posedge aclk) begin
        if(!aresetn) begin
            state<=HEADER; legacy<=0; response_payload<=0; cache_valid<=0;
            opcode<=0; request_k<=0; request_m<=0; cache_k<=0; cache_m<=0;
            tag<=0; cache_tag<=0; status<=0; length<=0; issued<=0;
            load_index<=0; load_group<=0; compute_group<=0; groups<=1; output_beat<=0;
            read_stage<=0; read_stage_last<=0; read_valid<=0; read_last<=0;
            product_valid<=0; product_last<=0; done<=0; error<=0;
            cache_quant<=0;quant_response<=0;param_lane<=0;quant_feed<=0;
        end else begin
            done<=0;
            read_stage<=issue; read_stage_last<=issue && issued==length-1;
            read_valid<=read_stage; read_last<=read_stage_last;
            product_valid<=read_valid; product_last<=read_last;
            case(state)
                HEADER: if(accept) begin
                    error<=0; status<=0; output_beat<=0; load_index<=0;
                    load_group<=0; compute_group<=0; issued<=0; groups<=1;
                    response_payload<=0; legacy<=s_axis_tdata[31:0]==QNT1;
                    quant_response<=s_axis_tdata[31:0]==QNC2 && s_axis_tdata[39:32]==5;
                    param_lane<=0;quant_feed<=0;
                    opcode<=s_axis_tdata[39:32];
                    request_k<=header_k; request_m<=header_m; tag<=s_axis_tdata[127:96];
                    if(s_axis_tdata[31:0]==QNT1) begin
                        cache_valid<=0; response_payload<=1;
                        if(s_axis_tdata[63:32]==0 || s_axis_tdata[63:32]>MAX_K ||
                           s_axis_tdata[127:64]!=0 || s_axis_tlast) begin
                            error<=1; status<=1; state<=s_axis_tlast ? OUTPUTS : DRAIN;
                        end else begin length<=s_axis_tdata[63:32]; state<=INPUTS; end
                    end else if(s_axis_tdata[31:0]!=QNC2 || s_axis_tdata[47:40]!=0 ||
                                s_axis_tdata[95:80]!=0) begin
                        cache_valid<=0; error<=1; status<=1;
                        state<=s_axis_tlast ? RESPONSE : DRAIN;
                    end else if(s_axis_tdata[39:32]==3 && header_k==0 && header_m==0 &&
                                s_axis_tdata[127:96]==0) begin
                        cache_valid<=0;
                        if(s_axis_tlast) state<=RESPONSE;
                        else begin error<=1; status<=2; state<=DRAIN; end
                    end else if(!valid_dims || s_axis_tdata[127:96]==0 ||
                                (s_axis_tdata[39:32]!=1 && s_axis_tdata[39:32]!=2 &&
                                 s_axis_tdata[39:32]!=4 && s_axis_tdata[39:32]!=5)) begin
                        cache_valid<=0; error<=1; status<=1;
                        state<=s_axis_tlast ? RESPONSE : DRAIN;
                    end else begin
                        groups<=(header_m+15)>>4; length<=header_k;
                        response_payload<=s_axis_tdata[39:32]==2 || s_axis_tdata[39:32]==5;
                        if(s_axis_tlast) begin
                            cache_valid<=0; error<=1; status<=2; state<=RESPONSE;
                        end else if(s_axis_tdata[39:32]==1 || s_axis_tdata[39:32]==4) begin
                            cache_valid<=0; state<=WEIGHTS;
                        end else if(!cache_valid || cache_k!=header_k || cache_m!=header_m ||
                                    cache_tag!=s_axis_tdata[127:96] ||
                                    cache_quant!=(s_axis_tdata[39:32]==5)) begin
                            cache_valid<=0; error<=1; status<=3; state<=DRAIN;
                        end else state<=INPUTS;
                    end
                end
                INPUTS: if(accept) begin
                    if(legacy) begin
                        if(s_axis_tlast) begin error<=1; status<=2; state<=OUTPUTS; end
                        else if(load_index==length-1) begin load_index<=0; state<=WEIGHTS; end
                        else load_index<=load_index+1;
                    end else if(load_index==length-1) begin
                        if(s_axis_tlast) begin issued<=0; state<=CLEAR; end
                        else begin cache_valid<=0; error<=1; status<=2; state<=DRAIN; end
                    end else if(s_axis_tlast) begin
                        cache_valid<=0; error<=1; status<=2; state<=RESPONSE;
                    end else load_index<=load_index+1;
                end
                WEIGHTS: if(accept) begin
                    if(load_index==length-1 && load_group==groups-1) begin
                        if(opcode==4 && !s_axis_tlast) begin
                            load_group<=0;param_lane<=0;state<=PARAMS;
                        end else if(opcode==4) begin
                            cache_valid<=0;error<=1;status<=2;state<=RESPONSE;
                        end else if(!s_axis_tlast) begin cache_valid<=0; error<=1; status<=2; state<=DRAIN; end
                        else if(legacy) begin issued<=0; state<=CLEAR; end
                        else begin
                            cache_valid<=1; cache_k<=request_k; cache_m<=request_m; cache_tag<=tag;
                            cache_quant<=0;
                            state<=RESPONSE;
                        end
                    end else if(s_axis_tlast) begin
                        cache_valid<=0; error<=1; status<=2; state<=legacy ? OUTPUTS : RESPONSE;
                    end else if(load_index==length-1) begin
                        load_index<=0; load_group<=load_group+1;
                    end else load_index<=load_index+1;
                end
                PARAMS: if(accept) begin
                    q_bias[load_group][param_lane]<=s_axis_tdata[31:0];
                    q_multiplier[load_group][param_lane]<=s_axis_tdata[63:32];
                    q_shift[load_group][param_lane]<=s_axis_tdata[69:64];
                    q_zero[load_group][param_lane]<=s_axis_tdata[79:72];
                    if(s_axis_tdata[127:80]!=0 || s_axis_tdata[71:70]!=0 ||
                       s_axis_tdata[63] || s_axis_tdata[69:64]==0 || s_axis_tdata[69:64]==63) begin
                        cache_valid<=0;error<=1;status<=1;state<=s_axis_tlast ? RESPONSE : DRAIN;
                    end else if(param_lane==15 && load_group==groups-1) begin
                        if(!s_axis_tlast) begin cache_valid<=0;error<=1;status<=2;state<=DRAIN;end
                        else begin
                            cache_valid<=1;cache_quant<=1;cache_k<=request_k;cache_m<=request_m;cache_tag<=tag;
                            state<=RESPONSE;
                        end
                    end else if(s_axis_tlast) begin
                        cache_valid<=0;error<=1;status<=2;state<=RESPONSE;
                    end else if(param_lane==15) begin param_lane<=0;load_group<=load_group+1;end
                    else param_lane<=param_lane+1;
                end
                CLEAR: begin issued<=0; state<=COMPUTE; end
                COMPUTE: begin
                    if(issue) issued<=issued+1;
                    if(product_valid && product_last) begin
                        output_beat<=0;
                        quant_feed<=0;
                        state<=legacy ? OUTPUTS : compute_group!=0 ? (quant_response ? QUANT : OUTPUTS) : RESPONSE;
                    end
                end
                DRAIN: if(accept && s_axis_tlast) begin
                    output_beat<=0; state<=legacy ? OUTPUTS : RESPONSE;
                end
                RESPONSE: if(m_axis_tvalid && m_axis_tready) begin
                    if(response_payload) begin output_beat<=0;quant_feed<=0;state<=quant_response ? QUANT : OUTPUTS; end
                    else begin state<=HEADER; done<=1; end
                end
                QUANT: begin
                    if(quant_feed<16 && quant_ready && !error)quant_feed<=quant_feed+1;
                    // A late arithmetic error also raises GPIO error, so the
                    // driver rejects the command even after its header was sent.
                    if(quant_valid && quant_error && m_axis_tready) begin error<=1;cache_valid<=0;end
                    if(m_axis_tvalid && m_axis_tready) begin
                        if(output_beat==15) begin
                            if(last_group) begin state<=HEADER;done<=1;end
                            else begin compute_group<=compute_group+1;output_beat<=0;quant_feed<=0;state<=error ? QUANT : CLEAR;end
                        end else output_beat<=output_beat+1;
                    end
                end
                OUTPUTS: if(m_axis_tvalid && m_axis_tready) begin
                    if(output_beat==63) begin
                        if(last_group) begin state<=HEADER; done<=1; end
                        else begin
                            compute_group<=compute_group+1; output_beat<=0;
                            state<=error ? OUTPUTS : CLEAR;
                        end
                    end else output_beat<=output_beat+1;
                end
                default: begin state<=HEADER; cache_valid<=0; error<=1; end
            endcase
        end
    end
endmodule
