#!/usr/bin/env python3
"""Summarize saved graph costs or time kernel ioctls during a hybrid run.

ioctl time includes kernel copies, descriptor setup, waiting and completion;
it is not a measurement of FPGA compute time alone. No driver/RTL changes.
"""
import argparse
import json
from pathlib import Path
import runpy
import sys
import time


def summarize(report):
    layers = report.get('layers', report.get('hybrid_layer_timings', []))
    if not layers:
        raise ValueError('Report has no layer timings')
    result = {
        'hardware_execution': report.get('hardware_execution', False),
        'int8_pointwise_seconds': sum(x['seconds'] for x in layers if x['int8_pointwise']),
        'other_graph_seconds': sum(x['seconds'] for x in layers if not x['int8_pointwise']),
        'kernel_ioctl_seconds': report.get('kernel_ioctl_seconds'),
        'ioctl_calls': report.get('ioctl_calls'),
        'dma_input_bytes': report.get('dma_input_bytes'),
        'dma_output_bytes':report.get('dma_output_bytes'),
        'pointwise_backend':report.get('pointwise_backend','tile'),
        'cached_load_commands':report.get('cached_load_commands',0),
        'cached_run_commands':report.get('cached_run_commands',0),
        'cached_batch_size':report.get('cached_batch_size'),
        'computed_tile_groups':report.get('computed_tile_groups'),
        'dma_command_packets':report.get('dma_command_packets'),
        'cpu_conv_backend': report.get('cpu_conv_backend', 'numpy'),
        'peak_process_rss_kib': report.get('peak_process_rss_kib'),
        'slowest_layers': sorted(layers, key=lambda x:x['seconds'], reverse=True)[:8],
    }
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--summary', type=Path)
    modes.add_argument('--wav', type=Path)
    parser.add_argument('--batch-size', type=int, default=128)
    parser.add_argument('--device', default='/dev/qn-tile')
    parser.add_argument('--pointwise-backend',choices=('tile','cached'),default='tile')
    parser.add_argument('--cached-batch-size',type=int,default=128)
    parser.add_argument('--remove-dc', action='store_true')
    parser.add_argument('--cpu-conv-backend', choices=('numpy', 'ort', 'native'), default='numpy')
    parser.add_argument('--cpu-conv-threads',type=int,choices=range(1,5),default=4)
    parser.add_argument('--report', type=Path, default=Path('hybrid-profile.json'))
    args = parser.parse_args()
    if args.summary:
        summarize(json.loads(args.summary.read_text()))
        return
    if not 1 <= args.batch_size <= 128:
        parser.error('--batch-size must be 1..128')
    if not 1 <= args.cached_batch_size <= 128:
        parser.error('--cached-batch-size must be 1..128')
    import fcntl
    original_ioctl = fcntl.ioctl
    measurements = {'kernel_ioctl_seconds': 0.0, 'profile_ioctl_calls': 0}
    def timed_ioctl(*values, **kwargs):
        started = time.perf_counter()
        try:
            return original_ioctl(*values, **kwargs)
        finally:
            measurements['kernel_ioctl_seconds'] += time.perf_counter()-started
            measurements['profile_ioctl_calls'] += 1
    runner = Path(__file__).resolve().parent/'asr-baseline/quartznet_hybrid.py'
    original_argv = sys.argv
    original_path = sys.path[:]
    try:
        fcntl.ioctl = timed_ioctl
        sys.path.insert(0, str(runner.parent))
        sys.argv = [str(runner), str(args.wav), '--device', args.device,
                    '--dma-batch-size', str(args.batch_size), '--report', str(args.report),
                    '--cpu-conv-backend', args.cpu_conv_backend,
                    '--cpu-conv-threads', str(args.cpu_conv_threads)]
        sys.argv.extend(['--pointwise-backend',args.pointwise_backend])
        sys.argv.extend(['--cached-batch-size',str(args.cached_batch_size)])
        if args.remove_dc:
            sys.argv.append('--remove-dc')
        runpy.run_path(str(runner), run_name='__main__')
    finally:
        fcntl.ioctl = original_ioctl
        sys.argv = original_argv
        sys.path[:] = original_path
    report = json.loads(args.report.read_text())
    report.update(measurements)
    # This profiler runs on Linux: ru_maxrss is KiB, includes graph setup.
    import resource
    report['peak_process_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert report['ioctl_calls'] == measurements['profile_ioctl_calls']
    args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    summarize(report)


if __name__ == '__main__':
    main()
