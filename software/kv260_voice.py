#!/usr/bin/env python3
"""Linux UIO driver and operator harness for voice_axi / qn_mac.

The core driver uses only the standard library. This is a bring-up harness,
not a trained QuartzNet application or a real-time inference runtime.
"""
import argparse
import ctypes
import mmap
import operator
import os
import sys
import threading
import time


def signed32(value):
    value &= 0xffffffff
    return value - 0x100000000 if value & 0x80000000 else value


def int8_values(values):
    result = [operator.index(v) for v in values]
    if any(v < -128 or v > 127 for v in result):
        raise ValueError("inputs and weights must be signed INT8 (-128..127)")
    return result


def pack_words(values):
    for offset in range(0, len(values), 4):
        yield sum((v & 255) << (8 * lane)
                  for lane, v in enumerate(values[offset:offset + 4]))


class UIOMMIO:
    """Map UIO map0. The kernel must expose this IP's 64 KiB device region.

    Do not map normal cached RAM. This expects Linux's UIO device mapping
    and its ARM device-memory ordering. Use a kernel driver for production.
    """
    def __init__(self, device="/dev/uio0", size=0x10000):
        if sys.byteorder != "little":
            raise RuntimeError("this AXI register driver requires a little-endian CPU")
        self.size = size
        self.fd = os.open(device, os.O_RDWR | os.O_SYNC)
        try:
            self.mapping = mmap.mmap(self.fd, size, flags=mmap.MAP_SHARED,
                                     prot=mmap.PROT_READ | mmap.PROT_WRITE,
                                     offset=0)
        except BaseException:
            os.close(self.fd)
            raise

    def _check(self, address):
        if address < 0 or address + 4 > self.size or address % 4:
            raise ValueError("MMIO requires an aligned address inside the mapping")

    def read32(self, address):
        self._check(address)
        # A typed native 32-bit access is required: byte-oriented struct reads
        # can pop the audio FIFO repeatedly or issue unsupported bus accesses.
        return ctypes.c_uint32.from_buffer(self.mapping, address).value

    def write32(self, address, value):
        self._check(address)
        ctypes.c_uint32.from_buffer(self.mapping, address).value = value & 0xffffffff

    def close(self):
        self.mapping.close()
        os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class VoiceAccelerator:
    CONTROL, STATUS, LENGTH, BIAS, CONFIG, RESULT, ACCUM = range(0, 0x1c, 4)
    INPUT, WEIGHT = 0x1000, 0x2000
    AUDIO_STATUS, AUDIO_DATA, AUDIO_DROPPED, AUDIO_CAPTURED = range(0x8000, 0x8010, 4)
    MAX_LENGTH = 4096

    def __init__(self, mmio, timeout=1.0):
        self.mmio = mmio
        self.timeout = timeout
        self.lock = threading.Lock()

    def _wait(self, completion=False):
        deadline = time.monotonic() + self.timeout
        while True:
            status = self.mmio.read32(self.STATUS)
            if status & 4:
                raise RuntimeError("qn_mac reports invalid command length")
            if not status & 1 and (not completion or status & 2):
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("qn_mac did not finish; check clock/reset and UIO mapping")
            time.sleep(0.00001)

    def dot(self, inputs, weights, bias=0):
        """Return raw signed INT32 dot product, chaining chunks of at most 4096.

        Hardware wraps on INT32 overflow. Callers must choose quantization
        scales/bias and tensor dimensions to prevent overflow when undesired.
        The saturated RESULT register is deliberately not used for chaining.
        """
        inputs, weights = int8_values(inputs), int8_values(weights)
        if len(inputs) != len(weights):
            raise ValueError("inputs and weights must have equal lengths")
        bias = operator.index(bias)
        if not -(1 << 31) <= bias < (1 << 31):
            raise ValueError("bias must fit signed INT32")
        with self.lock:
            # Clear stale errors before checking availability. Clear is valid while busy.
            self.mmio.write32(self.CONTROL, 2)
            self._wait()
            accumulator = bias
            for start in range(0, len(inputs), self.MAX_LENGTH):
                x = inputs[start:start + self.MAX_LENGTH]
                w = weights[start:start + self.MAX_LENGTH]
                for bank, values in ((self.INPUT, x), (self.WEIGHT, w)):
                    for index, word in enumerate(pack_words(values)):
                        self.mmio.write32(bank + 4 * index, word)
                self.mmio.write32(self.LENGTH, len(x))
                self.mmio.write32(self.BIAS, accumulator)
                self.mmio.write32(self.CONFIG, 0)
                self.mmio.write32(self.CONTROL, 1)
                self._wait(completion=True)
                accumulator = signed32(self.mmio.read32(self.ACCUM))
            return accumulator

    def audio_status(self):
        value = self.mmio.read32(self.AUDIO_STATUS)
        return {"count": value & 0x7ff, "empty": bool(value & (1 << 16)),
                "full": bool(value & (1 << 17)), "overflow": bool(value & (1 << 18)),
                "dropped": self.mmio.read32(self.AUDIO_DROPPED),
                "captured": self.mmio.read32(self.AUDIO_CAPTURED)}

    def read_audio(self, maximum=160):
        """Drain available 24-bit signed PCM samples; sole FIFO reader required.

        Overflow is sticky until hardware reset. Service FIFO before 64 ms
        elapses; its 1024 samples represent only 64 ms at 16 kHz.
        """
        if maximum < 0:
            raise ValueError("maximum must be nonnegative")
        with self.lock:
            count = min(maximum, self.audio_status()["count"])
            return [signed32(self.mmio.read32(self.AUDIO_DATA)) for _ in range(count)]


def requantize(accumulator, shift=0, relu=False):
    """Match RTL arithmetic-shift truncation and INT8 saturation; no rounding."""
    if not 0 <= shift <= 31:
        raise ValueError("shift must be 0..31")
    value = signed32(operator.index(accumulator)) >> shift
    return max(0 if relu else -128, min(127, value))


def conv1d(accelerator, inputs, weights, bias=None, stride=1, padding=0,
           dilation=1, groups=1, shift=0, relu=False):
    """Optional NumPy operator harness: C,T input and O,C/groups,K weights.

    Cross-correlation as in PyTorch Conv1d, grouped/depthwise/pointwise support.
    Explicit integer or (left,right) padding; returns signed INT8 O,T output.
    shift may be scalar or per-output-channel. BN must be folded externally.
    This intentionally issues one MMIO dot per output and is very slow.
    """
    import numpy as np
    x, w = np.asarray(inputs), np.asarray(weights)
    if x.ndim != 2 or w.ndim != 3:
        raise ValueError("expected input C,T and weights O,C/groups,K")
    if x.dtype.kind not in "iu" or w.dtype.kind not in "iu":
        raise ValueError("quantized inputs and weights must be integers")
    if np.any(x < -128) or np.any(x > 127) or np.any(w < -128) or np.any(w > 127):
        raise ValueError("input/weight range must be signed INT8")
    channels, length = x.shape
    outputs, channels_group, kernel = w.shape
    if stride < 1 or dilation < 1 or groups < 1 or channels % groups or outputs % groups:
        raise ValueError("invalid stride, dilation or groups")
    if channels_group != channels // groups or kernel < 1:
        raise ValueError("weight shape does not match grouped input")
    left, right = (padding, padding) if isinstance(padding, int) else padding
    if left < 0 or right < 0:
        raise ValueError("padding must be nonnegative")
    biases = [0] * outputs if bias is None else list(bias)
    shifts = [shift] * outputs if isinstance(shift, int) else list(shift)
    if len(biases) != outputs or len(shifts) != outputs:
        raise ValueError("bias/shift must have one entry per output channel")
    out_length = (length + left + right - dilation * (kernel - 1) - 1) // stride + 1
    if out_length < 1:
        raise ValueError("kernel exceeds padded input")
    padded = np.pad(x, ((0, 0), (left, right)))
    result = np.empty((outputs, out_length), dtype=np.int8)
    for oc in range(outputs):
        first = (oc // (outputs // groups)) * channels_group
        for t in range(out_length):
            positions = t * stride + np.arange(kernel) * dilation
            patch = padded[first:first + channels_group, positions].reshape(-1)
            value = accelerator.dot(patch, w[oc].reshape(-1), biases[oc])
            result[oc, t] = requantize(value, shifts[oc], relu)
    return result


def ctc_greedy_decode(token_ids, labels, blank_id):
    """Decode argmax IDs, removing blanks and consecutive repeated IDs.

    For streaming, callers must carry the previous ID across chunks before
    decoding; invoking independently can duplicate a token at the boundary.
    """
    result, previous = [], None
    for token in token_ids:
        token = operator.index(token)
        if token != blank_id and not 0 <= token < len(labels):
            raise ValueError("token ID outside vocabulary")
        if token != previous and token != blank_id:
            result.append(labels[token])
        previous = token
    return "".join(result)


class FakeMMIO:
    """Protocol-level test double, not an RTL simulation or board test."""
    def __init__(self):
        self.registers = {}
        self.lengths = []
        self.results = []

    def read32(self, address):
        return self.registers.get(address, 0)

    def write32(self, address, value):
        value &= 0xffffffff
        self.registers[address] = value
        if address == 0:
            if value & 2:
                self.registers[4] = 0
            if value & 1:
                length = self.registers.get(8, 0)
                if not 1 <= length <= 4096:
                    self.registers[4] = 4
                    return
                self.lengths.append(length)
                total = signed32(self.registers.get(12, 0))
                for i in range(length):
                    values = []
                    for bank in (0x1000, 0x2000):
                        v = (self.registers[bank + (i // 4) * 4] >> ((i % 4) * 8)) & 255
                        values.append(v - 256 if v >= 128 else v)
                    total += values[0] * values[1]
                total = signed32(total)
                self.registers[24] = total & 0xffffffff
                cfg = self.registers.get(16, 0)
                result = requantize(total, cfg & 31, bool(cfg & 256))
                self.registers[20] = result & 0xffffffff
                self.results.append(result)
                self.registers[4] = 2


def selftest():
    mmio = FakeMMIO()
    driver = VoiceAccelerator(mmio)
    for length in (0, 1, 2, 3, 4, 4095, 4096, 4097, 8195):
        x = [((i * 37) % 256) - 128 for i in range(length)]
        w = [((i * 19 + 7) % 256) - 128 for i in range(length)]
        before = len(mmio.lengths)
        expected = signed32(-313 + sum(a * b for a, b in zip(x, w)))
        assert driver.dot(x, w, -313) == expected
        assert mmio.lengths[before:] == [min(4096, length - i) for i in range(0, length, 4096)]
    assert driver.dot([-128, 127, -1], [127, -128, -128]) == -32384
    assert driver.dot([1], [1], 2147483647) == -2147483648
    assert requantize(-3, 1) == -2
    assert requantize(-3, 1, True) == 0
    assert ctc_greedy_decode([0, 0, 2, 0, 1, 1, 2], ["a", "b"], 2) == "aab"
    try:
        import numpy as np
    except ImportError:
        print("PASS: standard-library driver tests; NumPy operator tests skipped")
        return
    for groups, cin, cout, kernel, stride, dilation, padding in (
            (1, 3, 4, 1, 1, 1, 0), (3, 3, 3, 3, 2, 1, (1, 2)),
            (2, 4, 6, 3, 1, 2, 2)):
        x = (np.arange(cin * 11).reshape(cin, 11) % 13 - 6).astype(np.int8)
        w = (np.arange(cout * (cin // groups) * kernel).reshape(cout, cin // groups, kernel) % 7 - 3).astype(np.int8)
        b = list(range(cout))
        actual = conv1d(driver, x, w, b, stride, padding, dilation, groups, 1)
        left, right = (padding, padding) if isinstance(padding, int) else padding
        xp = np.pad(x, ((0, 0), (left, right)))
        expected = np.empty_like(actual)
        for oc in range(cout):
            first = (oc // (cout // groups)) * (cin // groups)
            for t in range(actual.shape[1]):
                total = b[oc]
                for ic in range(cin // groups):
                    for k in range(kernel):
                        total += int(xp[first + ic, t * stride + k * dilation]) * int(w[oc, ic, k])
                expected[oc, t] = requantize(total, 1)
        assert np.array_equal(actual, expected)
    print("PASS: driver chunk/tail/signed tests, grouped/depthwise/pointwise convolution reference")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--device", default="/dev/uio0")
    parser.add_argument("--audio", type=int, default=0, metavar="SAMPLES")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return
    with UIOMMIO(args.device) as mmio:
        driver = VoiceAccelerator(mmio)
        print("Audio:", driver.audio_status())
        print("Signed dot smoke test:", driver.dot([-128, 127, -1], [127, -128, -128]))
        if args.audio:
            print("PCM24:", driver.read_audio(args.audio))


if __name__ == "__main__":
    main()
