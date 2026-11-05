"""Builds /project1/module_host, the Block 2 scene-module wrapper.

Run inside TouchDesigner's textport (Alt+T):

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_module_host.py').read())

Re-running destroys and rebuilds the COMP, so it is safe to run repeatedly.
Contract: docs/SCENE_MODULE_SPEC.md sections 9 (standard parameters),
10 (slot connector order) and 12 (lifecycle).
"""

ROOT = op('/project1')
NAME = 'module_host'

existing = ROOT.op(NAME)
if existing:
    existing.destroy()

host = ROOT.create(baseCOMP, NAME)
host.nodeX, host.nodeY = 6400, 0
host.nodeWidth, host.nodeHeight = 900, 300

# ---------------------------------------------------------------- inputs
ins = [
    ('in0_image', inTOP),
    ('in1_motion', inCHOP),
    ('in2_palette', inDAT),
    ('in3_brand', inDAT),
    ('in4_logo', inTOP),
]
for i, (nm, kind) in enumerate(ins):
    o = host.create(kind, nm)
    o.nodeX, o.nodeY = 0, -i * 200

black = host.create(constantTOP, 'black')
black.par.color = (0, 0, 0)
black.par.alpha = 1
black.nodeX, black.nodeY = 400, -1200

bypass_src = host.create(nullTOP, 'bypass_src')
bypass_src.nodeX, bypass_src.nodeY = 800, -1000

module_null = host.create(nullTOP, 'module_null')
module_null.nodeX, module_null.nodeY = 800, 0

out_switch = host.create(switchTOP, 'out_switch')
out_switch.nodeX, out_switch.nodeY = 1200, -400
out_switch.inputConnectors[0].connect(module_null)
out_switch.inputConnectors[1].connect(bypass_src)

out1 = host.create(outTOP, 'out1')
out1.nodeX, out1.nodeY = 1600, -400
out1.inputConnectors[0].connect(out_switch)

# ------------------------------------------------------------ parameters
page = host.appendCustomPage('Module')

p = page.appendFile('Modulepath')[0]
p.default = ''

p = page.appendMenu('Moduletype')[0]
p.menuNames = ['base_scene', 'hit_fx', 'brand_overlay', 'finish_fx']
p.menuLabels = ['Base Scene', 'Hit FX', 'Brand Overlay', 'Finish FX']
p.default = 'base_scene'

page.appendPulse('Load')
page.appendPulse('Unload')

p = page.appendStr('Status')[0]
p.default = 'empty'
p.val = 'empty'

std = host.appendCustomPage('DeckGlow')

p = std.appendToggle('Moduleactive')[0]
p.default = 1
p.val = 1

p = std.appendFloat('Intensity')[0]
p.default = 1
p.normMin, p.normMax = 0, 1
p.val = 1

p = std.appendInt('Seed')[0]
p.default = 1
p.val = 1

std.appendPulse('Reset')

p = std.appendInt('Outputwidth')[0]
p.default = 1920
p.val = 1920

p = std.appendInt('Outputheight')[0]
p.default = 1080
p.val = 1080

# ----------------------------------------------------------------- logic
logic = host.create(textDAT, 'host')
logic.nodeX, logic.nodeY = 0, -1600
logic.text = '''
# Lifecycle for the scene-module wrapper. See docs/SCENE_MODULE_SPEC.md s12.

WIRING = {
    'base_scene':    ['in1_motion', 'in2_palette'],
    'hit_fx':        ['in0_image', 'in1_motion', 'in2_palette'],
    'brand_overlay': ['in0_image', 'in1_motion', 'in3_brand', 'in4_logo'],
    'finish_fx':     ['in0_image', 'in1_motion'],
}

STANDARD = ['Moduleactive', 'Intensity', 'Seed', 'Outputwidth', 'Outputheight']


def _host():
    return parent()


def _status(text):
    _host().par.Status = text


def Module():
    return _host().op('module')


def Unload():
    m = Module()
    if m:
        m.destroy()
    _host().op('module_null').inputConnectors[0].disconnect()
    _status('empty')
    Refresh()


def Load():
    h = _host()
    path = h.par.Modulepath.eval().strip()
    if not path:
        _status('error: no Modulepath set')
        return

    Unload()

    m = h.create(baseCOMP, 'module')
    m.nodeX, m.nodeY = 400, 0
    try:
        m.loadTox(path)
    except Exception as e:
        m.destroy()
        _status('error: load failed - %s' % e)
        Refresh()
        return

    mtype = h.par.Moduletype.eval()
    for index, srcname in enumerate(WIRING.get(mtype, [])):
        src = h.op(srcname)
        if src and index < len(m.inputConnectors):
            m.inputConnectors[index].connect(src)

    Apply()

    if hasattr(m.par, 'Reset'):
        m.par.Reset.pulse()

    h.op('module_null').inputConnectors[0].connect(m)
    Refresh()
    _status(Validate())


def Apply():
    h = _host()
    m = Module()
    if not m:
        return
    for name in STANDARD:
        target = getattr(m.par, name, None)
        if target is not None:
            target.val = getattr(h.par, name).eval()


def Reset():
    m = Module()
    if m and hasattr(m.par, 'Reset'):
        m.par.Reset.pulse()


def Refresh():
    """Point the bypass source at the right fallback and set the switch."""
    h = _host()
    mtype = h.par.Moduletype.eval()
    src = h.op('black') if mtype == 'base_scene' else h.op('in0_image')
    bp = h.op('bypass_src')
    bp.inputConnectors[0].disconnect()
    bp.inputConnectors[0].connect(src)

    live = bool(Module()) and bool(h.par.Moduleactive.eval())
    h.op('out_switch').par.index = 0 if live else 1


def Validate():
    m = Module()
    if not m:
        return 'error: module did not load'
    out = m.op('out1')
    if out is None:
        return 'error: module has no out1'
    if out.family != 'TOP':
        return 'error: out1 is %s, expected TOP' % out.family
    missing = [n for n in STANDARD if getattr(m.par, n, None) is None]
    if missing:
        return 'warn: loaded, missing pars %s' % ','.join(missing)
    return 'ok: %dx%d' % (out.width, out.height)


def OnPulse(par):
    if par.name == 'Load':
        Load()
    elif par.name == 'Unload':
        Unload()
    elif par.name == 'Reset':
        Reset()


def OnValueChange(par):
    if par.name in STANDARD:
        Apply()
    if par.name in ('Moduleactive', 'Moduletype'):
        Refresh()
'''

pe = host.create(parameterexecuteDAT, 'host_parexec')
pe.nodeX, pe.nodeY = 400, -1600
pe.par.op = host
pe.par.pars = '*'
pe.par.custom = True
pe.par.builtin = False
pe.par.valuechange = True
pe.par.onpulse = True
pe.par.active = True
pe.text = '''
def onValueChange(par, prev):
    op('host').module.OnValueChange(par)
    return

def onPulse(par):
    op('host').module.OnPulse(par)
    return
'''

# --------------------------------------------------------- host wiring
motion = ROOT.op('MOTION_OUT')
if motion:
    host.inputConnectors[1].connect(motion)

host.op('host').module.Refresh()

print('module_host built at', host.path)
print('inputs:', [c.name for c in host.inputConnectors])
print('status:', host.par.Status.eval())
