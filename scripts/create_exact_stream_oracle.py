"""Match ARM ORT's float32 requantization before extending hardware coverage."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1];source=ROOT/'software/ort_fpga_stream';dest=ROOT/'software/ort_fpga_stream_exact'
if (dest/'pointwise.cc').exists() and 'qnc_run_stream_reuse' in (dest/'pointwise.cc').read_text():
    raise FileExistsError('Preserved physical stream runtime exists; build its saved sources instead of regenerating the bootstrap oracle')
shutil.copytree(source,dest,dirs_exist_ok=True,ignore=shutil.ignore_patterns('*.o','*.so','__pycache__'))
text=(dest/'pointwise.cc').read_text()
text=text.replace('std::vector<int32_t> bias,mult;', 'std::vector<int32_t> bias,mult;std::vector<float> ratios;')
text=text.replace('bias.assign(data<int32_t>(b),data<int32_t>(b)+m);mult.resize(m);shifts.resize(m);',
                  'bias.assign(data<int32_t>(b),data<int32_t>(b)+m);mult.resize(m);shifts.resize(m);ratios.resize(m);')
text=text.replace('float ratio=(sx*sw[o])/sy;require', 'float ratio=(sx*sw[o])/sy;ratios[o]=ratio;require',1)
text=text.replace('q.mult.resize(256);q.shifts.resize(256);','q.mult.resize(256);q.shifts.resize(256);q.ratios.resize(256);')
needle='float ratio=(sx*sw[o])/sy;require'
text=text.replace(needle,'float ratio=(sx*sw[o])/sy;q.ratios[o]=ratio;require')
start=text.index('  int64_t product=sum*mult[o]');end=text.index('\n }\n};',start)
text=text[:start]+'''  float product=static_cast<float>(sum)*ratios[o];
  product=std::clamp(product,-float(zy),255.f-float(zy));
  return static_cast<uint8_t>(static_cast<int>(std::nearbyint(product))+zy);'''+text[end:]
text=text.replace('prototype.fpga.stream','prototype.fpga.stream.exact')
(dest/'pointwise.cc').write_text(text)
for name in ('pair_graph.py','stream_graph.py'):
    text=(dest/name).read_text().replace('prototype.fpga.stream','prototype.fpga.stream.exact')
    (dest/name).write_text(text)
text=(ROOT/'software/latency/validate_stream_oracle.py').read_text()
text=text.replace('ort_fpga_stream','ort_fpga_stream_exact').replace('from pair_graph import','from pair_graph import').replace('from stream_graph import','from stream_graph import')
text=text.replace("'maximum_logit_difference':", "'all_cpu_logits_bit_exact':bool(np.array_equal(actual,reference)),\n                 'maximum_logit_difference':")
text=text.replace("'all_diagnostic_transcripts_equal':all(r['text_exact'] for r in rows),", "'all_diagnostic_transcripts_equal':all(r['text_exact'] for r in rows),'all_cpu_logits_bit_exact':all(r['all_cpu_logits_bit_exact'] for r in rows),")
(ROOT/'software/latency/validate_exact_stream_oracle.py').write_text(text)
print('Created exact ARM float32 reference; FPGA backend remains gated')
