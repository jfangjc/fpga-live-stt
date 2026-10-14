"""Copy the pinned frontend arithmetic, omitting only unused output padding."""
import ast
import copy
import hashlib
import textwrap
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
source = ROOT/'software/model-tools/citrinet_cpu.py'
tree = ast.parse(source.read_text())
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Frontend')
method = copy.deepcopy(next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__call__'))
matches = [n for n in method.body if isinstance(n, ast.Assign) and
           len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'features' and
           isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute) and
           isinstance(n.value.func.value, ast.Name) and n.value.func.value.id == 'np' and n.value.func.attr == 'pad']
assert len(matches) == 1
method.body.remove(matches[0])
content = '''"""Private valid-frame frontend for runtimes that immediately crop padding.

All preprocessing arithmetic is copied from the pinned frontend. The output
contains only valid frames; callers must use that explicit input contract.
The original public frontend remains unchanged.
"""
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/model-tools'))
from citrinet_cpu import Frontend

class ValidFrameFrontend(Frontend):
'''+textwrap.indent(ast.unparse(method), '    ')+'\n'
ast.parse(content)
path = ROOT/'software/latency/frontend_valid_frames.py'
if path.exists(): assert path.read_text() == content
else: path.write_text(content, newline='\n')
print('Prepared valid-frame frontend; pinned source SHA256:',hashlib.sha256(source.read_bytes()).hexdigest())
