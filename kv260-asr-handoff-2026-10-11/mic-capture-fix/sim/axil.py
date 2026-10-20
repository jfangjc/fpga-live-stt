"""Minimal AXI4-Lite master for cocotb (single outstanding transaction).

Signals are driven on the falling edge and handshakes are evaluated there too. Ready and
valid only change on rising edges, so the values seen half a cycle later are stable.
"""
from cocotb.triggers import FallingEdge, RisingEdge

OKAY, SLVERR = 0, 2


class AxiLiteMaster:
    def __init__(self, dut, clk, prefix="s_axi_"):
        self.clk = clk
        self.s = lambda name: getattr(dut, prefix + name)
        for name in ("awvalid", "wvalid", "bready", "arvalid", "rready"):
            self.s(name).value = 0
        self.s("awaddr").value = 0
        self.s("araddr").value = 0
        self.s("wdata").value = 0
        self.s("wstrb").value = 0
        self.s("awprot").value = 0
        self.s("arprot").value = 0

    async def write(self, addr, data, strb=0xF):
        s = self.s
        await FallingEdge(self.clk)
        s("awaddr").value = addr
        s("awvalid").value = 1
        s("wdata").value = data & 0xFFFFFFFF
        s("wstrb").value = strb
        s("wvalid").value = 1
        s("bready").value = 1
        aw_done = w_done = False
        while not (aw_done and w_done):
            aw_now = not aw_done and int(s("awready").value) == 1
            w_now = not w_done and int(s("wready").value) == 1
            await RisingEdge(self.clk)
            await FallingEdge(self.clk)
            if aw_now:
                aw_done = True
                s("awvalid").value = 0
            if w_now:
                w_done = True
                s("wvalid").value = 0
        while int(s("bvalid").value) != 1:
            await FallingEdge(self.clk)
        resp = int(s("bresp").value)
        await RisingEdge(self.clk)
        await FallingEdge(self.clk)
        s("bready").value = 0
        return resp

    async def read(self, addr):
        s = self.s
        await FallingEdge(self.clk)
        s("araddr").value = addr
        s("arvalid").value = 1
        s("rready").value = 1
        while True:
            ar_now = int(s("arready").value) == 1
            await RisingEdge(self.clk)
            await FallingEdge(self.clk)
            if ar_now:
                s("arvalid").value = 0
                break
        while int(s("rvalid").value) != 1:
            await FallingEdge(self.clk)
        data = int(s("rdata").value)
        resp = int(s("rresp").value)
        await RisingEdge(self.clk)
        await FallingEdge(self.clk)
        s("rready").value = 0
        return data, resp
