# Live FPGA-Accelerated Speech-to-Text on the Kria KV260

## Setup

The captioner runs on an AMD Kria KV260. A separate computer is required to
prepare various aspects of the model off-board, including source code vendoring
and PL synthesis.

Known working software versions:
- Kria Ubuntu 24.04 LTS
- Vivado 2026.1
- Python 3.14

If you use `nix`, `nix develop` sets up `cmake`, `make`, `clang` and `python3`.

### Overview

There are 7 total steps:
1. Download model weights
2. Synthesise PL
3. Package a tarball
4. Upload the tarball to the board
5. Extract the tarball
6. Plug everything in
7. Run the on-board installation script

Steps 1 and 2 can be performed at the same time (this is recommended as they
are the longest two steps in this process).

### Step 1 - Download Model Weights

Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r scripts/requirements.txt
python scripts/setup.py
```

Linux/Mac

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/setup.py
```

This step will download the model weights for QuartzNet and convert them into a
file format we can use on the board itself. The majority of this step is a
roughly 400 MB download.

On some machines the `pip install -r scripts/requirements.txt` might fail. The most
common culprit for this is having a system not supported by pytorch. To solve
this, we recommend you use a container or virtual machine, or another computer.

Intel silicon macs are unsupported by pytorch, so you'll need a virtualised or
containerised solution of some sort.

### Step 2 - Synthesise PL

```sh
vivado -mode batch -source hw/build.tcl
```

On some systems, vivado installs itself as a wrapper that changes the working
directory, so this command fails with "No such file or directory". If this
happens, use the absolute path to the file like so:

```sh
vivado -mode batch -source "$(pwd)/hw/build.tcl"
```

This will take some time (potentially upwards of 20-30 minutes). It is
recommended to also perform step 1 simultaneously to this to save time.

Also note that this requires the vivado binary to be on path and accessible.
You may need to source Vivado's settings script to do this (or simply add the
vivado install directory to your normal path):

```sh
source /tools/Xilinx/2026.1/Vivado/settings64.sh     # Linux
C:\AMDDesignTools\2026.1\Vivado\settings64.bat     # Windows
```

Add `-tclargs nomic` to build without the microphone, LED and button, for
transcribing recorded clips only.

### Step 3 - Package a Tarball

In order to make life easier when transferring files to the board, we package a
simple tarball.

```sh
bash scripts/package.sh
```

This will create a new tarball in the working directory called
`stt-caption-kv260.tar.xz` which you can upload to the board how you so choose
to do in the next step.

When running this script on Windows you will likely need to use `git bash` or
WSL.

### Step 4 - Upload the Tarball to the Board

There are two ways of doing this.

1. Take the SD card out of the board and put it into your computer. Then simply
   copy the tarball into a directory somewhere on the SD card.

Or

2. Connect to the board via ethernet (or otherwise get on the same LAN) and
   upload to it with a tool like scp

This is your choice. We recommend option 1 as it's less error prone and much
less host dependent (i.e. the process is similar regardless of your operating
system).

Note that if choosing option 1 you will need to select the correct partition.
This will be the `writable` partition, which contains a standard Linux root
filesystem.

### Step 5 - Extract the Tarball

Once the tarball is on the board, you will need to obtain a shell on the board.
This can be done via serial (i.e. by plugging in the usb serial cable) or over
ssh, which requires having the board connected to a LAN. The choice is, once
again, yours.

```sh
ubuntu@kria:~$ tar xmf stt-caption-kv260.tar.xz
```

### Step 6 - Plug Everything In

Before you start the captioner, make sure everything is plugged in. You should
have the following attached to your board.

- Power cable
- Displayport
- PMOD board and microphone

Note that the microphone should be plugged into J2 on the board (not J1), i.e.
the outermost microphone spot (also labelled Mic L).

### Step 7 - Run the On-Board Installation Script

Once the tarball is extracted, there's an installation script inside it.

```sh
ubuntu@kria:~$ cd stt-caption-install/
ubuntu@kria:~/stt-caption-install$ sudo bash install.sh --enable
```

This builds `caption`, `screen` and `transcript` from `app/` on the board (with
`cmake` if the board has it, otherwise straight through `cc`), builds the
u-dma-buf driver, and installs everything in `/opt/stt-caption`.

The `--enable` flag will immediately start the transcriber and enable it by
default on boot. If you don't want to do this (for example because you haven't
plugged everything in yet), simply omit the flag and start the service yourself
later.

It is recommended to check the status of the service after enabling it if you
require diagnostic information.

```sh
systemctl status stt-caption
```

## Running the project

The captioner runs as a systemd unit called `stt-caption.service`. It loads the
`stt-kv260` overlay (only in place of the boot default, never another project's
overlay), loads the u-dma-buf driver and runs `screen`, or `caption` with
`DISPLAY_CAPTIONS=no`.

As per normal systemd behaviour, you can do all the following:

```sh
systemctl start stt-caption
systemctl stop stt-caption
systemctl restart stt-caption
systemctl enable stt-caption
systemctl disable stt-caption
systemctl status stt-caption
```

Note that the transcriber disables gdm (gnome display manager), as it requires
the ability to take over the frame buffer, so if you want to use it you will
have to re-enable the `gdm.service` systemd unit.

While it runs, the LED is on during speech, and every 120 ms a preview shows the
settled words and a tentative tail. 0.7 s after speech stops, the phrase is
decoded once more and shown as the final. Pressing the button ends the session;
a new one starts a second later.

On the monitor, the phrase being spoken is drawn large on two live lines, with
the earlier phrases dimmed above it. A status strip along the bottom shows
whether someone is speaking, the microphone level, the runner, the last decode
time and the caption delay. After 5 s of silence the screen clears.

### Settings

Settings live in `/etc/default/stt-caption` on the board:

| Setting | Values |
|---|---|
| `RUNNER` | `hybrid` (the FPGA engine) or `cpu` (INT8 on the A53s) |
| `DISPLAY_CAPTIONS` | `yes` to draw on the monitor with `screen`, `no` to only log with `caption` |
| `DISPLAY_STATUS` | `yes` or `no` for the status strip along the bottom |
| `CLEAR_AFTER` | seconds of silence before the screen clears, `0` to never clear |
| `THEME` | `butter` (pastel yellow) or `night` (dark) |
| `SETTLE` | previews that must agree before a word settles, `0` for the previous preview only |

Changes to this file also require a restart of the service.

```sh
sudo systemctl restart stt-caption.service
```

Every session writes `/var/lib/stt-caption/sessions/<time>/captions.txt` (the
captions `caption` prints; empty for `screen`) and `stderr.txt`. `latest` points
at the newest, and the newest 20 are kept.
`sudo /opt/stt-caption/bin/stt-caption status` shows the overlay, the service
and the latest session.

### Running the programs by hand

Stop the service, then load the overlay and the DMA buffers the same way it
does:

```sh
sudo systemctl stop stt-caption
sudo /opt/stt-caption/bin/stt-caption prepare
cd /opt/stt-caption/share
```

For live captions in the terminal, run either the `hybrid` (FPGA) or `cpu`
runner. `hybrid` takes the engine program `quartznet_engine.bin`, and `cpu`
takes the INT8 weights `quartznet_int8.bin`:

```sh
sudo ../bin/caption hybrid quartznet_engine.bin running_prior.json
sudo ../bin/caption cpu quartznet_int8.bin running_prior.json
```

To show the live captions on the monitor, run `screen` instead of `caption`,
with the same arguments. Add `--no-status` to hide the strip, `--clear-after 0`
to keep the captions on screen, `--theme night` for a dark screen, or
`--settle 3` to only settle a word once 3 previews in a row agree on it:

```sh
sudo ../bin/screen hybrid quartznet_engine.bin running_prior.json
```

To turn a 16 kHz mono 16-bit WAV file into text (this also works with a `nomic`
build):

```sh
sudo ../bin/transcript hybrid quartznet_engine.bin running_prior.json speech.wav transcript.txt
```

Run `sudo /opt/stt-caption/bin/stt-caption cleanup` afterwards to give the
screen back to the text console.

You can also run the converted model on the PC, on the same kind of WAV file:

```sh
python scripts/run.py speech.wav
```

### Removing

You can uninstall the captioner by using the `uninstall.sh` script installed
with the rest of the system.

```sh
ubuntu@kria:~$ sudo /opt/stt-caption/uninstall.sh
```

Or to also remove `/etc/default/stt-caption` and logs:

```sh
ubuntu@kria:~$ sudo /opt/stt-caption/uninstall.sh --purge
```

### Running tests

Similarly to the vivado build command, you can run the RTL testbenches:

```sh
vivado -mode batch -source sim/run.tcl
```

This runs the two front end and three engine testbenches in `sim/`; each prints
`PASS` or a `FAIL` message.

The display layouts and the settle rule have tests of their own, run on the
board or any Linux machine from the source directory:

```sh
cmake -S app -B build/app -G "Unix Makefiles"
cmake --build build/app
ctest --test-dir build/app
```
