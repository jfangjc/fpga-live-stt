"""Read-only independent audit of prior evidence; no board claims."""
import hashlib
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / "Prototype"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    board = json.loads((OLD / "reports/quartznet_cached_board.json").read_text())
    traffic = json.loads((OLD / "reports/cached_architecture_estimate.json").read_text())
    hardware = json.loads((OLD / "reports/cached_hardware_validation.json").read_text())
    computed = {"loads": 0, "runs": 0, "ioctls": 0, "tx": 0, "rx": 0,
                "padded_macs": 0, "minimum_core_cycles": 0}
    for layer in traffic["layers"]:
        k, m, t = (layer[x] for x in ("k", "m", "time_frames"))
        g, runs = (m + 15) // 16, (t + 15) // 16
        load, packet, response = 16 + 16 * k * g, 16 + 16 * k, 16 + 1024 * g
        batch = min(128, 133120 // response)
        computed["loads"] += 1
        computed["runs"] += runs
        computed["ioctls"] += 1 + (runs + batch - 1) // batch
        computed["tx"] += load + packet * runs
        computed["rx"] += 16 + response * runs
        computed["padded_macs"] += runs * g * k * 256
        # Stream input, then serial compute and output per group. Excludes
        # pipeline drain, clear, response, LOAD, handshake and stalls.
        computed["minimum_core_cycles"] += runs * (k + g * (k + 64))
    expected = dict(loads=94, runs=3008, ioctls=699, tx=36831712, rx=79282656)
    assert all(computed[k] == v for k, v in expected.items()), computed
    hashes = {rel: {"actual": sha(OLD / rel), "expected": digest}
              for rel, digest in hardware["sha256"].items()}
    assert all(x["actual"] == x["expected"] for x in hashes.values()), hashes
    module = OLD / "software/tile-driver/prebuilt/6.8.0-1015-xilinx/qn_tile_cached.ko"
    blob = module.read_bytes()
    assert blob[:4] == b"\x7fELF" and blob[4:6] == b"\x02\x01"
    assert struct.unpack_from("<H", blob, 18)[0] == 183
    vermagic = re.search(rb"vermagic=([^\x00]+)", blob).group(1).decode()
    pins = {}
    constraint = ROOT / "Prototype_v2.srcs/constrs_1/imports/Lab2b-Files/kria-constraints.xdc"
    for pin, port in re.findall(r"set_property PACKAGE_PIN (\w+) \[get_ports (\w+)\]", constraint.read_text()):
        pins[port] = pin
    cpu, hybrid = board["cpu"]["total_seconds"], board["run"]["total_seconds"]
    profile = board["profile"]
    result = {
        "kind": "independent local artifact audit; estimates are not physical measurements",
        "historical_evidence_hashes_match": True,
        "module_architecture": "ELF64 little-endian AArch64", "vermagic": vermagic,
        "constraint_sha256": sha(constraint), "constraint_pin_assignments": pins,
        "protocol_recomputed": computed,
        "core_cycle_lower_bound_seconds_at_100MHz": computed["minimum_core_cycles"] / 1e8,
        "int32_accumulator_extreme_abs_upper_bound": 1024 * 128 * 128,
        "budget": {
            "old_cpu_seconds": cpu, "old_hybrid_seconds": hybrid,
            "target_20_percent_lower_seconds": cpu * .8,
            "old_hybrid_over_cpu": hybrid / cpu,
            "all_ioctl_removed_floor_seconds": hybrid - profile["kernel_ioctl_seconds"],
            "all_pointwise_host_work_removed_floor_seconds": hybrid - (profile["int8_pointwise_seconds"] - profile["kernel_ioctl_seconds"]),
        },
        "artifacts": hashes,
        "limitations": ["No KV260 access or new physical measurements", "Vermagic/hash verification does not prove module loading or DMA compatibility", "Verified voice_dma_top maps pmod_i2s ports to internal mic_* ports; retain this wrapper or adapt constraints explicitly", "Historical routed results do not validate a new prototype_v2 build", "Minimum serial core cycles exclude several positive overheads and stalls"]
    }
    out = ROOT / "verification/existing_audit.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

