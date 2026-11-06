"""Builds and exports the kinetic_stripes base_scene module (Block 3).

Run inside TouchDesigner's textport (Alt+T), with engine_input_block1.toe open:

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_kinetic_stripes.py').read())

Writes modules/kinetic_stripes/module.tox and thumbnail.png next to
module.json. Paths derive from project.folder, so the .toe must be the one in
touchDesigner/.

This is the stripes look from ReactiveVisualsTouchDesignerProtoOsc.8.toe moved
behind the base_scene contract. Only the branch that actually rendered there is
ported: in the saved proto, comp1 and feedback1 are bypassed and level1 is
locked, so the feedback trails and the mid/high-driven noise never reached the
screen. The locked level1 image is recovered as assets/stripe_lookup.png and
re-locked inside the module, so the .tox depends on no external file.

Signal mapping, raw OSC -> motion lane:

    bass       ramp phase (stripe slide)   -> body_level
    onset      flash brightness 0.75..2    -> impact_fast
    bar pulse  zoom 1..2 (0.6 s release)   -> sync_bar_env
    kick       zoom 1..1.12                -> impact_wide
    beat sin   x drift +-0.03              -> sync_sine

At idle (all lanes 0) it renders static stripes at 0.75 brightness.

The build finishes in two deferred stages (TouchDesigner initialises
asynchronously - see CLAUDE.md): the lookup image must load before it can be
locked, and must still be there after its file path is cleared.

Contract: docs/SCENE_MODULE_SPEC.md sections 6, 9, 10.1, 11 and 12.
"""

import os

MODULE_DIR = os.path.join(project.folder, 'modules', 'kinetic_stripes')
TOX = os.path.join(MODULE_DIR, 'module.tox')
THUMB = os.path.join(MODULE_DIR, 'thumbnail.png')
LOOKUP_PNG = os.path.join(MODULE_DIR, 'assets', 'stripe_lookup.png')

if not os.path.isfile(LOOKUP_PNG):
    raise RuntimeError('missing %s - is engine_input_block1.toe the open project?'
                       % LOOKUP_PNG)

ROOT = op('/project1')
BUILD = '_kinetic_stripes_build'

old = ROOT.op(BUILD)
if old:
    old.destroy()

m = ROOT.create(baseCOMP, BUILD)
m.nodeX, m.nodeY = 6400, -1800

# Parameters are created before any operator references them: an expression
# assigned against a parameter that does not exist yet does not resolve.

# ------------------------------------------------------ standard parameters
std = m.appendCustomPage('DeckGlow')

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

# No temporal state (no feedback, timers or particles), so Reset has nothing
# to clear; it exists for the uniform API.
std.appendPulse('Reset')

# Built at thumbnail size; set to 1920x1080 just before export.
p = std.appendInt('Outputwidth')[0]
p.default = 1920
p.val = 640

p = std.appendInt('Outputheight')[0]
p.default = 1080
p.val = 360

# --------------------------------------------------- base_scene parameters
scene = m.appendCustomPage('Scene')

# Performer amounts arrive pre-scaled in the lanes (spec s9.1).
# Paletteindex is required by s10.1; the proto look is fixed greys-to-yellow,
# so this module does not read a palette yet.
p = scene.appendInt('Paletteindex')[0]
p.default = 0
p.min = 0
p.clampMin = True
p.val = 0

# -------------------------------------------- creative controls (spec s11)
# Defaults are the proto's literal constants. Keep in sync with module.json.
CONTROLS = [
    # name,          label,           default, min,  max
    ('Stripeperiod', 'Stripe Period', 0.54,    0.1,  2.0),
    ('Stripeshift',  'Stripe Shift',  1.0,     0.0,  2.0),
    ('Flash',        'Flash',         1.25,    0.0,  2.0),
    ('Barzoom',      'Bar Zoom',      1.0,     0.0,  1.5),
    ('Kickzoom',     'Kick Zoom',     0.12,    0.0,  0.5),
    ('Beatdrift',    'Beat Drift',    0.03,    0.0,  0.1),
]
ctl = m.appendCustomPage('Controls')
for name, label, default, lo, hi in CONTROLS:
    p = ctl.appendFloat(name, label=label)[0]
    p.default = default
    p.val = default
    p.normMin, p.normMax = lo, hi
    p.min, p.max = lo, hi
    p.clampMin = p.clampMax = True


def lane(name):
    """Safe lane read: 0 when the motion input is absent (spec s12.2)."""
    mo = "op('../motion')"
    return "({0}.chan('{1}').eval() if {0}.chan('{1}') else 0)".format(mo, name)


def ctlpar(name):
    return 'parent(2).par.' + name


def place(o, x, y):
    o.nodeX, o.nodeY = x, y


# ------------------------------------------------------- required operators
mot_in = m.create(inCHOP, 'in0_motion')
place(mot_in, 0, 0)

pal_in = m.create(inDAT, 'in1_palette')
place(pal_in, 0, -200)

motion = m.create(nullCHOP, 'motion')
place(motion, 300, 0)
motion.inputConnectors[0].connect(mot_in)

render = m.create(baseCOMP, 'render')
place(render, 700, 0)

# --------------------------------------------------------------- render net
keys = render.create(tableDAT, 'stripe_keys')
place(keys, -400, 300)
keys.clear()
for row in (['pos', 'r', 'g', 'b', 'a'],
            [0.0,        0.0,        0.0,        0.0,        1],
            [0.10152284, 0.14213198, 0.14213198, 0.14213198, 1],
            [0.28172588, 0.44923857, 0.44923857, 0.44923857, 1],
            [0.6675127,  1,          1,          0,          1],
            [1,          1,          1,          1,          1]):
    keys.appendRow(row)

stripes = render.create(rampTOP, 'stripes')
place(stripes, 0, 0)
for d in list(stripes.docked):      # drop any auto-created keys DAT
    d.destroy()
stripes.par.dat = 'stripe_keys'
stripes.par.outputresolution = 'custom'
# Honour the runtime's requested size exactly (spec s14, s15.4).
stripes.par.resmult = False
stripes.par.resolutionw.expr = 'parent(2).par.Outputwidth'
stripes.par.resolutionh.expr = 'parent(2).par.Outputheight'
stripes.par.period.expr = ctlpar('Stripeperiod')
stripes.par.phase.expr = '%s * %s' % (lane('body_level'), ctlpar('Stripeshift'))

tex = render.create(moviefileinTOP, 'lookup_tex')
place(tex, 0, -300)
tex.par.file = LOOKUP_PNG           # cleared again once locked (stage A)

colorize = render.create(lookupTOP, 'colorize')
place(colorize, 300, 0)
colorize.inputConnectors[0].connect(stripes)
colorize.inputConnectors[1].connect(tex)

flash = render.create(levelTOP, 'flash')
place(flash, 600, 0)
flash.inputConnectors[0].connect(colorize)
flash.par.brightness1.expr = '0.75 + %s * %s' % (lane('impact_fast'), ctlpar('Flash'))

bar_zoom = render.create(transformTOP, 'bar_zoom')
place(bar_zoom, 900, 0)
bar_zoom.inputConnectors[0].connect(flash)
z = '1 + %s * %s' % (lane('sync_bar_env'), ctlpar('Barzoom'))
bar_zoom.par.sx.expr = z
bar_zoom.par.sy.expr = z

kick_zoom = render.create(transformTOP, 'kick_zoom')
place(kick_zoom, 1200, 0)
kick_zoom.inputConnectors[0].connect(bar_zoom)
z = '1 + %s * %s' % (lane('impact_wide'), ctlpar('Kickzoom'))
kick_zoom.par.sx.expr = z
kick_zoom.par.sy.expr = z

drift = render.create(transformTOP, 'beat_drift')
place(drift, 1500, 0)
drift.inputConnectors[0].connect(kick_zoom)
drift.par.tx.expr = '%s * %s' % (lane('sync_sine'), ctlpar('Beatdrift'))

tile_right = render.create(transformTOP, 'tile_right')
place(tile_right, 1500, 300)
tile_right.inputConnectors[0].connect(kick_zoom)
tile_right.par.tx = 0.1

tile_left = render.create(transformTOP, 'tile_left')
place(tile_left, 1500, -300)
tile_left.inputConnectors[0].connect(kick_zoom)
tile_left.par.tx = -0.1

tile_fill = render.create(compositeTOP, 'tile_fill')
place(tile_fill, 1800, 0)
tile_fill.inputConnectors[0].connect(tile_right)
tile_fill.inputConnectors[1].connect(drift)
tile_fill.inputConnectors[2].connect(tile_left)
tile_fill.par.operand = 'over'

intensity = render.create(levelTOP, 'intensity')
place(intensity, 2100, 0)
intensity.inputConnectors[0].connect(tile_fill)
intensity.par.brightness1.expr = 'parent(2).par.Intensity'

rout = render.create(outTOP, 'out1')
place(rout, 2400, 0)
rout.inputConnectors[0].connect(intensity)

out1 = m.create(outTOP, 'out1')
place(out1, 1100, 0)
# a COMP is not a valid source; connect to its output connector
out1.inputConnectors[0].connect(render.outputConnectors[0])

print('kinetic_stripes network built in', m.path, '- finishing in a few frames...')

# ------------------------------------------------------ deferred stages
# Size alone cannot prove the image loaded: an empty TOP is also 256x256. The
# source PNG's red channel averages 117/255 = 0.46, so check the pixels.
TEX_OK = '''
def tex_ok(tex):
    try:
        mean = float(tex.numpyArray()[:, :, 0].mean())
    except Exception as e:
        return False, 'unreadable (%%s)' %% e
    good = (tex.width, tex.height) == (256, 256) and 0.40 < mean < 0.52
    return good, '%%dx%%d, mean %%.3f (want 256x256, ~0.46)' %% (tex.width, tex.height, mean)
'''

# Stage A: the PNG has loaded; freeze it into the module and drop the path.
STAGE_A = TEX_OK + '''
b = op(%(build)r)
tex = b.op('render/lookup_tex')
good, info = tex_ok(tex)
print('  lookup image      ' + info)
if not good:
    print('FAIL lookup image did not load; leaving %%s for inspection' %% b.path)
else:
    tex.lock = True
    tex.par.file = ''
    run(%(stage_b)r, delayFrames=5)
'''

# Stage B: confirm the lock survived, save the thumbnail at 640x360, then
# export at the default 1920x1080 and remove the build COMP.
STAGE_B = TEX_OK + '''
import os
b = op(%(build)r)
tex = b.op('render/lookup_tex')
out = b.op('out1')
good, info = tex_ok(tex)
print('  after lock        %%s, lock=%%s' %% (info, tex.lock))
if not (good and tex.lock):
    print('FAIL lookup image lost after locking; leaving %%s for inspection' %% b.path)
else:
    out.cook(force=True)
    print('  thumbnail render  %%dx%%d' %% (out.width, out.height))
    out.save(%(thumb)r)
    b.par.Outputwidth = 1920
    b.par.Outputheight = 1080
    b.save(%(tox)r)
    ok = os.path.isfile(%(tox)r) and os.path.isfile(%(thumb)r)
    for f in (%(tox)r, %(thumb)r):
        print('  wrote', f, os.path.getsize(f) if os.path.isfile(f) else 'MISSING')
    if ok:
        b.destroy()
        print('kinetic_stripes exported; build COMP removed')
        print('next: load it in module_host (see CLAUDE.md, Block 3)')
    else:
        print('FAIL export incomplete; leaving', b.path, 'for inspection')
'''

_vars = {'build': m.path, 'tox': TOX, 'thumb': THUMB}
_vars['stage_b'] = STAGE_B % _vars
run(STAGE_A % _vars, delayFrames=10)
