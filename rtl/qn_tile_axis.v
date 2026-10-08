`timescale 1ns/1ps
// AXI-stream pointwise INT8 tile: X[K,16] times W[K,16] -> INT32 Y[16,16].
// Packet: QNT1 header, K input rows, K weight rows. 16 signed bytes per row.
// Header [31:0]=31544e51, [63:32]=K (1..MAX_K), [127:64]=0.
// TLAST occurs only on the last weight row. Output is 64 128-bit beats,
// time-major, four signed INT32 output channels per beat, TLAST on beat63.
// Host pads tails and crops unused time/output lanes. No bias or scaling here.
// Malformed packets drain through TLAST and produce a zero tile with error=1.
module qn_tile_axis #(
    parameter MAX_K = 1024
) (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF S_AXIS:M_AXIS, ASSOCIATED_RESET aresetn" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *) input wire aclk,
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *) input wire aresetn,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TDATA" *)
    input wire [127:0] s_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TVALID" *)
    input wire s_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TREADY" *)
    output wire s_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TLAST" *)
    input wire s_axis_tlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TDATA" *)
    output wire [127:0] m_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TVALID" *)
    output wire m_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TREADY" *)
    input wire m_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TLAST" *)
    output wire m_axis_tlast,
    output wire busy,
    output reg done,
    output reg error
);
    localparam INDEX_WIDTH = MAX_K > 1 ? $clog2(MAX_K) : 1;
    localparam HEADER=0, INPUTS=1, WEIGHTS=2, COMPUTE=3, DRAIN=4, OUTPUTS=5;
    reg [2:0] state;
    reg [INDEX_WIDTH:0] length, issued;
    reg [INDEX_WIDTH-1:0] load_index;
    reg [5:0] output_beat;
    wire [127:0] input_row, weight_row;
    reg read_valid, read_last, product_valid, product_last;
    wire signed [31:0] accumulator [0:255];
    wire accept = s_axis_tvalid && s_axis_tready;
    wire issue = state == COMPUTE && issued < length;
    wire [7:0] base = {output_beat, 2'b00};
    assign s_axis_tready = aresetn && (state == HEADER || state == INPUTS ||
                                     state == WEIGHTS || state == DRAIN);
    assign m_axis_tvalid = aresetn && state == OUTPUTS;
    assign m_axis_tlast = output_beat == 63;
    assign m_axis_tdata = {accumulator[base+3], accumulator[base+2],
                          accumulator[base+1], accumulator[base]};
    assign busy = state != HEADER;

    // Explicit block RAM, one-cycle read latency; packet supplies all used rows.
    genvar bank, t, o;
    generate for (bank=0; bank<2; bank=bank+1) begin: memories
        wire write_enable = accept && (bank == 0 ? state == INPUTS : state == WEIGHTS);
        wire [127:0] row;
        xpm_memory_sdpram #(
            .MEMORY_SIZE(MAX_K*128), .MEMORY_PRIMITIVE("block"),
            .CLOCKING_MODE("common_clock"), .ECC_MODE("no_ecc"),
            .USE_MEM_INIT(0), .WRITE_DATA_WIDTH_A(128), .BYTE_WRITE_WIDTH_A(128),
            .ADDR_WIDTH_A(INDEX_WIDTH), .READ_DATA_WIDTH_B(128),
            .ADDR_WIDTH_B(INDEX_WIDTH), .READ_LATENCY_B(1),
            .WRITE_MODE_B("read_first"), .SIM_ASSERT_CHK(1)
        ) memory (
            .clka(aclk), .clkb(aclk), .sleep(1'b0),
            .ena(write_enable), .wea(write_enable), .addra(load_index), .dina(s_axis_tdata),
            .injectsbiterra(1'b0), .injectdbiterra(1'b0), .rstb(1'b0),
            .enb(issue), .regceb(1'b1), .addrb(issued[INDEX_WIDTH-1:0]),
            .doutb(row), .sbiterrb(), .dbiterrb()
        );
        if (bank == 0) assign input_row = row;
        else assign weight_row = row;
    end endgenerate

    // One native DSP per lane, MREG then PREG; enable each pipeline stage
    // only for a valid row/product. P holds the signed 48-bit running sum.
    generate for (t=0; t<16; t=t+1) begin: times
        for (o=0; o<16; o=o+1) begin: outputs
            wire [47:0] sum;
            assign accumulator[t*16+o] = sum[31:0];
            DSP48E2 #(
                .AREG(0), .ACASCREG(0), .BREG(0), .BCASCREG(0),
                .ADREG(0), .DREG(0), .CREG(0), .MREG(1), .PREG(1),
                .ALUMODEREG(0), .OPMODEREG(0), .INMODEREG(0),
                .CARRYINREG(0), .CARRYINSELREG(0), .USE_MULT("MULTIPLY")
            ) mac (
                .CLK(aclk), .A({{22{input_row[t*8+7]}}, input_row[t*8 +: 8]}),
                .B({{10{weight_row[o*8+7]}}, weight_row[o*8 +: 8]}),
                .C(48'b0), .D(27'b0), .ACIN(30'b0), .BCIN(18'b0), .PCIN(48'b0),
                .ALUMODE(4'b0), .INMODE(5'b0), .OPMODE(9'b000100101),
                .CARRYIN(1'b0), .CARRYINSEL(3'b0), .CARRYCASCIN(1'b0), .MULTSIGNIN(1'b0),
                .CEA1(1'b0), .CEA2(1'b0), .CEB1(1'b0), .CEB2(1'b0),
                .CEAD(1'b0), .CEC(1'b0), .CED(1'b0), .CEALUMODE(1'b0),
                .CECTRL(1'b0), .CEINMODE(1'b0), .CECARRYIN(1'b0),
                .CEM(read_valid), .CEP(state == COMPUTE && product_valid),
                .RSTA(1'b0), .RSTB(1'b0), .RSTC(1'b0), .RSTD(1'b0),
                .RSTALUMODE(1'b0), .RSTCTRL(1'b0), .RSTINMODE(1'b0), .RSTALLCARRYIN(1'b0),
                .RSTM(!aresetn), .RSTP(!aresetn || (accept && state == HEADER)),
                .P(sum), .ACOUT(), .BCOUT(), .PCOUT(), .CARRYCASCOUT(), .CARRYOUT(),
                .MULTSIGNOUT(), .OVERFLOW(), .UNDERFLOW(), .PATTERNDETECT(), .PATTERNBDETECT(), .XOROUT()
            );
        end
    end endgenerate

    always @(posedge aclk) begin
        if (!aresetn) begin
            state <= HEADER;
            length <= 0;
            load_index <= 0;
            issued <= 0;
            output_beat <= 0;
            read_valid <= 0;
            read_last <= 0;
            product_valid <= 0;
            product_last <= 0;
            done <= 0;
            error <= 0;
        end else begin
            done <= 0;
            read_valid <= issue;
            read_last <= issue && issued == length-1;
            product_valid <= read_valid;
            product_last <= read_last;
            case (state)
                HEADER: if (accept) begin
                    error <= 0;
                    output_beat <= 0;
                    load_index <= 0;
                    if (s_axis_tlast) begin
                        error <= 1;
                        state <= OUTPUTS;
                    end else if (s_axis_tdata[31:0] != 32'h31544e51 ||
                                 s_axis_tdata[63:32] == 0 ||
                                 s_axis_tdata[63:32] > MAX_K ||
                                 s_axis_tdata[127:64] != 0) begin
                        error <= 1;
                        state <= DRAIN;
                    end else begin
                        length <= s_axis_tdata[63:32];
                        state <= INPUTS;
                    end
                end
                INPUTS: if (accept) begin
                    if (s_axis_tlast) begin
                        error <= 1;
                        state <= OUTPUTS;
                    end else if (load_index == length-1) begin
                        load_index <= 0;
                        state <= WEIGHTS;
                    end else load_index <= load_index+1;
                end
                WEIGHTS: if (accept) begin
                    if (load_index == length-1) begin
                        if (!s_axis_tlast) begin
                            error <= 1;
                            state <= DRAIN;
                        end else begin
                            issued <= 0;
                            state <= COMPUTE;
                        end
                    end else if (s_axis_tlast) begin
                        error <= 1;
                        state <= OUTPUTS;
                    end else load_index <= load_index+1;
                end
                COMPUTE: begin
                    if (issue) issued <= issued+1;
                    if (product_valid && product_last) begin
                        output_beat <= 0;
                        state <= OUTPUTS;
                    end
                end
                DRAIN: if (accept && s_axis_tlast) begin
                    output_beat <= 0;
                    state <= OUTPUTS;
                end
                OUTPUTS: if (m_axis_tvalid && m_axis_tready) begin
                    if (output_beat == 63) begin
                        state <= HEADER;
                        done <= 1;
                    end else output_beat <= output_beat+1;
                end
                default: state <= HEADER;
            endcase
        end
    end
endmodule
