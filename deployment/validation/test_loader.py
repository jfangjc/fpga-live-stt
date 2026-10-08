"""Run loader against a private fake sysfs and command stubs; no hardware access."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile


root = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix="loader-test-", dir=root / "validation") as tmp:
    fixture = Path(tmp)
    package = fixture / "package"
    package.mkdir()
    for name in ("load_and_test.sh", "package_listing.awk", "SHA256SUMS", "README.md",
                 "install.sh", "restore.sh", "kv260_voice.py", "board_smoke.py"):
        shutil.copyfile(root / name, package / name)
    shutil.copytree(root / "voice-prototype", package / "voice-prototype")
    firmware = fixture / "firmware" / "xilinx" / "voice-prototype"
    shutil.copytree(root / "voice-prototype", firmware)
    sysfs = fixture / "sys"
    for driver in ("uio_pdrv_genirq", "xilinx_fclk", "afi-fpga"):
        (sysfs / "bus/platform/drivers" / driver).mkdir(parents=True)
    devices = sysfs / "bus/platform/devices"
    for name, driver in (("voice-pl0-clock", "xilinx_fclk"), ("axi:voice-afi", "afi-fpga")):
        device = devices / name
        device.mkdir(parents=True)
        (device / "driver").symlink_to(sysfs / "bus/platform/drivers" / driver)
    (devices / "voice-pl0-clock/set_rate").write_text("99999001\n")
    manager = sysfs / "class/fpga_manager/fpga0"
    manager.mkdir(parents=True)
    (manager / "state").write_text("operating\n")
    uio = sysfs / "class/uio/uio4"
    (uio / "maps/map0").mkdir(parents=True)
    (uio / "name").write_text("voice-prototype\n")
    (uio / "maps/map0/addr").write_text("0x00000000a0000000\n")
    (uio / "maps/map0/size").write_text("0x0000000000010000\n")
    commands = fixture / "bin"
    commands.mkdir()
    listing = fixture / "listing.txt"
    listing.write_text("3 PL_FLAT - - voice-pr... id_ok PL_FLAT (0+0+0) -1 voice-prototype\n")
    actions = fixture / "actions.txt"
    stubs = {
        "id": "echo 0",
        "sha256sum": "exit 0",  # Archive integrity is verified separately.
        "xmutil": f'if [ "$1" = listapps ]; then cat "{listing}"; else echo "$*" >> "{actions}"; fi',
        "python3": f'echo "smoke $*" >> "{actions}"',
        "modprobe": "echo 'Unexpected module load' >&2; exit 99",
    }
    for name, body in stubs.items():
        executable = commands / name
        executable.write_text("#!/bin/sh\n" + body + "\n")
        executable.chmod(0o755)
    source = (root / "load_and_test.sh").read_text()
    source = source.replace("/sys/", str(sysfs) + "/")
    source = source.replace("/lib/firmware/", str(fixture / "firmware") + "/")
    (package / "load_and_test.sh").write_text(source)
    env = dict(os.environ, PATH=str(commands) + ":" + os.environ["PATH"])
    result = subprocess.run(["sh", str(package / "load_and_test.sh")], env=env,
                            capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    recorded = actions.read_text()
    assert "loadapp voice-prototype" in recorded
    assert "unloadapp" not in recorded
    assert "smoke board_smoke.py /dev/uio4" in recorded
    assert not (sysfs / "module/uio_pdrv_genirq/parameters/of_id").exists()
    # An incorrect mapping must stop before the mocked MMIO test.
    actions.write_text("")
    (uio / "maps/map0/addr").write_text("0x00000000ffa00000\n")
    result = subprocess.run(["sh", str(package / "load_and_test.sh")], env=env,
                            capture_output=True, text=True)
    assert result.returncode != 0 and "Unexpected UIO address" in result.stdout
    assert "smoke" not in actions.read_text()
print("PASS: loader proceeds without hidden of_id, skips inactive unload, checks mapping before MMIO")
