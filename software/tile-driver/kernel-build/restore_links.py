from pathlib import Path
import json,os
root=Path(__file__).parent/'sysroot'
for name,dest,sym in json.loads((root.parent/'header_links.json').read_text()):
 p=root/name
 if not p.exists() and not p.is_symlink():
  p.parent.mkdir(parents=True,exist_ok=True)
  if sym: p.symlink_to(dest)
  else: os.link(root/dest,p)
print('Links restored')
