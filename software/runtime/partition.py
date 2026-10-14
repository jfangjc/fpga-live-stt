"""Generic ONNX partition executor for constant 1x1 Conv + ORT CPU regions.

Experimental: partition overhead is measured, never credited as FPGA speedup.
Only N=1 inputs are supported by accelerated nodes; unsupported Conv stays ORT.
"""
import copy
from collections import Counter
import numpy as np
import onnx
from onnx import helper, numpy_helper
import onnxruntime as ort

def options(threads):
    opt = ort.SessionOptions()
    opt.intra_op_num_threads = threads
    opt.inter_op_num_threads = 1
    opt.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opt.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return opt

class PartitionGraph:
    def __init__(self,path,threads=4,device=None,emulate=False,region_threads=1,fp32_partition=False):
        if threads<1 or (device is None and not emulate):
            raise ValueError('A physical device or explicit numerical emulation is required')
        model = onnx.shape_inference.infer_shapes(onnx.load(str(path)))
        onnx.checker.check_model(model)
        if not 1<=region_threads<=threads: raise ValueError('Region thread count must be in 1..threads')
        self.device,self.emulate,self.fp32_partition = device,emulate,fp32_partition
        initial = {v.name:v for v in model.graph.initializer}
        arrays = {name:numpy_helper.to_array(v) for name,v in initial.items()}
        infos = {v.name:v for v in list(model.graph.input)+list(model.graph.value_info)+list(model.graph.output)}
        nodes = list(model.graph.node)
        self.input_names = [v.name for v in model.graph.input if v.name not in initial]
        self.output_names = [v.name for v in model.graph.output]
        self.uses = Counter(x for n in nodes for x in n.input if x)
        self.uses.update(self.output_names)
        self.steps = []
        self.accelerated_nodes = []
        eligible = {}
        for index,node in enumerate(nodes):
            attrs = {a.name:helper.get_attribute_value(a) for a in node.attribute}
            w = arrays.get(node.input[1]) if node.op_type=='Conv' and len(node.input)>=2 else None
            if (node.domain in ('','ai.onnx') and w is not None and w.dtype==np.float32 and w.ndim==3 and
                w.shape[2]==1 and 1<=w.shape[0]<=1024 and 1<=w.shape[1]<=1024 and
                attrs.get('group',1)==1 and attrs.get('strides',[1])==[1] and
                attrs.get('pads',[0,0])==[0,0] and attrs.get('auto_pad',b'NOTSET') in (b'',b'NOTSET') and
                (len(node.input)<3 or not node.input[2] or node.input[2] in arrays)):
                scale = np.max(np.abs(w[:,:,0]),axis=1).astype(np.float32)/np.float32(127)
                scale[scale==0]=1
                qw = np.clip(np.rint(w[:,:,0]/scale[:,None]),-127,127).astype(np.int8)
                bias = arrays.get(node.input[2]) if len(node.input)>2 else None
                eligible[index]=(qw,scale,bias,w[:,:,0])
        if not eligible: raise ValueError('No supported constant pointwise layers; FPGA would perform no work')
        index=0
        while index<len(nodes):
            if index in eligible:
                node=nodes[index]
                self.steps.append(('fpga',node,eligible[index]))
                self.accelerated_nodes.append(node.name or node.output[0])
                index+=1
                continue
            end=index+1
            while end<len(nodes) and end not in eligible: end+=1
            subset=nodes[index:end]
            produced={x for n in subset for x in n.output}
            required={x for n in subset for x in n.input if x}
            external=sorted(required-produced-set(initial))
            later={x for n in nodes[end:] for x in n.input}|set(self.output_names)
            outputs=sorted(produced&later)
            if not outputs: index=end; continue
            for name in external+outputs:
                if name not in infos: raise ValueError('Missing inferred ONNX type/shape: '+name)
            graph=helper.make_graph(copy.deepcopy(subset),'cpu_region_'+str(index),
                  [copy.deepcopy(infos[n]) for n in external], [copy.deepcopy(infos[n]) for n in outputs],
                  [copy.deepcopy(initial[n]) for n in sorted(required&set(initial))])
            region=helper.make_model(graph,opset_imports=list(model.opset_import)); region.ir_version=model.ir_version
            onnx.checker.check_model(region)
            # Tiny independent regions must not each spawn a full board thread pool.
            # The complete CPU baseline retains the explicit full thread setting.
            opt=options(region_threads)
            # Independent resident regions would otherwise keep many CPU arenas.
            opt.enable_cpu_mem_arena=False
            opt.enable_mem_pattern=False
            session=ort.InferenceSession(region.SerializeToString(),opt,providers=['CPUExecutionProvider'])
            self.steps.append(('cpu',session,(external,outputs)))
            index=end
        self.last_profile=[]
        self.live_after=[]
        live=set(self.output_names)
        for kind,op,data in reversed(self.steps):
            self.live_after.append(live.copy())
            if kind=='cpu': inputs,outputs=data
            else: inputs,outputs=[op.input[0]],[op.output[0]]
            live.difference_update(outputs); live.update(inputs)
        self.live_after.reverse()

    def run(self,feed):
        import time
        values=dict(feed)
        if set(values)!=set(self.input_names): raise ValueError('Unexpected graph feeds')
        profile=[]
        for kind,op,data in self.steps:
            start=time.perf_counter()
            if kind=='cpu':
                inputs,outputs=data
                result=op.run(outputs,{name:values[name] for name in inputs})
                values.update(zip(outputs,result))
            else:
                qw,scale,bias,w=data
                x=values[op.input[0]]
                if x.dtype!=np.float32 or x.ndim!=3 or x.shape[0]!=1 or x.shape[1]!=qw.shape[1]:
                    raise ValueError('Accelerated Conv requires FP32 [1,K,T]')
                x=np.ascontiguousarray(x[0])
                # Native qnc_run_f32 already scans finite values while finding scale.
                if (self.emulate or self.fp32_partition) and not np.all(np.isfinite(x)):
                    raise ValueError('Nonfinite activation')
                if self.fp32_partition:
                    y=w@x
                elif self.emulate:
                    act=np.float32(np.max(np.abs(x))/np.float32(127))
                    if act==0: act=np.float32(1)
                    qx=np.clip(np.rint(x/act),-127,127).astype(np.int8)
                    y=(qw.astype(np.int32)@qx.astype(np.int32)).astype(np.float32)*(scale*act)[:,None]
                else:
                    self.device.load(qw)
                    y=self.device.run_float(x,scale)
                if bias is not None: y=y+bias[:,None]
                values[op.output[0]]=y[None]
            profile.append({'kind':kind,'seconds':time.perf_counter()-start})
            # Release intermediate arrays as soon as no future region consumes them.
            next_uses=self.live_after[len(profile)-1]
            for name in list(values):
                if name not in next_uses: del values[name]
        self.last_profile=profile
        return [values[name] for name in self.output_names]
