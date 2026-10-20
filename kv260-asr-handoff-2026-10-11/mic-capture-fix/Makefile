# Mic capture fix: lint, unit tests and cocotb simulations (Mac or Linux, no Vivado needed).
#   make            lint + pytest + all four cocotb DUTs
#   make sim DUT=top [WAVES=1]   one DUT (i2s_rx | decim3 | dc_gain | top)
#   make waves DUT=top           open sim/dump_<DUT>.fst in Surfer
#   make bench-dry               3 s dry run of sw/bench_capture.py on a simulated device
#   make coeffs                  regenerate rtl/decim3_coeffs.vh and sim/decim3_coeffs.py
#   make dist                    zip this folder for review (excludes build output)
PYTHON ?= python3
DUTS := i2s_rx decim3 dc_gain top
RTL := rtl/audio_capture_axi.v rtl/i2s_rx_stereo.v rtl/decim3_fir.v rtl/dc_gain.v

.PHONY: all lint pytest sim simall waves bench-dry coeffs dist clean
all: lint pytest simall

lint:
	verilator --lint-only -Wall -Irtl --top-module audio_capture_axi $(RTL)
	@echo "lint: clean (verilator -Wall)"

pytest:
	cd sim && $(PYTHON) -m pytest -q test_coeffs.py
	cd sw && $(PYTHON) -m pytest -q test_audio_ring.py

sim:
	$(MAKE) -C sim DUT=$(DUT)
	@if [ -f sim/dump.fst ]; then mv -f sim/dump.fst sim/dump_$(DUT).fst; fi

simall:
	@for d in $(DUTS); do $(MAKE) -C sim DUT=$$d || exit 1; done
	@$(PYTHON) scripts/summarise_results.py sim

waves:
	surfer sim/dump_$(DUT).fst &

bench-dry:
	cd sw && $(PYTHON) bench_capture.py --fake --seconds 3 --hop-ms 250 --out bench_dry.json

coeffs:
	$(PYTHON) scripts/gen_coeffs.py

dist: clean
	cd .. && rm -f mic-capture-fix.zip && zip -qr mic-capture-fix.zip mic-capture-fix -x '*/__pycache__/*' '*/.pytest_cache/*'
	@echo "wrote ../mic-capture-fix.zip"

clean:
	rm -rf sim/sim_build_* sim/results_*.xml sim/dump*.fst sim/__pycache__ sw/__pycache__ sim/.pytest_cache sw/.pytest_cache .pytest_cache sw/bench_dry.json
