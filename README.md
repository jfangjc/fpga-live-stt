# Live FPGA-Accelerated Speech-to-Text on the Kria KV260

## Setup
The captioner runs on an AMD Kria KV260, with a separate computer to download and convert the model and synthesise the PL. It is known to work with Kria Ubuntu 24.04 LTS, Vivado 2026.1 and Python 3.14.

If you use `nix`, you can set up `cmake`, `make`, `clang` and `python3` using just:

```bash
nix develop
```

Source Vivado by using its included `settings64.sh` or `settings64.bat` for Windows (or add the Vivado install directory to your path):

```bash
source /tools/Xilinx/2026.1/Vivado/settings64.sh
```

Or for Windows:

```powershell
C:\AMDDesignTools\2026.1\Vivado\settings64.bat
```

Downloading the model and building the bitstream are the two longest steps, so it is worth running them at the same time.

Next is to download and convert the model. Run the below from the root of the project:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/setup.py
```

Or for Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r scripts/requirements.txt
python scripts/setup.py
```

This downloads the QuartzNet weights (mostly a roughly 400 MB download) and converts them into a format the board can use. If `pip install -r scripts/requirements.txt` fails, the most common cause is a system not supported by pytorch, such as an Intel Mac. Use a container, a virtual machine or another computer instead.

Now build the bitstream. Run the below from the root of the project:

```bash
vivado -mode batch -source hw/build.tcl
```

This can take upwards of 20-30 minutes. On some systems vivado installs itself as a wrapper that changes the working directory, so this fails with "No such file or directory". If this happens, use the absolute path:

```bash
vivado -mode batch -source "$(pwd)/hw/build.tcl"
```

Add `-tclargs nomic` to build without the microphone, LED and button, for transcribing recorded clips only.

Then package everything the board needs into a tarball called `stt-caption-kv260.tar.xz` in the working directory. On Windows run this from `git bash` or WSL:

```bash
bash scripts/package.sh
```

## Installing on the board
Copy the tarball to the board, either by taking the SD card out and copying it onto the `writable` partition (the board's standard Linux root filesystem), or over the network with a tool like `scp`. The SD card is recommended as it is less error prone and works the same on any operating system.

Get a shell on the board over the USB serial cable or ssh, and extract the tarball:

```bash
tar xmf stt-caption-kv260.tar.xz
```

Before starting the captioner, plug in the power cable, the DisplayPort monitor, and the PMOD board with the microphone. The microphone goes in J2 (not J1), the outermost spot labelled Mic L.

Then run the installation script from the tarball:

```bash
cd stt-caption-install/
sudo bash install.sh --enable
```

This builds `caption`, `screen` and `transcript` from `app/` on the board (with `cmake` if the board has it, otherwise straight through `cc`), builds the u-dma-buf driver, and installs everything in `/opt/stt-caption`. `--enable` starts the captioner now and on every boot. Leave it out if everything is not plugged in yet and start the service yourself later. Check the status of the service afterwards for diagnostic information:

```bash
systemctl status stt-caption
```

## Running the project
The captioner runs as a systemd unit called `stt-caption.service`. It loads the `stt-kv260` overlay (only in place of the boot default, never another project's overlay), loads the u-dma-buf driver and runs `screen`, or `caption` with `DISPLAY_CAPTIONS=no`. It works like any other unit:

```bash
systemctl start stt-caption
systemctl stop stt-caption
systemctl restart stt-caption
systemctl enable stt-caption
systemctl disable stt-caption
systemctl status stt-caption
```

The captioner disables gdm (GNOME display manager) as it needs to take over the framebuffer, so re-enable the `gdm.service` unit if you want to use it.

While it runs, the LED is on during speech, and every 120 ms a preview shows the settled words and a tentative tail. 0.7 s after speech stops, the phrase is decoded once more and shown as the final. Pressing the button ends the session and a new one starts a second later.

On the monitor, the phrase being spoken is drawn large on two live lines, with the earlier phrases dimmed above it. A status strip along the bottom shows whether someone is speaking, the microphone level, the runner, the last decode time and the caption delay. After 5 s of silence the screen clears.

Settings live in `/etc/default/stt-caption` on the board:

- `RUNNER` is `hybrid` (the FPGA engine) or `cpu` (INT8 on the A53s)
- `DISPLAY_CAPTIONS` is `yes` to draw on the monitor with `screen`, or `no` to only log with `caption`
- `DISPLAY_STATUS` is `yes` or `no` for the status strip along the bottom
- `CLEAR_AFTER` is the seconds of silence before the screen clears, or `0` to never clear
- `THEME` is `butter` (pastel yellow) or `night` (dark)
- `SETTLE` is the number of previews that must agree before a word settles, or `0` for the previous preview only

Restart the service after changing them:

```bash
sudo systemctl restart stt-caption.service
```

Every session writes `/var/lib/stt-caption/sessions/<time>/captions.txt` (the captions `caption` prints, empty for `screen`) and `stderr.txt`. `latest` points at the newest, and the newest 20 are kept. `sudo /opt/stt-caption/bin/stt-caption status` shows the overlay, the service and the latest session.

To run the programs by hand, stop the service, then load the overlay and the DMA buffers the same way it does:

```bash
sudo systemctl stop stt-caption
sudo /opt/stt-caption/bin/stt-caption prepare
cd /opt/stt-caption/share
```

For live captions in the terminal, run either the `hybrid` (FPGA) or `cpu` runner. `hybrid` takes the engine program `quartznet_engine.bin`, and `cpu` takes the INT8 weights `quartznet_int8.bin`:

```bash
sudo ../bin/caption hybrid quartznet_engine.bin running_prior.json
sudo ../bin/caption cpu quartznet_int8.bin running_prior.json
```

To show the live captions on the monitor, run `screen` instead of `caption`, with the same arguments. Add `--no-status` to hide the strip, `--clear-after 0` to keep the captions on screen, `--theme night` for a dark screen, or `--settle 3` to only settle a word once 3 previews in a row agree on it:

```bash
sudo ../bin/screen hybrid quartznet_engine.bin running_prior.json
```

To show the same layout in a terminal instead, for example over ssh or the serial console with no monitor attached, add `--output terminal`. The two dim history lines, the live phrase with its settled words in bold and the rest in yellow, and the status line are redrawn in place at the top of the terminal, in the terminal's own colours (`--theme` only applies to the monitor):

```bash
sudo ../bin/screen hybrid quartznet_engine.bin running_prior.json --output terminal
```

To turn a 16 kHz mono 16-bit WAV file into text (this also works with a `nomic` build):

```bash
sudo ../bin/transcript hybrid quartznet_engine.bin running_prior.json speech.wav transcript.txt
```

Run `sudo /opt/stt-caption/bin/stt-caption cleanup` afterwards to give the screen back to the text console.

You can also run the converted model on the PC, on the same kind of WAV file:

```bash
python scripts/run.py speech.wav
```

To uninstall the captioner, run the `uninstall.sh` script installed with it. Add `--purge` to also remove `/etc/default/stt-caption` and the logs:

```bash
sudo /opt/stt-caption/uninstall.sh
sudo /opt/stt-caption/uninstall.sh --purge
```

You can run all the RTL testbenches using `run.tcl` in `./sim` at the root of the project. This runs the two front end and three engine testbenches in `sim/`, and each prints `PASS` or a `FAIL` message:

```bash
vivado -mode batch -source sim/run.tcl
```

The monitor and terminal layouts and the settle rule have tests of their own, run on the board or any Linux machine from the source directory:

```bash
cmake -S app -B build/app -G "Unix Makefiles"
cmake --build build/app
ctest --test-dir build/app
```
