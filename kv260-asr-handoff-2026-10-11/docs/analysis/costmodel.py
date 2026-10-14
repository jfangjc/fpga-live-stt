"""Per-layer MAC / weight / activation cost model for Citrinet-256 and QuartzNet 5x5/15x5.
Parses the Citrinet jasper list from the checkpoint YAML with a tiny hand parser (no PyYAML)."""
import re, sys, math, json

def parse_citrinet(path):
    txt = open(path).read()
    enc = txt.split("encoder:")[1].split("decoder:")[0]
    feat_in = int(re.search(r"feat_in:\s*(\d+)", enc).group(1))
    blocks = []
    for chunk in enc.split("  - filters:")[1:]:
        f = int(chunk.split()[0])
        rep = int(re.search(r"repeat:\s*(\d+)", chunk).group(1))
        k = int(re.search(r"kernel:\s*\n\s*-\s*(\d+)", chunk).group(1))
        s = int(re.search(r"stride:\s*\n\s*-\s*(\d+)", chunk).group(1))
        res = "residual: true" in chunk
        se = "se: true" in chunk
        blocks.append(dict(filters=f, repeat=rep, kernel=k, stride=s, residual=res, se=se,
                           stride_last="stride_last: true" in chunk))
    dec = txt.split("decoder:")[1]
    dec_in = int(re.search(r"feat_in:\s*(\d+)", dec).group(1))
    ncls = int(re.search(r"num_classes:\s*(\d+)", dec).group(1)) + 1  # + blank
    return feat_in, blocks, dec_in, ncls

def citrinet_layers(feat_in, blocks, dec_in, ncls, fps=100.0, se_ratio=8):
    L = []  # (name, kind, macs_per_s, weights, out_fps, cin, cout, k)
    cin = feat_in; rate = fps
    for bi, b in enumerate(blocks):
        c_block_in = cin; rate_in = rate
        for r in range(b["repeat"]):
            last = r == b["repeat"] - 1
            s = b["stride"] if (last or not b["stride_last"]) else 1
            if b["stride_last"] and not last: s = 1
            rate_out = rate / s
            L.append((f"b{bi}.r{r}.dw", "dw", b["kernel"] * cin * rate_out, b["kernel"] * cin, rate_out, cin, cin, b["kernel"]))
            L.append((f"b{bi}.r{r}.pw", "pw", cin * b["filters"] * rate_out, cin * b["filters"] + b["filters"], rate_out, cin, b["filters"], 1))
            cin = b["filters"]; rate = rate_out
        if b["se"]:
            C = b["filters"]; h = C // se_ratio
            # FC1 + FC2 once per window; scale multiply per frame per channel
            L.append((f"b{bi}.se", "se", C * rate, 2 * C * h + h + C, rate, C, C, 0))
        if b["residual"]:
            L.append((f"b{bi}.res", "pw_res", c_block_in * b["filters"] * rate, c_block_in * b["filters"] + b["filters"], rate, c_block_in, b["filters"], 1))
    L.append(("decoder", "pw", dec_in * ncls * rate, dec_in * ncls + ncls, rate, dec_in, ncls, 1))
    return L

def quartznet_layers(B, fps=100.0, feat_in=64, ncls=29):
    # NeMo QuartzNet BxR (R=5): C1 sep k33 s2 256; B1..B5 (256,33)(256,39)(512,51)(512,63)(512,75) each repeated B/5 times;
    # C2 sep k87 d2 512; C3 1x1 1024; decoder 1x1 ncls. Residual 1x1 per block.
    L = []; rate = fps / 2
    L.append(("C1.dw", "dw", 33 * feat_in * rate, 33 * feat_in, rate, feat_in, feat_in, 33))
    L.append(("C1.pw", "pw", feat_in * 256 * rate, feat_in * 256, rate, feat_in, 256, 1))
    cin = 256
    spec = [(256, 33), (256, 39), (512, 51), (512, 63), (512, 75)]
    rep_b = B // 5
    for gi, (f, k) in enumerate(spec):
        for rb in range(rep_b):
            c0 = cin
            for r in range(5):
                L.append((f"B{gi+1}.{rb}.r{r}.dw", "dw", k * cin * rate, k * cin, rate, cin, cin, k))
                L.append((f"B{gi+1}.{rb}.r{r}.pw", "pw", cin * f * rate, cin * f, rate, cin, f, 1))
                cin = f
            L.append((f"B{gi+1}.{rb}.res", "pw_res", c0 * f * rate, c0 * f, rate, c0, f, 1))
    L.append(("C2.dw", "dw", 87 * cin * rate, 87 * cin, rate, cin, cin, 87))
    L.append(("C2.pw", "pw", cin * 512 * rate, cin * 512, rate, cin, 512, 1)); cin = 512
    L.append(("C3", "pw", cin * 1024 * rate, cin * 1024, rate, cin, 1024, 1))
    L.append(("decoder", "pw", 1024 * ncls * rate, 1024 * ncls + ncls, rate, 1024, ncls, 1))
    return L

def summarise(name, L):
    tot = sum(x[2] for x in L); w = sum(x[3] for x in L)
    by = {}
    for x in L: by[x[1]] = by.get(x[1], 0) + x[2]
    maxw = max(x[3] for x in L)
    out = dict(model=name, layers=len(L), macs_per_s=tot, weights=w,
               frac={k: v / tot for k, v in by.items()}, max_layer_weights=maxw)
    return out

if __name__ == "__main__":
    cfg = sys.argv[1]
    fi, blocks, dec_in, ncls = parse_citrinet(cfg)
    C = citrinet_layers(fi, blocks, dec_in, ncls)
    res = [summarise("citrinet-256", C), summarise("quartznet-5x5", quartznet_layers(5)), summarise("quartznet-15x5", quartznet_layers(15))]
    for r in res: print(json.dumps(r, indent=1))
    # Cross-check against MODEL_SELECTION.md: 1008 padded frames -> 2.732405760e9 conv MACs, 2.572303104e9 pointwise
    T = 1008 / 100.0
    conv = sum(x[2] for x in C if x[1] in ("dw", "pw", "pw_res")) * T
    pw = sum(x[2] for x in C if x[1] in ("pw", "pw_res")) * T
    print("citrinet conv MACs @1008 frames:", conv, "pointwise:", pw, "pw frac", pw / conv)
    print("dw count", sum(1 for x in C if x[1] == "dw"), "pw count", sum(1 for x in C if x[1] in ("pw", "pw_res")), "se", sum(1 for x in C if x[1] == "se"))
    # per-block summary for Citrinet, for one 2.56 s window (256 frames)
    W = 2.56
    print("\nblock, fps_out, MACs/window(2.56s), int8 weight bytes, act bytes in (int8, C*T)")
    blk = {}
    for x in C:
        b = x[0].split(".")[0]
        d = blk.setdefault(b, [0, 0, 0, 0])
        d[0] += x[2] * W; d[1] += x[3]; d[2] = x[4]; d[3] = max(d[3], x[5] * x[4] * W)
    for b, d in blk.items(): print(f"{b:8s} {d[2]:6.1f} {d[0]/1e6:9.2f}M {d[1]/1e3:8.1f}K {d[3]/1e3:7.1f}K")
    json.dump([list(x) for x in C], open(sys.argv[2], "w"))
