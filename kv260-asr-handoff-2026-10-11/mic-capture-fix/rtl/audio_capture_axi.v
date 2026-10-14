`timescale 1ns/1ps
// Audio capture block: drop-in replacement for voice_axi (which also carried the legacy
// qn_mac bring-up tile that sits on the routed critical path).
//
//   aud_clk (24.576 MHz)                         | s_axi_aclk (100 MHz)
//   i2s_rx_stereo -> decim3_fir -> dc_gain x2 ---+--> toggle CDC -> ring buffer (BRAM) -> AXI-Lite
//   48 kHz stereo    16 kHz, 20-bit   16-bit     |    seq-checked    2^RING_AW frames
//
// AXI-Lite map (byte offsets; 64 KB window by default, same size as voice_axi):
//   0x00 ID         RO  0x41554431 "AUD1"
//   0x04 CTRL       RW  [0] enable (0 holds the audio pipeline in reset, BCLK stopped)
//                       [1] irq_en  [11:8] gain_shift (0..8, change only while disabled)
//                       [31] write 1: clear counters, pointers and sticky flags (self-clearing)
//   0x08 STATUS     RO  [0] enable [1] overrun [2] cdc_drop [3] saturated [4] irq [5] fir_overlap
//   0x0C DEPTH      RO  ring depth in frames
//   0x10 WRITE_CNT  RO  frames written (free-running); ring index = WRITE_CNT mod DEPTH
//   0x14 READ_CNT   RW  frames consumed by software (absolute count, software-owned)
//   0x18 FILL       RO  WRITE_CNT - READ_CNT
//   0x1C OVERRUNS   RO  frames written while FILL >= DEPTH (unread data overwritten)
//   0x20 SAT_CNT    RO  saturated samples (both channels)
//   0x24 CDC_DROPS  RO  sequence gaps across the clock crossing (expected 0)
//   0x28 IRQ_THRESH RW  IRQ when FILL >= IRQ_THRESH (0 disables), default 4000 (0.25 s)
//   0x2C PARAMS     RO  {taps=96, decim=3, dc_k=9, version=1}
//   0x8000+4*i RING RO  frame i = {right[15:0], left[15:0]}, 16 kHz
// IRQ (level): irq_en && ((IRQ_THRESH != 0 && FILL >= IRQ_THRESH) || overrun).
module audio_capture_axi #(
    parameter ADDR_WIDTH = 16,
    parameter RING_AW = 13              // 8192 frames = 0.512 s at 16 kHz (8 BRAM36)
) (
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME s_axi_aclk, ASSOCIATED_BUSIF S_AXI, ASSOCIATED_RESET s_axi_aresetn, FREQ_HZ 99999001" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 s_axi_aclk CLK" *) input wire s_axi_aclk,
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME s_axi_aresetn, POLARITY ACTIVE_LOW" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 s_axi_aresetn RST" *) input wire s_axi_aresetn,
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME S_AXI, PROTOCOL AXI4LITE, DATA_WIDTH 32, READ_WRITE_MODE READ_WRITE, FREQ_HZ 99999001, HAS_BURST 0, HAS_LOCK 0, HAS_CACHE 0, HAS_QOS 0, HAS_REGION 0, SUPPORTS_NARROW_BURST 0, NUM_READ_OUTSTANDING 1, NUM_WRITE_OUTSTANDING 1" *)
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWADDR" *) input wire [ADDR_WIDTH-1:0] s_axi_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWPROT" *) input wire [2:0] s_axi_awprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *) input wire s_axi_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *) output wire s_axi_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WDATA" *) input wire [31:0] s_axi_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *) input wire [3:0] s_axi_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WVALID" *) input wire s_axi_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WREADY" *) output wire s_axi_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BRESP" *) output reg [1:0] s_axi_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BVALID" *) output reg s_axi_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BREADY" *) input wire s_axi_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *) input wire [ADDR_WIDTH-1:0] s_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARPROT" *) input wire [2:0] s_axi_arprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *) input wire s_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *) output wire s_axi_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RDATA" *) output wire [31:0] s_axi_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RRESP" *) output reg [1:0] s_axi_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RVALID" *) output reg s_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RREADY" *) input wire s_axi_rready,
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME aud_clk, FREQ_HZ 24576000" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aud_clk CLK" *) input wire aud_clk,
    input wire aud_locked,              // clk_wiz locked; audio domain held in reset until set
    output wire mic_bclk,
    output wire mic_ws,
    input  wire mic_data,
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME irq, SENSITIVITY LEVEL_HIGH" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:interrupt:1.0 irq INTERRUPT" *) output wire irq
);
    localparam [31:0] DEPTH = 32'd1 << RING_AW;
    generate
        if (RING_AW + 3 != ADDR_WIDTH) begin : g_bad_params
            // The ring must fill exactly the upper half of the AXI window.
            PARAMETER_ERROR_RING_AW_MUST_EQUAL_ADDR_WIDTH_MINUS_3 u_param_error ();
        end
    endgenerate

    wire clk = s_axi_aclk;
    wire rst = ~s_axi_aresetn;

    // ------------------------------------------------------------------ AXI-domain state
    reg        ctrl_enable, ctrl_irq_en;
    reg [3:0]  ctrl_gain;
    reg [31:0] irq_threshold, read_count, write_count;
    reg [31:0] overrun_count, sat_count, cdc_drops;
    reg        overrun_sticky, cdc_sticky, sat_sticky;
    reg        aud_run;                 // registered so the audio-domain reset source is glitch-free

    // ------------------------------------------------------------------ audio clock domain
    wire glob_n = s_axi_aresetn & aud_locked;
    wire run_n = aud_run & aud_locked;
    (* ASYNC_REG = "TRUE" *) reg [1:0] aud_glob_sync;
    (* ASYNC_REG = "TRUE" *) reg [1:0] aud_run_sync;
    always @(posedge aud_clk or negedge glob_n)
        if (!glob_n) aud_glob_sync <= 2'b00; else aud_glob_sync <= {aud_glob_sync[0], 1'b1};
    always @(posedge aud_clk or negedge run_n)
        if (!run_n) aud_run_sync <= 2'b00; else aud_run_sync <= {aud_run_sync[0], 1'b1};
    wire aud_rst_glob = ~aud_glob_sync[1];
    wire aud_rst_run = ~aud_run_sync[1];

    // gain_shift is quasi-static: only changed while capture is disabled (pipeline in reset).
    (* ASYNC_REG = "TRUE" *) reg [3:0] gain_meta;
    (* ASYNC_REG = "TRUE" *) reg [3:0] gain_sync;
    always @(posedge aud_clk) begin
        gain_meta <= ctrl_gain;
        gain_sync <= gain_meta;
    end

    wire signed [17:0] rx_l, rx_r;
    wire rx_v;
    wire [31:0] rx_frames;
    i2s_rx_stereo rx (
        .clk(aud_clk), .rst(aud_rst_run), .mic_data(mic_data),
        .mic_bclk(mic_bclk), .mic_ws(mic_ws),
        .left(rx_l), .right(rx_r), .valid(rx_v), .frames(rx_frames));

    wire signed [19:0] fir_l, fir_r;
    wire fir_v, fir_err;
    decim3_fir fir (
        .clk(aud_clk), .rst(aud_rst_run), .in_valid(rx_v), .in_l(rx_l), .in_r(rx_r),
        .out_valid(fir_v), .out_l(fir_l), .out_r(fir_r), .overlap_err(fir_err));

    wire signed [15:0] dc_l, dc_r;
    wire dc_lv, dc_rv, sat_l, sat_r;
    dc_gain dcl (
        .clk(aud_clk), .rst(aud_rst_run), .in_valid(fir_v), .x(fir_l), .gain_shift(gain_sync),
        .out_valid(dc_lv), .y(dc_l), .sat(sat_l));
    dc_gain dcr (
        .clk(aud_clk), .rst(aud_rst_run), .in_valid(fir_v), .x(fir_r), .gain_shift(gain_sync),
        .out_valid(dc_rv), .y(dc_r), .sat(sat_r));

    // CDC source: two-phase toggle handshake. The payload register changes at most once per
    // 1536 aud_clk (62.5 us), far longer than the 3-cycle destination synchroniser, so the
    // destination always samples a stable payload (bounded by set_max_delay in audio_cdc.xdc).
    // A 2-bit sequence number lets the destination count any lost transfer.
    // Reset only by the global reset, so toggling 'enable' cannot create a false edge.
    reg [35:0] pay_src;
    reg        req_toggle;
    reg [1:0]  seq;
    always @(posedge aud_clk) begin
        if (aud_rst_glob) begin
            pay_src <= 36'd0;
            req_toggle <= 1'b0;
            seq <= 2'd0;
        end else if (dc_lv) begin
            pay_src <= {seq, sat_r, sat_l, dc_r, dc_l};
            seq <= seq + 2'd1;
            req_toggle <= ~req_toggle;
        end
    end

    // ------------------------------------------------------------------ CDC destination
    (* ASYNC_REG = "TRUE" *) reg req_meta;
    (* ASYNC_REG = "TRUE" *) reg req_sync;
    reg        req_prev;
    reg [35:0] pay_cap;
    reg        cap_vld;
    (* ASYNC_REG = "TRUE" *) reg fir_err_meta;
    (* ASYNC_REG = "TRUE" *) reg fir_err_sync;
    always @(posedge clk) begin
        if (rst) begin
            req_meta <= 1'b0; req_sync <= 1'b0; req_prev <= 1'b0;
            pay_cap <= 36'd0; cap_vld <= 1'b0;
            fir_err_meta <= 1'b0; fir_err_sync <= 1'b0;
        end else begin
            req_meta <= req_toggle;
            req_sync <= req_meta;
            req_prev <= req_sync;
            cap_vld <= 1'b0;
            if (req_sync != req_prev) begin
                pay_cap <= pay_src;
                cap_vld <= 1'b1;
            end
            fir_err_meta <= fir_err;
            fir_err_sync <= fir_err_meta;
        end
    end

    // ------------------------------------------------------------------ ring buffer
    (* ram_style = "block" *) reg [31:0] ring [0:(1 << RING_AW) - 1];
    reg [31:0] ring_q;
    always @(posedge clk) begin
        if (cap_vld) ring[write_count[RING_AW-1:0]] <= pay_cap[31:0];
    end

    wire [31:0] fill = write_count - read_count;
    reg  [1:0]  exp_seq;
    reg         seq_valid;

    // ------------------------------------------------------------------ AXI-Lite slave
    reg aw_pending, w_pending;
    reg [ADDR_WIDTH-1:0] awaddr;
    reg [31:0] wdata;
    reg [3:0] wstrb;
    assign s_axi_awready = !aw_pending && !s_axi_bvalid;
    assign s_axi_wready = !w_pending && !s_axi_bvalid;
    assign s_axi_arready = !s_axi_rvalid;
    wire write_commit = aw_pending && w_pending && !s_axi_bvalid;
    wire w_in_regs = !awaddr[ADDR_WIDTH-1] && ((awaddr >> 8) == 0) && (awaddr[1:0] == 2'b00);
    wire [5:0] w_idx = awaddr[7:2];
    wire write_ok = w_in_regs && (wstrb == 4'hf) && (w_idx == 6'd1 || w_idx == 6'd5 || w_idx == 6'd10);
    wire soft_clear = write_commit && write_ok && (w_idx == 6'd1) && wdata[31];

    wire ar_fire = s_axi_arvalid && s_axi_arready;
    wire ar_ring = s_axi_araddr[ADDR_WIDTH-1];
    wire ar_regs = !ar_ring && ((s_axi_araddr >> 8) == 0);   // registers live in the first 256 B
    wire ar_aligned = s_axi_araddr[1:0] == 2'b00;
    reg  rd_is_ring;
    reg  [31:0] rdata_reg;
    assign s_axi_rdata = rd_is_ring ? ring_q : rdata_reg;

    wire irq_level = ctrl_irq_en && (((irq_threshold != 32'd0) && (fill >= irq_threshold)) || overrun_sticky);
    assign irq = irq_level;

    always @(posedge clk) begin
        if (ar_fire) ring_q <= ring[s_axi_araddr[RING_AW+1:2]];
    end

    always @(posedge clk) begin
        if (rst) begin
            aw_pending <= 1'b0; w_pending <= 1'b0; awaddr <= {ADDR_WIDTH{1'b0}};
            wdata <= 32'd0; wstrb <= 4'd0;
            s_axi_bvalid <= 1'b0; s_axi_bresp <= 2'b00;
            s_axi_rvalid <= 1'b0; s_axi_rresp <= 2'b00; rdata_reg <= 32'd0; rd_is_ring <= 1'b0;
            ctrl_enable <= 1'b0; ctrl_irq_en <= 1'b0; ctrl_gain <= 4'd4;
            irq_threshold <= 32'd4000; read_count <= 32'd0; write_count <= 32'd0;
            overrun_count <= 32'd0; sat_count <= 32'd0; cdc_drops <= 32'd0;
            overrun_sticky <= 1'b0; cdc_sticky <= 1'b0; sat_sticky <= 1'b0;
            exp_seq <= 2'd0; seq_valid <= 1'b0;
            aud_run <= 1'b0;
        end else begin
            aud_run <= ctrl_enable;

            // write channel
            if (s_axi_awvalid && s_axi_awready) begin awaddr <= s_axi_awaddr; aw_pending <= 1'b1; end
            if (s_axi_wvalid && s_axi_wready) begin wdata <= s_axi_wdata; wstrb <= s_axi_wstrb; w_pending <= 1'b1; end
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (write_commit) begin
                aw_pending <= 1'b0; w_pending <= 1'b0;
                s_axi_bvalid <= 1'b1;
                s_axi_bresp <= write_ok ? 2'b00 : 2'b10;
                if (write_ok) begin
                    case (w_idx)
                        6'd1: begin
                            ctrl_enable <= wdata[0];
                            ctrl_irq_en <= wdata[1];
                            ctrl_gain <= wdata[11:8];
                        end
                        6'd5: read_count <= wdata;
                        6'd10: irq_threshold <= wdata;
                        default: ;
                    endcase
                end
            end

            // read channel
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (ar_fire) begin
                s_axi_rvalid <= 1'b1;
                rd_is_ring <= ar_ring && ar_aligned;
                s_axi_rresp <= 2'b00;
                rdata_reg <= 32'd0;
                if (!ar_aligned || (!ar_ring && !ar_regs)) s_axi_rresp <= 2'b10;
                else if (!ar_ring) begin
                    case (s_axi_araddr[7:2])
                        6'd0:  rdata_reg <= 32'h41554431;
                        6'd1:  rdata_reg <= {20'd0, ctrl_gain, 6'd0, ctrl_irq_en, ctrl_enable};
                        6'd2:  rdata_reg <= {26'd0, fir_err_sync, irq_level, sat_sticky, cdc_sticky, overrun_sticky, ctrl_enable};
                        6'd3:  rdata_reg <= DEPTH;
                        6'd4:  rdata_reg <= write_count;
                        6'd5:  rdata_reg <= read_count;
                        6'd6:  rdata_reg <= fill;
                        6'd7:  rdata_reg <= overrun_count;
                        6'd8:  rdata_reg <= sat_count;
                        6'd9:  rdata_reg <= cdc_drops;
                        6'd10: rdata_reg <= irq_threshold;
                        6'd11: rdata_reg <= {8'd96, 8'd3, 8'd9, 8'd1};
                        default: s_axi_rresp <= 2'b10;
                    endcase
                end
            end

            // ring producer side
            if (cap_vld) begin
                write_count <= write_count + 32'd1;
                if (fill >= DEPTH) begin
                    overrun_count <= overrun_count + 32'd1;
                    overrun_sticky <= 1'b1;
                end
                sat_count <= sat_count + {31'd0, pay_cap[32]} + {31'd0, pay_cap[33]};
                if (pay_cap[32] || pay_cap[33]) sat_sticky <= 1'b1;
                if (seq_valid && pay_cap[35:34] != exp_seq) begin
                    cdc_drops <= cdc_drops + 32'd1;
                    cdc_sticky <= 1'b1;
                end
                exp_seq <= pay_cap[35:34] + 2'd1;
                seq_valid <= 1'b1;
            end

            // soft clear wins over everything above in the same cycle
            if (soft_clear) begin
                write_count <= 32'd0; read_count <= 32'd0;
                overrun_count <= 32'd0; sat_count <= 32'd0; cdc_drops <= 32'd0;
                overrun_sticky <= 1'b0; cdc_sticky <= 1'b0; sat_sticky <= 1'b0;
                seq_valid <= 1'b0;
            end
        end
    end

    wire _unused_ok = &{1'b0, s_axi_awprot, s_axi_arprot, rx_frames, dc_rv, 1'b0};
endmodule
