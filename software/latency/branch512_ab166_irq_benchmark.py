"""Same qualified graph/library with all four supported CPU IRQ placements."""
from branch512_ab166_neon_maskfast_benchmark import *
from branch512_ab166_neon_maskfast_benchmark import bindings as parent_bindings

def configure(core):
    assert core in (0,1,2,3)
    before=snapshot()
    try:
        for number in before:(Path('/proc/irq')/number/'smp_affinity_list').write_text(str(core))
        after=snapshot()
        assert all(v['effective']==str(core) for v in after.values())
    except BaseException:
        for number,value in before.items():(Path('/proc/irq')/number/'smp_affinity_list').write_text(value['requested'])
        raise
    return {'before':before,'after':after}

def bindings(items):
    return parent_bindings(items)|{'irq_placement_source_sha256':sha(__file__),
                                  'timer_source_sha256':sha(__file__)}
