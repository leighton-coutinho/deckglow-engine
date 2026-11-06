"""Dumps the state of each module host (module_host, hit_host, brand_host) and its module.

Run inside TouchDesigner's textport (Alt+T):

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\diagnose_module_host.py').read())

Read-only. Changes nothing.
"""

HOSTS = ['module_host', 'hit_host', 'brand_host']


def show(label, fn):
    try:
        print('  %-26s %s' % (label + ':', fn()))
    except Exception as e:
        print('  %-26s <%s: %s>' % (label + ':', type(e).__name__, e))


def dump(name):
    h = op('/project1/' + name)
    print('=' * 60)
    print('HOST', name, h)
    if not h:
        print('  %s does not exist - run build_module_host.py first' % name)
        return

    show('Status', lambda: h.par.Status.eval())
    show('Moduletype', lambda: h.par.Moduletype.eval())
    show('Modulepath', lambda: h.par.Modulepath.eval())
    show('Moduleactive', lambda: h.par.Moduleactive.eval())
    show('Intensity', lambda: h.par.Intensity.eval())
    show('Outputwidth', lambda: h.par.Outputwidth.eval())

    print('CHAIN')
    show('image input from', lambda: [c.owner.name for c in h.inputConnectors[0].connections] or '(none)')
    show('in0_image res', lambda: '%dx%d' % (h.op('in0_image').width, h.op('in0_image').height))
    show('module_null inputs', lambda: len(h.op('module_null').inputConnectors[0].connections))
    show('out_switch index', lambda: h.op('out_switch').par.index.eval())
    show('host out1 res', lambda: '%dx%d' % (h.op('out1').width, h.op('out1').height))
    show('bypass_src from', lambda: [c.owner.name for c in h.op('bypass_src').inputConnectors[0].connections])

    m = h.op('module')
    print('MODULE', m)
    if not m:
        return
    show('children', lambda: [c.name for c in m.children])
    show('inputConnectors', lambda: len(m.inputConnectors))
    show('module out1 res', lambda: '%dx%d' % (m.op('out1').width, m.op('out1').height))
    show('errors', lambda: m.errors(recurse=True) or '(none)')

    mo = m.op('motion')
    if mo:
        show('motion channels', lambda: mo.numChans)
        show('impact_trigger', lambda: mo['impact_trigger'].eval())
        show('impact_fast', lambda: mo['impact_fast'].eval())

    # orb_burst specifics
    orbs = m.op('render/orbs')
    if orbs:
        show('orbs alive', lambda: orbs.module.Alive())
        show('orb_fx errors', lambda: m.op('render/orb_fx').errors() or '(none)')
        show('out_switch (0=fx 1=pass)', lambda: m.op('render/out_switch').par.index.eval())

    # clean_lockup specifics
    lay = m.op('render/layout')
    if lay:
        try:
            L = lay.module.Layout()
        except Exception as e:
            L = {}
            print('  layout failed: %s: %s' % (type(e).__name__, e))
        show('brand displayName', lambda: repr(lay.module.Brand('displayName', '')))
        show('mode (after fallback)', lambda: L['mode'])
        show('logo present', lambda: lay.module.LogoPresent())
        show('logo rect', lambda: tuple(round(v, 3) for v in L['logo']))
        show('name rect', lambda: tuple(round(v, 3) for v in L['name']))
        show('lockup_fx errors', lambda: m.op('render/lockup_fx').errors() or '(none)')
        show('out_switch (0=shown 1=pass)', lambda: m.op('render/out_switch').par.index.eval())


for n in HOSTS:
    dump(n)
print('=' * 60)
