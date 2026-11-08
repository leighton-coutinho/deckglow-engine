"""Builds and exports the solid_background base_scene module.

Run inside TouchDesigner's textport (Alt+T), with engine_input_block1.toe open:

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_solid_background.py').read())

Writes modules/solid_background/module.tox and thumbnail.png next to
module.json.

The runtime palette's `background` colour (which the frontend's
setBackground overrides), pulsing toward the palette's `primary` on the beat.
It is the "alive" background scene; a completely still colour needs no module
at all - an empty or switched-off base slot shows the background colour.

    colour = (background + (primary - background) x Breathe x sync_level) x Intensity

At idle it is exactly the background colour; Breathe 0 makes it still; the
master fader calms it (it scales sync_level). The first version only scaled
brightness with body_level and failed quarantine's Sync test (s15.3) - a base
scene must move with the beat, and dimming a near-black background barely
changes a pixel. It is also the cleanest reference module: no Python, only
pure-read expressions, so it passes the creator-pack rules (PACK_FORMAT_SPEC
s6) unchanged. Without a palette input it uses the spec's default colours.
"""

import os

MODULE_DIR = os.path.join(project.folder, 'modules', 'solid_background')
TOX = os.path.join(MODULE_DIR, 'module.tox')
THUMB = os.path.join(MODULE_DIR, 'thumbnail.png')

ROOT = op('/project1')
BUILD = '_solid_background_build'
DEMO = '_solid_background_thumb_palette'
FALLBACK = {'background': {'r': 0.02, 'g': 0.02, 'b': 0.03},   # SCENE_MODULE_SPEC s8.1
            'primary':    {'r': 1.00, 'g': 0.82, 'b': 0.10}}

for nm in (BUILD, DEMO):
    old = ROOT.op(nm)
    if old:
        old.destroy()

m = ROOT.create(baseCOMP, BUILD)
m.nodeX, m.nodeY = 6400, -2400

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
std.appendPulse('Reset')            # no temporal state
p = std.appendInt('Outputwidth')[0]
p.default = 1920
p.val = 640                         # thumbnail size while building
p = std.appendInt('Outputheight')[0]
p.default = 1080
p.val = 360

# -------------------------------------------- creative controls (spec s11)
ctl = m.appendCustomPage('Controls')
p = ctl.appendFloat('Breathe', label='Beat Pulse')[0]
p.default = 0.15
p.val = 0.15
p.normMin, p.normMax = 0, 1
p.min, p.max = 0, 1
p.clampMin = p.clampMax = True


def lane(name):
    """Safe lane read from inside render: 0 when motion is absent (s12.2)."""
    mo = "op('../motion')"
    return "({0}.chan('{1}').eval() if {0}.chan('{1}') else 0)".format(mo, name)


def palette(role, comp):
    cell = "op('../in1_palette')['%s', '%s']" % (role, comp)
    return "(float(%s.val) if %s is not None else %s)" % (cell, cell, FALLBACK[role][comp])


# ------------------------------------------------------- required operators
mot_in = m.create(inCHOP, 'in0_motion')
mot_in.nodeX, mot_in.nodeY = 0, 0
pal_in = m.create(inDAT, 'in1_palette')
pal_in.nodeX, pal_in.nodeY = 0, -200
motion = m.create(nullCHOP, 'motion')
motion.nodeX, motion.nodeY = 300, 0
motion.inputConnectors[0].connect(mot_in)

render = m.create(baseCOMP, 'render')
render.nodeX, render.nodeY = 700, 0

fill = render.create(constantTOP, 'fill')
fill.nodeX, fill.nodeY = 0, 0
fill.par.outputresolution = 'custom'
fill.par.resmult = False                        # honour the requested size (s6.4)
fill.par.resolutionw.expr = 'parent(2).par.Outputwidth'
fill.par.resolutionh.expr = 'parent(2).par.Outputheight'
pulse = "parent(2).par.Breathe * %s" % lane('sync_level')
for comp, par in (('r', 'colorr'), ('g', 'colorg'), ('b', 'colorb')):
    bg, pri = palette('background', comp), palette('primary', comp)
    getattr(fill.par, par).expr = '(%s + (%s - %s) * %s) * parent(2).par.Intensity' % (bg, pri, bg, pulse)
fill.par.alpha = 1

rout = render.create(outTOP, 'out1')
rout.nodeX, rout.nodeY = 300, 0
rout.inputConnectors[0].connect(fill)

out1 = m.create(outTOP, 'out1')
out1.nodeX, out1.nodeY = 1100, 0
out1.inputConnectors[0].connect(render.outputConnectors[0])

# ------------------------------------------------- thumbnail and export
# A demo palette (deep purple) so the thumbnail shows what the module does;
# the exported module reads whatever palette the runtime gives it.
demo = ROOT.create(tableDAT, DEMO)
demo.nodeX, demo.nodeY = 6000, -2400
demo.clear()
for row in (['role', 'r', 'g', 'b', 'a'], ['background', 0.25, 0.0, 0.35, 1.0],
            ['primary', 1.0, 0.82, 0.1, 1.0], ['secondary', 0.1, 0.35, 1.0, 1.0],
            ['accent', 1.0, 1.0, 1.0, 1.0]):
    demo.appendRow(row)
m.inputConnectors[1].connect(demo)

if not os.path.isdir(MODULE_DIR):
    os.makedirs(MODULE_DIR)

fill.cook(force=True)
out1.cook(force=True)
print('  thumbnail render  %dx%d, colour %.3f %.3f %.3f' % (
    out1.width, out1.height, fill.par.colorr.eval(), fill.par.colorg.eval(), fill.par.colorb.eval()))
out1.save(THUMB)
m.inputConnectors[1].disconnect()
m.par.Outputwidth = 1920
m.par.Outputheight = 1080
m.save(TOX)

ok = os.path.isfile(TOX) and os.path.isfile(THUMB)
for f in (TOX, THUMB):
    print('  wrote', f, os.path.getsize(f) if os.path.isfile(f) else 'MISSING')
if ok:
    m.destroy()
    demo.destroy()
    print('solid_background exported; build COMPs removed')
    print('next: Scan, Validate and Approve com.deckglow.solid_background in the scene library')
else:
    print('FAIL export incomplete; leaving', m.path, 'for inspection')
