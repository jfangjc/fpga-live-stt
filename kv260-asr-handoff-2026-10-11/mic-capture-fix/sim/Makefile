# cocotb 2.1 + Verilator. One DUT per invocation:
#   make DUT=i2s_rx | decim3 | dc_gain | top     [WAVES=1]
# The top-level Makefile runs all four. Waves land in sim/dump_<DUT>.fst.
SIM ?= verilator
TOPLEVEL_LANG = verilog
DUT ?= top
RTL := $(CURDIR)/../rtl

ifeq ($(DUT),i2s_rx)
VERILOG_SOURCES = $(RTL)/i2s_rx_stereo.v
COCOTB_TOPLEVEL = i2s_rx_stereo
COCOTB_TEST_MODULES = test_i2s_rx
else ifeq ($(DUT),decim3)
VERILOG_SOURCES = $(RTL)/decim3_fir.v
COCOTB_TOPLEVEL = decim3_fir
COCOTB_TEST_MODULES = test_decim3
else ifeq ($(DUT),dc_gain)
VERILOG_SOURCES = $(RTL)/dc_gain.v
COCOTB_TOPLEVEL = dc_gain
COCOTB_TEST_MODULES = test_dc_gain
else ifeq ($(DUT),top)
VERILOG_SOURCES = $(RTL)/audio_capture_axi.v $(RTL)/i2s_rx_stereo.v $(RTL)/decim3_fir.v $(RTL)/dc_gain.v
COCOTB_TOPLEVEL = audio_capture_axi
COCOTB_TEST_MODULES = test_audio_capture
else
$(error Unknown DUT '$(DUT)'; use i2s_rx, decim3, dc_gain or top)
endif

EXTRA_ARGS += -I$(RTL) -Wno-fatal
ifeq ($(WAVES),1)
EXTRA_ARGS += --trace-fst --trace-structs
COCOTB_PLUSARGS += --trace
endif

# Separate build dir for wave builds: cocotb does not rebuild when only flags change.
SIM_BUILD = $(CURDIR)/sim_build_$(DUT)$(if $(filter 1,$(WAVES)),_waves,)
COCOTB_RESULTS_FILE = $(CURDIR)/results_$(DUT).xml
export PYTHONPATH := $(CURDIR):$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim
