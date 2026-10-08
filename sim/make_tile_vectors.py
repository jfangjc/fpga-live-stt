"""Independent Python integer reference for the Verilog tile scoreboard."""
from pathlib import Path

root = Path(__file__).parent / 'tile_vectors'
root.mkdir(exist_ok=True)
for length, seed in ((1, 0), (17, 9), (257, 19), (1024, 255), (17, 11)):
    values = []
    for time in range(16):
        for output in range(16):
            total = sum(((k * 17 + time * 7 + seed) % 256 - 128) *
                        ((k * 31 + output * 13 + seed * 3) % 256 - 128)
                        for k in range(length))
            values.append(f'{total & 0xffffffff:08x}')
    (root / f'k{length}_s{seed}.hex').write_text('\n'.join(values) + '\n')
print('Generated independent signed integer tile references')
