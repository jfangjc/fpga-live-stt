"""Inspect compiled UINT8 program tensors without requiring local ONNX."""
import argparse,hashlib,json,struct
from pathlib import Path
import numpy as np
ap=argparse.ArgumentParser();ap.add_argument('model',type=Path);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
def fields(data):
    p=0
    def integer():
        nonlocal p
        n=s=0
        while True:
            b=data[p];p+=1;n|=(b&127)<<s
            if b<128:return n
            s+=7;assert s<=63
    while p<len(data):
        key=integer();kind=key&7
        if kind==0:value=integer()
        elif kind==2:
            size=integer();value=data[p:p+size];p+=size
        elif kind in (1,5):
            size=8 if kind==1 else 4;value=data[p:p+size];p+=size
        else:raise ValueError('Unsupported protobuf wire type')
        yield key>>3,value
    assert p==len(data)
model=a.model.read_bytes();graph=next(v for k,v in fields(model) if k==7)
rows=[]
for key,tensor in fields(graph):
    if key!=5:continue
    values=dict(fields(tensor));raw=values.get(9,b'')
    if not raw.startswith(struct.pack('<I',0x314e4843)):continue
    n=struct.unpack_from('<I',raw,4)[0];pos=8
    for stage in range(n):
        kernel=struct.unpack_from('<I',raw,pos)[0];pos+=28+4*256*4
        dw=np.frombuffer(raw,np.int8,count=256*kernel,offset=pos).reshape(256,kernel);pos+=dw.nbytes
        pw=np.frombuffer(raw,np.int8,count=65536,offset=pos).reshape(256,256);pos+=pw.nbytes+260
        rows.append({'program':values[8].decode(),'stage':stage,'kernel':kernel,
                     'dw_zero_weights':int(np.count_nonzero(dw==0)),'dw_weights':int(dw.size),
                     'dw_zero_rows':int(np.count_nonzero(np.all(dw==0,axis=1))),
                     'pw_zero_weights':int(np.count_nonzero(pw==0)),'pw_zero_rows':int(np.count_nonzero(np.all(pw==0,axis=1)))})
    assert pos==len(raw)
assert len(rows)==100
out={'complete':True,'hardware_execution':False,'model_sha256':hashlib.sha256(model).hexdigest(),
     'rows':rows,'dw_zero_weight_fraction':sum(r['dw_zero_weights'] for r in rows)/sum(r['dw_weights'] for r in rows),
     'dw_zero_rows':sum(r['dw_zero_rows'] for r in rows),'pw_zero_rows':sum(r['pw_zero_rows'] for r in rows)}
a.out.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k!='rows'}))
