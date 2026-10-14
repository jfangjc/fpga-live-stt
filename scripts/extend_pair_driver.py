"""Generate the isolated pair driver from the frozen accepted transport."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
s = (root/'deployment/experimental-bulk/qn_tile.c').read_text()
def replace(a,b):
    global s
    assert a in s, a
    s = s.replace(a,b)
replace('bool removed, poisoned, cache_quant, needs_rebind;',
        'bool removed, poisoned, cache_quant, needs_rebind, dw_valid;')
replace('q->cache_owner = NULL;', 'q->cache_owner = NULL;\n\tq->dw_valid = false;')
# The release path now needs braces; its ownership guard must cover both writes.
replace('if (q->cache_owner == file)\n\t\tq->cache_owner = NULL;\n\tq->dw_valid = false;',
        'if (q->cache_owner == file) {\n\t\tq->cache_owner = NULL;\n\t\tq->dw_valid = false;\n\t}')
replace('(layer_op == QN_LAYER_RUN || layer_op == QN_LAYER_RUN_QUANT || layer_op == QN_LAYER_RUN_BULK)',
        '(layer_op == QN_LAYER_RUN || layer_op == QN_LAYER_RUN_QUANT || layer_op == QN_LAYER_RUN_BULK || layer_op == 8)')
replace('(layer_op == QN_LAYER_RUN_QUANT || layer_op == QN_LAYER_RUN_BULK)',
        '(layer_op == QN_LAYER_RUN_QUANT || layer_op == QN_LAYER_RUN_BULK || layer_op == 8)')
replace('if (layer_op != QN_LAYER_RUN && layer_op != QN_LAYER_RUN_QUANT && layer_op != QN_LAYER_RUN_BULK)\n\t\t\tq->cache_owner = NULL;\n\tq->dw_valid = false;',
        '''if ((layer_op == 7 && (q->cache_owner != file || !q->cache_quant ||
            q->cache_tag != layer_tag || q->cache_k != layer_k)) ||
            (layer_op == 8 && !q->dw_valid)) {
            ret = -ESTALE;
            goto unlock;
        }
        if (layer_op == 7) q->dw_valid = false;
        if (layer_op != QN_LAYER_RUN && layer_op != QN_LAYER_RUN_QUANT &&
            layer_op != QN_LAYER_RUN_BULK && layer_op != 7 && layer_op != 8) {
            q->cache_owner = NULL;
            q->dw_valid = false;
        }''')
# Fix the uncached guard expanded above (the original guard has no braces).
replace('if (!cached)\n\t\tq->cache_owner = NULL;\n\tq->dw_valid = false;',
        'if (!cached) {\n\t\tq->cache_owner = NULL;\n\t\tq->dw_valid = false;\n\t}')
replace('if (layer_op == QN_LAYER_LOAD || layer_op == QN_LAYER_LOAD_QUANT) {',
        'if (layer_op == 7) q->dw_valid = true;\n\t\tif (layer_op == QN_LAYER_LOAD || layer_op == QN_LAYER_LOAD_QUANT) {')
s += '\nstatic unsigned int pair_protocol = 1;\nmodule_param(pair_protocol, uint, 0444);\n'
(root/'deployment/experimental-pair/qn_tile.c').write_text(s, encoding='utf-8')
