"""Builds and exports the stub base_scene test module.

Run inside TouchDesigner's textport (Alt+T):

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_stub_module.py').read())

Writes module.tox next to module.json. The module is a flat colour driven by
three motion lanes; it exists to exercise the module host, not to look good.
Contract: docs/SCENE_MODULE_SPEC.md sections 6, 9 and 10.1.
"""

import os

MODULE_DIR = (r'C:\Users\ljlco\source\repos\CodexProjects'
              r'\ReactiveVisualEngineCode\touchDesigner\modules\stub_scene')
TOX = os.path.join(MODULE_DIR, 'module.tox')

ROOT = op('/project1')
BUILD = '_stub_build'

old = ROOT.op(BUILD)
if old:
    old.destroy()

stub = ROOT.create(baseCOMP, BUILD)
stub.nodeX, stub.nodeY = 6400, -1200

# Parameters are created before any operator references them: an expression
# assigned against a parameter that does not exist yet does not resolve.

# ------------------------------------------------------ standard parameters
std = stub.appendCustomPage('DeckGlow')

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

# --------------------------------------------------- base_scene parameters
scene = stub.appendCustomPage('Scene')

for name in ('Motionamount', 'Textureamount', 'Toneamount'):
    p = scene.appendFloat(name)[0]
    p.default = 1
    p.normMin, p.normMax = 0, 1
    p.val = 1

p = scene.appendInt('Paletteindex')[0]
p.default = 0
p.min = 0
p.clampMin = True
p.val = 0


def lane(name):
    """Safe lane read: 0 when the motion input is absent (spec s12.2)."""
    m = "op('../motion')"
    return "({0}.chan('{1}').eval() if {0}.chan('{1}') else 0)".format(m, name)


# ------------------------------------------------------- required operators
mot_in = stub.create(inCHOP, 'in0_motion')
mot_in.nodeX, mot_in.nodeY = 0, 0

pal_in = stub.create(inDAT, 'in1_palette')
pal_in.nodeX, pal_in.nodeY = 0, -200

motion = stub.create(nullCHOP, 'motion')
motion.nodeX, motion.nodeY = 300, 0
motion.inputConnectors[0].connect(mot_in)

render = stub.create(baseCOMP, 'render')
render.nodeX, render.nodeY = 700, 0

base = render.create(constantTOP, 'base')
base.nodeX, base.nodeY = 0, 0
base.par.outputresolution = 'custom'
# Honour the runtime's requested size exactly. The global res multiplier
# (Edit > Preferences > TOPs) would otherwise silently rescale out1 and make
# the validator's resolution check meaningless (spec s14, s15.4).
base.par.resmult = False
base.par.resolutionw.expr = 'parent(2).par.Outputwidth'
base.par.resolutionh.expr = 'parent(2).par.Outputheight'
base.par.colorr.expr = lane('body_level') + ' * parent(2).par.Intensity'
base.par.colorg.expr = (lane('sync_phase')
                        + ' * parent(2).par.Motionamount * parent(2).par.Intensity')
base.par.colorb.expr = (lane('texture_level')
                        + ' * parent(2).par.Textureamount * parent(2).par.Intensity')
base.par.alpha = 1

rout = render.create(outTOP, 'out1')
rout.nodeX, rout.nodeY = 400, 0
rout.inputConnectors[0].connect(base)

out1 = stub.create(outTOP, 'out1')
out1.nodeX, out1.nodeY = 1100, 0
# a COMP is not a valid source; connect to its output connector
out1.inputConnectors[0].connect(render.outputConnectors[0])

# ------------------------------------------------------------------ export
if not os.path.isdir(MODULE_DIR):
    os.makedirs(MODULE_DIR)

stub.save(TOX)

if os.path.isfile(TOX):
    print('wrote', TOX, os.path.getsize(TOX), 'bytes')
    try:
        # force a cook first: width/height read stale before the TOP cooks
        base.cook(force=True)
        out1.cook(force=True)
        print('base resolution:', base.width, 'x', base.height)
        print('module out1:', out1.width, 'x', out1.height)
    except Exception as e:
        print('(resolution check unavailable: %s)' % e)
    stub.destroy()
    print('build COMP removed; /project1 is clean')
else:
    print('SAVE FAILED - leaving', stub.path, 'in place for inspection')
