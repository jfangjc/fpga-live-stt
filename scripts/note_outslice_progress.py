"""Append Oct13 output-pipeline progress without changing legacy text encoding."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'LATENCY20_PROGRESS.md'
text=path.read_bytes().decode('cp1252')
note='''

### 2026-10-13: isolated output pipeline, routed build pending

The final SLICE166 route failed the unchanged timing gate: setup -0.536 ns,
hold +0.002 ns, 1,371 failing setup endpoints. No qualified XSA or board
deployment occurred. Preserved source-bound failure report:
reports/fused/branch512_slice166_timing_failure.json. The worst path runs
from a pointwise DSP through output/control muxes to the outer step enable.

Added separate qn_branch512_outslice_axis.sv with a one-beat elastic output
register. A retained completion flag prevents loss of the engine done pulse
while a weight-load ACK is buffered. LOADACK and COUNTER consume only on
valid/ready handshakes. Pointwise and depthwise arithmetic remain unchanged.
Passed all 25 full-block arithmetic/protocol/backpressure cases; six reset
and replay cases cover internal load acknowledgements, input stream and
quantizer buffers; two additional cases reset full output-data buffers.
Evidence: reports/fused/branch512_outslice_regression_evidence.json. Parent
arithmetic, software-model, driver and 77-access AXI proofs remain bound.

An initial output-data reset fixture incorrectly forced internal readiness
without stalling the external consumer. Its failure log is preserved as
branch512_outslice_payload_reset_fixture_failure.log. After asserting both
stalls consistently, the two cases passed. No RTL arithmetic was altered.
A generated proof-file path typo was corrected before synthesis began.

The isolated build/branch512_outslice166_system project targets 166.7 MHz.
Synthesis/routing are running; final setup >= 0.001 ns, hold >= 0 and clean
error/critical-warning DRC are required before export. No new physical
latency improvement is claimed. Accepted measurements remain adaptive:
0.5 s 38.939 ms / 30.323%, 1 s 54.158 ms / 43.024%,
2.5 s 91.601 ms / 38.899% reductions against paired optimized CPU.
The goal remains hybrid p50 <= half the strongest valid CPU p50, lower p95
and exact outputs, including all weight transfers and synchronization.

Four sequential qualification watchers wait for routed proof then base,
scale-split, additional pointwise retention and optional NEON tests. They
use their own firmware/report names and restore bulk100M after each board
run. Twenty-four staged board tools match local SHA256; all four ARM64
benchmark modules import successfully. New watchers decode both UTF-16
PowerShell logs and UTF-8 logs; all four detected the actual failed-route
log in the regression. Old waiting jobs exited without board deployment.
Read-only board check confirmed bulk clock 99,999,999 Hz and no benchmark
job active. Broader candidates remain software-qualified development.
'''
if '### 2026-10-13: isolated output pipeline, routed build pending' not in text:
    path.write_bytes((text+note).encode('cp1252'))
print('Saved output-pipeline progress; 2x speed remains unproven')
