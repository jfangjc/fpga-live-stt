"""Eliminate exact duplicate constants and pure metadata/mask calculations."""
import argparse
import collections
import copy
import hashlib
import json
from pathlib import Path
import onnx
from onnx import helper, numpy_helper
from share_shape_metadata import rewrite, sha, ROOT

PURE = {'Constant','Shape','Gather','Range','Unsqueeze','Squeeze','Slice',
        'GreaterOrEqual','Greater','Less','LessOrEqual','Equal','Not','And','Or',
        'Cast','Where','Expand','Concat','Identity','Transpose',
        'QuantizeLinear','DequantizeLinear','Relu'}

def tensor_key(tensor):
    if tensor.data_type == onnx.TensorProto.STRING:
        return tensor.data_type, tuple(tensor.dims), tuple(tensor.string_data)
    array = numpy_helper.to_array(tensor)
    return tensor.data_type, tuple(tensor.dims), hashlib.sha256(array.tobytes()).digest()

def attributes_key(node):
    result = []
    for attr in sorted(node.attribute, key=lambda a:a.name):
        attr = copy.deepcopy(attr)
        if attr.type == onnx.AttributeProto.TENSOR:
            # Tensor names and doc strings do not affect Constant's value.
            result.append((attr.name, attr.type, tensor_key(attr.t)))
        else:
            result.append((attr.name, attr.type, attr.SerializeToString()))
    return tuple(result)

def eliminate(model):
    model = copy.deepcopy(model)
    aliases = {}; seen = {}; constants = {}; changes = []
    input_names = {v.name for v in model.graph.input}
    kept = []
    for tensor in model.graph.initializer:
        key = tensor_key(tensor)
        if tensor.name not in input_names and key in constants:
            aliases[tensor.name] = constants[key]
            changes.append({'kind':'initializer','removed':tensor.name,'canonical':constants[key]})
        else:
            kept.append(tensor)
            if tensor.name not in input_names: constants[key] = tensor.name
    del model.graph.initializer[:]; model.graph.initializer.extend(kept)
    kept = []
    for node in model.graph.node:
        for i,name in enumerate(node.input): node.input[i] = aliases.get(name,name)
        key = (node.domain, node.op_type, tuple(node.input), attributes_key(node))
        if node.domain in ('','ai.onnx') and node.op_type in PURE and key in seen:
            previous = seen[key]
            assert len(node.output) == len(previous.output)
            for old,new in zip(node.output,previous.output):
                if old: aliases[old] = new
            changes.append({'kind':'node','removed':node.name,'operator':node.op_type,
                            'canonical':previous.name,'outputs':dict(zip(node.output,previous.output))})
        else:
            kept.append(node)
            if node.domain in ('','ai.onnx') and node.op_type in PURE: seen[key] = node
    for output in model.graph.output:
        if output.name in aliases:
            kept.append(helper.make_node('Identity',[aliases[output.name]],[output.name],
                                         name=output.name+'_preserve_output'))
    del model.graph.node[:]; model.graph.node.extend(kept)
    infos = [v for v in model.graph.value_info if v.name not in aliases]
    del model.graph.value_info[:]; model.graph.value_info.extend(infos)
    onnx.checker.check_model(model)
    return model, changes

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model',type=Path,default=ROOT/'research/fused/cpu-int8.onnx')
    ap.add_argument('--out',type=Path,default=ROOT/'research/fused/cpu-int8-cse.onnx')
    a=ap.parse_args()
    original=onnx.load(str(a.model))
    shared,shape_changes=rewrite(original)
    result,changes=eliminate(shared)
    a.out.parent.mkdir(parents=True,exist_ok=True);onnx.save(result,str(a.out))
    proof=json.loads(a.model.with_suffix('.json').read_text())
    assert proof['model_sha256']==sha(a.model)
    proof.update(model_sha256=sha(a.out),parent_model_sha256=sha(a.model),
                 transformation='Proved Shape input sharing then exact common-subexpression elimination of pure metadata/mask nodes and constants',
                 transform_source_sha256=sha(Path(__file__)),
                 shape_proof_source_sha256=sha(Path(__file__).with_name('share_shape_metadata.py')),
                 metadata_input_changes=shape_changes,duplicate_eliminations=changes,
                 numerical_arithmetic_changed=False,physical_performance_validated=False)
    a.out.with_suffix('.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps({'original_nodes':len(original.graph.node),'new_nodes':len(result.graph.node),
                      'removed':dict(collections.Counter(v.get('operator',v['kind']) for v in changes)),
                      'original_initializers':len(original.graph.initializer),'new_initializers':len(result.graph.initializer)}))

if __name__=='__main__':main()
