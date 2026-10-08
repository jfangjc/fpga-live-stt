# V1 board package

Loads the V1 design (microphone capture and the AXI-Lite INT8 dot product) as
the `voice-prototype` xmutil application, then runs a short smoke test. It
does not run speech recognition.

| File | Purpose |
|---|---|
| `voice-prototype/voice-prototype.dts`, `shell.json` | Overlay source and `PL_FLAT` metadata |
| `install.sh` | Installs the app into `/lib/firmware/xilinx/voice-prototype`; refuses to overwrite |
| `load_and_test.sh` | Loads the app, checks clock, AFI and UIO bindings, runs `board_smoke.py` |
| `restore.sh` | Restores the stock `k26-starter-kits` app |
| `kv260_voice.py`, `board_smoke.py` | UIO driver and smoke test |
| `validation/` | Offline overlay checks against the board's live device tree |

## Build the package

The bitstream binary and overlay are build outputs. From the repository root,
after building V1:

```sh
bootgen -arch zynqmp -image scripts/voice_bitstream.bif -process_bitstream bin -w on
cp Prototype.runs/impl_1/voice_top.bit.bin deployment/voice-prototype/voice-prototype.bit.bin
dtc -@ -I dts -O dtb -o deployment/voice-prototype/voice-prototype.dtbo deployment/voice-prototype/voice-prototype.dts
```

`install.sh` checks `SHA256SUMS`, so regenerate it from inside `deployment/`
after rebuilding.

## Run on the board

Copy this folder to the board (it was used as `~/voice-deployment`), then:

```bash
cd ~/voice-deployment
python3 kv260_voice.py --selftest
sudo sh install.sh
sudo xmutil listapps          # voice-prototype must appear as PL_FLAT
sudo sh load_and_test.sh
```

Expected output:

```text
PASS: physical accelerator signed dot = -32384
PASS: capture engine delivered 160 PCM24 samples
```

The overlay requests 100 MHz on PL0. Check it with
`cat /sys/bus/platform/devices/voice-pl0-clock/set_rate` (the board reads
99,999,999 Hz). Restore the stock app with `sudo sh restore.sh`.

The UIO index is discovered by name, not assumed. The FIFO overflow flag is
sticky until reset, and capture can overflow while Linux binds devices, so
the test drains the backlog first.

## Microphone wiring

| SPH0645 | FPGA port | Package pin |
|---|---|---|
| BCLK | `pmod_i2s_bclk` | D11 |
| WS | `pmod_i2s_lrclk` | B10 |
| DATA | `pmod_i2s_dout` (input) | E12 |
| SELECT | ground (left channel) | — |
| VDD / GND | 3.3 V / ground | — |

Fit a 100 kOhm pulldown on DATA. Package pins are not connector pin numbers;
check the carrier connector mapping in `Prototype.srcs/constrs_1/` first.

The receiver makes about 1.024 MHz BCLK and 16 kHz WS from the 100 MHz clock
with a 32-bit phase accumulator. It samples on the falling edge and keeps 24
bits of the left slot (the microphone provides 18).

## Register map

Byte offsets from 0xA0000000. Use aligned 32-bit accesses; partial writes
return SLVERR. The IRQ (GIC SPI 89, level high) fires at 160 samples or on
overflow.

| Offset | Purpose |
|---|---|
| 0x0000 | Control: bit0 START, bit1 clear DONE/ERROR |
| 0x0004 | Status: bit0 BUSY, bit1 DONE, bit2 length ERROR |
| 0x0008 | Vector length, 1..4096 |
| 0x000C | Signed INT32 initial bias or previous partial sum |
| 0x0010 | bits4:0 arithmetic right shift, bit8 ReLU |
| 0x0014 | Saturated INT8 result |
| 0x0018 | Raw INT32 accumulator |
| 0x1000..0x1FFC | 4096 INT8 inputs, four per word |
| 0x2000..0x2FFC | 4096 INT8 weights, four per word |
| 0x8000 | Audio status: bits10:0 count, bit16 empty, bit17 full, bit18 overflow |
| 0x8004 | Pop one PCM24 sample; empty read returns SLVERR |
| 0x8008 | Dropped-sample counter |
| 0x800C | Captured-frame counter |
