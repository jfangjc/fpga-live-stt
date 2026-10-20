"""Ensure a failed Vivado route is detected in Windows redirected logs."""
import ast,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
failed=ROOT/'build/branch512_slice166_implement_driver.log'
marker='Chain timing or DRC gate failed'
for variant in ('','_scale','_more','_neon','_maskfast'):
    script=ROOT/f'scripts/qualify_branch512_drop166{variant}.py'
    tree=ast.parse(script.read_text())
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('read_log','timing_failed')]
    assert len(functions)==2
    namespace={}
    exec(compile(ast.Module(body=functions,type_ignores=[]),str(script),'exec'),namespace)
    assert marker in namespace['read_log'](failed),script
    assert namespace['timing_failed'](failed),script
    with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
        path=Path(directory)/'log.txt'
        for encoding in ('utf-8','utf-16'):
            path.write_text(marker,encoding=encoding)
            assert namespace['read_log'](path)==marker,(script,encoding)
            assert namespace['timing_failed'](path),(script,encoding)
            echo='# if {$setup<0.001} {error {Chain timing or DRC gate failed}}\n# file mkdir deployment\nCHAIN_FIRMWARE_EXPORT_COMPLETE\n'
            path.write_text(echo,encoding=encoding)
            assert not namespace['timing_failed'](path),'Successful Tcl echo was falsely rejected'
            path.write_text(echo+'Chain timing or DRC gate failed\n',encoding=encoding)
            assert namespace['timing_failed'](path),'Actual gate failure after echo was missed'
            path.write_text('ERROR: [Common 17-39] Build failed\n',encoding=encoding)
            assert namespace['timing_failed'](path),'Actual tool error was missed'
print('PASS: five watchers detect real failures and accept successful gate echoes in UTF-8/UTF-16')
