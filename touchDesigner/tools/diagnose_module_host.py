"""Dumps the state of /project1/module_host and its loaded module.

Run inside TouchDesigner's textport (Alt+T):

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\diagnose_module_host.py').read())

Read-only. Changes nothing.
"""


def show(label, fn):
    try:
        print('  %-26s %s' % (label + ':', fn()))
    except Exception as e:
        print('  %-26s <%s: %s>' % (label + ':', type(e).__name__, e))


h = op('/project1/module_host')
print('=' * 60)
print('HOST', h)

if not h:
    print('  module_host does not exist - run build_module_host.py first')
else:
    show('Status', lambda: h.par.Status.eval())
    show('Moduleactive', lambda: h.par.Moduleactive.eval())
    show('Intensity', lambda: h.par.Intensity.eval())
    show('Outputwidth', lambda: h.par.Outputwidth.eval())
    show('Moduletype', lambda: h.par.Moduletype.eval())
    show('Modulepath', lambda: h.par.Modulepath.eval())

    print('CHAIN')
    show('module_null inputs', lambda: len(h.op('module_null').inputConnectors[0].connections))
    show('module_null res', lambda: '%dx%d' % (h.op('module_null').width, h.op('module_null').height))
    show('out_switch index', lambda: h.op('out_switch').par.index.eval())
    show('out_switch res', lambda: '%dx%d' % (h.op('out_switch').width, h.op('out_switch').height))
    show('host out1 res', lambda: '%dx%d' % (h.op('out1').width, h.op('out1').height))
    show('bypass_src inputs', lambda: len(h.op('bypass_src').inputConnectors[0].connections))

    m = h.op('module')
    print('MODULE', m)
    if m:
        show('children', lambda: [c.name for c in m.children])
        show('outputConnectors', lambda: len(m.outputConnectors))
        show('inputConnectors', lambda: len(m.inputConnectors))
        show('module out1', lambda: m.op('out1'))
        show('module out1 res', lambda: '%dx%d' % (m.op('out1').width, m.op('out1').height))
        show('par Outputwidth', lambda: m.par.Outputwidth.eval())
        show('par Intensity', lambda: m.par.Intensity.eval())
        show('par Paletteindex', lambda: m.par.Paletteindex.eval())
        show('errors', lambda: m.errors() or '(none)')

        b = m.op('render/base')
        print('RENDER/BASE', b)
        if b:
            show('res', lambda: '%dx%d' % (b.width, b.height))
            show('outputresolution', lambda: b.par.outputresolution.eval())
            show('resolutionw expr', lambda: repr(b.par.resolutionw.expr))
            show('resolutionw mode', lambda: b.par.resolutionw.mode)
            show('resolutionw eval', lambda: b.par.resolutionw.eval())
            show('colorr expr', lambda: repr(b.par.colorr.expr))
            show('colorr eval', lambda: b.par.colorr.eval())
            show('colorg eval', lambda: b.par.colorg.eval())
            show('colorb eval', lambda: b.par.colorb.eval())
            show('errors', lambda: b.errors() or '(none)')

        mo = m.op('motion')
        print('MODULE/MOTION', mo)
        if mo:
            show('numChans', lambda: mo.numChans)
            show('channels', lambda: [c.name for c in mo.chans()][:20])
            show('body_level', lambda: mo['body_level'].eval())
print('=' * 60)
