"""Builds and exports the projector_safe finish_fx module (Block 6).

Run inside TouchDesigner's textport (Alt+T), with engine_input_block1.toe open:

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_projector_safe.py').read())

Writes modules/projector_safe/module.tox and thumbnail.png next to
module.json. The thumbnail is rendered over kinetic_stripes' thumbnail, so
Block 3 must have been exported.

How it works:

    in0_image -> render/in_image -+-> render/soft (Blur) -+
                                  +-----------------------+-> render/finish (GLSL)
                                  \-> render/out_switch (pass-through) -> out1

    soft     = Softness x (0.6 + 0.8 x mood_softness)   blend toward the blur
    contrast = (c - 0.5) x Contrast + 0.5, then x Brightness
    punch    = x (1 + Punch x impact_wide)              restrained, spec s10.4
    warmth   = r x (1 + t), b x (1 - t), t = (mood_warmth - 0.5) x 0.2 x Warmth
    clamp    = 0..1 when Outputclamp is on
    Intensity blends the finished image with the untouched input.

With the spec defaults (Contrast 1, Brightness 1, Softness 0) the image only
moves by the small warmth and punch terms. Moduleactive off or Intensity 0
passes in0_image through exactly. Final hardware safety is not this module's
job: /project1/output applies it after every module and is never bypassed.

No Python: parameter expressions only (capabilities.usesPython false).

Contract: docs/SCENE_MODULE_SPEC.md sections 6, 9, 10.4, 11 and 12.
"""

import os

MODULE_DIR = os.path.join(project.folder, 'modules', 'projector_safe')
TOX = os.path.join(MODULE_DIR, 'module.tox')
THUMB = os.path.join(MODULE_DIR, 'thumbnail.png')
THUMB_SRC = os.path.join(project.folder, 'modules', 'kinetic_stripes', 'thumbnail.png')

if not os.path.isfile(THUMB_SRC):
    raise RuntimeError('missing %s - export kinetic_stripes (Block 3) first' % THUMB_SRC)

ROOT = op('/project1')
BUILD = '_projector_safe_build'
BG = '_projector_safe_thumb_bg'

for nm in (BUILD, BG):
    old = ROOT.op(nm)
    if old:
        old.destroy()


def place(o, x, y):
    o.nodeX, o.nodeY = x, y


m = ROOT.create(baseCOMP, BUILD)
m.nodeX, m.nodeY = 11200, -1800

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

# No temporal state; Reset exists for the uniform API.
std.appendPulse('Reset')

p = std.appendInt('Outputwidth')[0]
p.default = 1920
p.val = 1920

p = std.appendInt('Outputheight')[0]
p.default = 1080
p.val = 1080

# ------------------------------------------------- finish_fx parameters s10.4
fin = m.appendCustomPage('Finish')
for name, default, lo, hi in (('Contrast', 1.0, 0.0, 2.0),
                              ('Brightness', 1.0, 0.0, 2.0),
                              ('Softness', 0.0, 0.0, 1.0)):
    p = fin.appendFloat(name)[0]
    p.default = default
    p.val = default
    p.normMin, p.normMax = lo, hi
    p.min, p.max = lo, hi
    p.clampMin = p.clampMax = True

p = fin.appendToggle('Outputclamp', label='Output Clamp')[0]
p.default = 1
p.val = 1

# -------------------------------------------- creative controls (spec s11)
# Keep in sync with module.json.
CONTROLS = [
    # name,     label,    default, min, max
    ('Warmth', 'Warmth',  0.3,     0.0, 1.0),
    ('Punch',  'Punch',   0.08,    0.0, 0.3),
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
    """Safe lane read from inside render: 0 when motion is absent (s12.2)."""
    mo = "op('../motion')"
    return "({0}.chan('{1}').eval() if {0}.chan('{1}') else 0)".format(mo, name)


R = 'parent(2).par.'

# ------------------------------------------------------- required operators
img_in = m.create(inTOP, 'in0_image')
place(img_in, 0, 200)

mot_in = m.create(inCHOP, 'in1_motion')
place(mot_in, 0, 0)

motion = m.create(nullCHOP, 'motion')
place(motion, 300, 0)
motion.inputConnectors[0].connect(mot_in)

render = m.create(baseCOMP, 'render')
place(render, 700, 100)

SHADER = r'''
// projector_safe: restrained softness, contrast, brightness and warmth.
uniform vec4 uFinish;   // x contrast, y brightness, z softness, w clamp (0/1)
uniform vec4 uMood;     // x warmth tint t (signed), y punch, z Intensity

layout(location = 0) out vec4 fragColor;

void main()
{
    vec4 src = texture(sTD2DInputs[0], vUV.st);
    vec3 soft = texture(sTD2DInputs[1], vUV.st).rgb;

    vec3 c = mix(src.rgb, soft, clamp(uFinish.z, 0.0, 1.0));
    c = (c - 0.5) * uFinish.x + 0.5;
    c *= uFinish.y * (1.0 + uMood.y);
    c *= vec3(1.0 + uMood.x, 1.0, 1.0 - uMood.x);
    if (uFinish.w > 0.5)
        c = clamp(c, 0.0, 1.0);

    c = mix(src.rgb, c, clamp(uMood.z, 0.0, 1.0));
    fragColor = TDOutputSwizzle(vec4(c, src.a));
}
'''

shader = render.create(textDAT, 'finish_shader')
place(shader, 300, 400)
shader.text = SHADER

in_image = render.create(inTOP, 'in_image')
place(in_image, 0, 0)

soft = render.create(blurTOP, 'soft')
place(soft, 300, -200)
soft.inputConnectors[0].connect(in_image)
soft.par.extend = 'hold'
# resolution-independent: about 0.8% of the frame height
soft.par.size.expr = "max(1, me.inputs[0].height * 0.008) if me.inputs else 4"

fx = render.create(glslTOP, 'finish')
place(fx, 600, 0)
fx.inputConnectors[0].connect(in_image)
fx.inputConnectors[1].connect(soft)
fx.par.pixeldat = 'finish_shader'
fx.seq.vec.numBlocks = 2
fx.par.vec0name = 'uFinish'
fx.par.vec0valuex.expr = R + 'Contrast'
fx.par.vec0valuey.expr = R + 'Brightness'
fx.par.vec0valuez.expr = 'min(1, %sSoftness * (0.6 + 0.8 * %s))' % (R, lane('mood_softness'))
fx.par.vec0valuew.expr = R + 'Outputclamp'
fx.par.vec1name = 'uMood'
fx.par.vec1valuex.expr = '(%s - 0.5) * 0.2 * %sWarmth' % (lane('mood_warmth'), R)
fx.par.vec1valuey.expr = '%sPunch * %s' % (R, lane('impact_wide'))
fx.par.vec1valuez.expr = R + 'Intensity'

sw = render.create(switchTOP, 'out_switch')
place(sw, 900, 0)
sw.inputConnectors[0].connect(fx)
sw.inputConnectors[1].connect(in_image)
sw.par.index.expr = '0 if (%sModuleactive and %sIntensity > 0) else 1' % (R, R)

rout = render.create(outTOP, 'out1')
place(rout, 1200, 0)
rout.inputConnectors[0].connect(sw)

render.inputConnectors[0].connect(img_in)

out1 = m.create(outTOP, 'out1')
place(out1, 1100, 100)
out1.inputConnectors[0].connect(render.outputConnectors[0])

# ------------------------------------------------ thumbnail background
bg = ROOT.create(moviefileinTOP, BG)
bg.nodeX, bg.nodeY = 10800, -1800
bg.par.file = THUMB_SRC
m.inputConnectors[0].connect(bg)

print('projector_safe network built in', m.path, '- finishing in a few frames...')

# The thumbnail shows the finish at work (softer, punchier) over the stripes;
# the exported module keeps the spec defaults.
STAGE = '''
import os
b = op(%(build)r)
bg = op(%(bg)r)
fx = b.op('render/finish')
out = b.op('out1')
b.par.Softness = 0.35
b.par.Contrast = 1.25
out.cook(force=True)
err = fx.errors()
print('  background        %%dx%%d (want 640x360)' %% (bg.width, bg.height))
print('  shader            ' + (err or 'compiled, no errors'))
if fx.warnings():
    print('  shader warnings   ' + fx.warnings())
print('  blur size         %%.1f px' %% b.op('render/soft').par.size.eval())
print('  output            %%dx%%d, switch %%s (0 = finish applied)'
      %% (out.width, out.height, b.op('render/out_switch').par.index.eval()))
if err or (bg.width, bg.height) != (640, 360):
    print('FAIL shader error or background not loaded; leaving %%s for inspection' %% b.path)
else:
    out.save(%(thumb)r)
    b.par.Softness = 0.0
    b.par.Contrast = 1.0
    b.inputConnectors[0].disconnect()
    b.save(%(tox)r)
    ok = os.path.isfile(%(tox)r) and os.path.isfile(%(thumb)r)
    for f in (%(tox)r, %(thumb)r):
        print('  wrote', f, os.path.getsize(f) if os.path.isfile(f) else 'MISSING')
    if ok:
        b.destroy()
        bg.destroy()
        print('projector_safe exported; build COMPs removed')
        print('next: load it in finish_host (see CLAUDE.md, Block 6)')
    else:
        print('FAIL export incomplete; leaving', b.path, 'for inspection')
'''

if not os.path.isdir(MODULE_DIR):
    os.makedirs(MODULE_DIR)

run(STAGE % {'build': m.path, 'bg': bg.path, 'tox': TOX, 'thumb': THUMB},
    delayFrames=10)
