"""Builds and exports the orb_burst hit_fx module (Block 4).

Run inside TouchDesigner's textport (Alt+T), with engine_input_block1.toe open:

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_orb_burst.py').read())

Writes modules/orb_burst/module.tox and thumbnail.png next to module.json.
Paths derive from project.folder, so the .toe must be the one in touchDesigner/.

How it works:

    in1_motion -> motion --(read by Python)--> render/pool (Script CHOP, 32 slots)
                                                  |  orbs_a: x y radius alpha
                                                  |  orbs_b: r g b core
    in0_image -> render/in_image -> render/orb_fx (GLSL TOP: soft discs + blend)
                                 \-> render/out_switch (pass-through) -> out1

- impact_trigger spawns Spawncount orbs into a fixed ring of 32 slots; the
  oldest slot is reused, so the count can never grow (spec s10.2, s14).
- impact_fast at the moment of the trigger sets each burst's brightness, so
  flashAmount and masterIntensity reach the orbs. A burst at zero flash is
  skipped entirely.
- impact_wide sustains the orbs while it is high (persistence).
- Positions and sizes come from random.Random(Seed, burst number): the same
  Seed and trigger sequence give the same orbs. Reset clears all slots.
- Colours cycle palette primary/secondary/accent from in2_palette, with the
  spec's default palette when it is absent; Colorize blends from white.
- Moduleactive off, or Fxamount x Intensity at 0, switches to an exact
  pass-through of in0_image.

Uses Python (the pool), so module.json declares capabilities.usesPython.

The export finishes in a deferred stage (TouchDesigner initialises
asynchronously - see CLAUDE.md): it spawns a demo burst over a dark
background for the thumbnail, then saves.

Contract: docs/SCENE_MODULE_SPEC.md sections 6, 9, 10.2, 11, 12 and 14.
"""

import os

MODULE_DIR = os.path.join(project.folder, 'modules', 'orb_burst')
TOX = os.path.join(MODULE_DIR, 'module.tox')
THUMB = os.path.join(MODULE_DIR, 'thumbnail.png')

ROOT = op('/project1')
BUILD = '_orb_burst_build'
BG = '_orb_burst_thumb_bg'

for nm in (BUILD, BG):
    old = ROOT.op(nm)
    if old:
        old.destroy()

m = ROOT.create(baseCOMP, BUILD)
m.nodeX, m.nodeY = 8000, -1800

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

std.appendPulse('Reset')

# Non-base modules preserve the input size; these exist for the uniform API.
p = std.appendInt('Outputwidth')[0]
p.default = 1920
p.val = 1920

p = std.appendInt('Outputheight')[0]
p.default = 1080
p.val = 1080

# ------------------------------------------------- hit_fx parameters s10.2
hit = m.appendCustomPage('Hit FX')

p = hit.appendFloat('Fxamount', label='FX Amount')[0]
p.default = 1
p.val = 1
p.normMin, p.normMax = 0, 1
p.min, p.max = 0, 1
p.clampMin = p.clampMax = True

p = hit.appendMenu('Blendmode', label='Blend Mode')[0]
p.menuNames = ['over', 'add', 'screen']
p.menuLabels = ['Over', 'Add', 'Screen']
p.default = 'over'
p.val = 'over'

p = hit.appendFloat('Colorize')[0]
p.default = 1
p.val = 1
p.normMin, p.normMax = 0, 1
p.min, p.max = 0, 1
p.clampMin = p.clampMax = True

# -------------------------------------------- creative controls (spec s11)
# Keep in sync with module.json.
CONTROLS = [
    # name,         label,           kind,    default, min,  max
    ('Ballsize',   'Ball Size',      'float', 0.12,    0.02, 0.4),
    ('Lifetime',   'Lifetime',       'float', 0.8,     0.1,  3.0),
    ('Spawncount', 'Balls Per Hit',  'int',   4,       1,    12),
    ('Spread',     'Spread',         'float', 0.6,     0.0,  1.0),
    ('Softness',   'Softness',       'float', 0.5,     0.0,  1.0),
]
ctl = m.appendCustomPage('Controls')
for name, label, kind, default, lo, hi in CONTROLS:
    append = ctl.appendInt if kind == 'int' else ctl.appendFloat
    p = append(name, label=label)[0]
    p.default = default
    p.val = default
    p.normMin, p.normMax = lo, hi
    p.min, p.max = lo, hi
    p.clampMin = p.clampMax = True


def place(o, x, y):
    o.nodeX, o.nodeY = x, y


# ------------------------------------------------------- required operators
img_in = m.create(inTOP, 'in0_image')
place(img_in, 0, 200)

mot_in = m.create(inCHOP, 'in1_motion')
place(mot_in, 0, 0)

pal_in = m.create(inDAT, 'in2_palette')
place(pal_in, 0, -200)

motion = m.create(nullCHOP, 'motion')
place(motion, 300, 0)
motion.inputConnectors[0].connect(mot_in)

render = m.create(baseCOMP, 'render')
place(render, 700, 100)

# ------------------------------------------------------------ orb pool logic
ORBS = r'''
# orb_burst pool. State lives in render's storage, so it survives cooks but
# not a rebuild. Reset() clears it. See build_orb_burst.py for the design.
import random

POOL = 32
ROLES = ('primary', 'secondary', 'accent')
DEFAULT_PALETTE = {                      # SCENE_MODULE_SPEC s8.1
    'primary':   (1.00, 0.82, 0.10),
    'secondary': (0.10, 0.35, 1.00),
    'accent':    (1.00, 1.00, 1.00),
}


def _root():
    return parent(2)


def _fresh():
    return {'slots': [None] * POOL, 'next': 0, 'bursts': 0, 'prev': False}


def _state():
    st = parent().storage.get('orbs')
    if st is None:
        st = _fresh()
        parent().store('orbs', st)
    return st


def Reset():
    parent().store('orbs', _fresh())


def _lane(name):
    mo = _root().op('motion')
    c = mo[name] if mo is not None else None
    return c.eval() if c is not None else 0.0


def _palette():
    pal = dict(DEFAULT_PALETTE)
    dat = _root().op('in2_palette')
    try:
        for r in range(1, dat.numRows):
            role = dat[r, 0].val.strip()
            if role in pal:
                pal[role] = (float(dat[r, 1]), float(dat[r, 2]), float(dat[r, 3]))
    except Exception:
        pass                             # absent or malformed: defaults stand
    return pal


def _spawn(st, energy, now):
    root = _root()
    st['bursts'] += 1
    rng = random.Random(int(root.par.Seed.eval()) * 1000003 + st['bursts'])
    spread = float(root.par.Spread.eval())
    size = float(root.par.Ballsize.eval())
    for i in range(int(root.par.Spawncount.eval())):
        slot = st['next']
        st['next'] = (slot + 1) % POOL
        st['slots'][slot] = {
            'birth': now,
            'x': 0.5 + (rng.random() - 0.5) * spread,
            'y': 0.5 + (rng.random() - 0.5) * spread,
            'size': size * (0.6 + 0.8 * rng.random()),
            'role': ROLES[(st['bursts'] + i) % len(ROLES)],
            'energy': energy,
        }


def Demo(count=8):
    """Spawn a full-energy burst now. Used by the builder for the thumbnail."""
    root = _root()
    keep = root.par.Spawncount.eval()
    root.par.Spawncount = count
    _spawn(_state(), 1.0, absTime.seconds)
    root.par.Spawncount = keep


def Cook(scriptOp):
    root = _root()
    st = _state()
    now = absTime.seconds

    if root.par.Moduleactive.eval():
        trig = _lane('impact_trigger') > 0.5
        if trig and not st['prev']:
            energy = min(1.0, 2.0 * _lane('impact_fast'))
            if energy > 0.02:
                _spawn(st, energy, now)
        st['prev'] = trig

    life_s = max(0.05, float(root.par.Lifetime.eval()))
    persist = 0.6 + 0.4 * _lane('impact_wide')
    colorize = float(root.par.Colorize.eval())
    core = min(0.98, max(0.0, 1.0 - float(root.par.Softness.eval())))
    pal = _palette()

    cols = {k: [0.0] * POOL for k in ('x', 'y', 'radius', 'alpha', 'r', 'g', 'b', 'core')}
    for i, o in enumerate(st['slots']):
        if o is None:
            continue
        t = (now - o['birth']) / life_s
        if t < 0.0 or t >= 1.0:
            st['slots'][i] = None
            continue
        cols['x'][i] = o['x']
        cols['y'][i] = o['y']
        cols['radius'][i] = o['size'] * (0.55 + 0.45 * min(1.0, t * 4.0))
        cols['alpha'][i] = o['energy'] * (1.0 - t) ** 2 * persist
        pr, pg, pb = pal[o['role']]
        cols['r'][i] = 1.0 + (pr - 1.0) * colorize
        cols['g'][i] = 1.0 + (pg - 1.0) * colorize
        cols['b'][i] = 1.0 + (pb - 1.0) * colorize
        cols['core'][i] = core

    scriptOp.clear()
    scriptOp.isTimeSlice = False
    scriptOp.numSamples = POOL
    for name in ('x', 'y', 'radius', 'alpha', 'r', 'g', 'b', 'core'):
        scriptOp.appendChan(name).vals = cols[name]


def Alive():
    return sum(1 for o in _state()['slots'] if o is not None)
'''

POOL_CALLBACKS = r'''
def onSetupParameters(scriptOp):
    return

def onPulse(par):
    return

def onGetCookLevel(scriptOp):
    # every frame while the output is in use, so orbs keep fading even when
    # the motion input holds still
    return CookLevel.WHEN_USED

def onCook(scriptOp):
    op('orbs').module.Cook(scriptOp)
    return
'''

SHADER = r'''
// orb_burst: soft discs from the pool, blended over the input image.
uniform vec4 uParams;    // x: Fxamount * Intensity, y: blend (0 over, 1 add, 2 screen)
uniform vec4 uOrbA[32];  // x, y (0..1 uv), radius (fraction of height), alpha
uniform vec4 uOrbB[32];  // r, g, b, core (where the soft edge starts, 0..1 of radius)

layout(location = 0) out vec4 fragColor;

void main()
{
    vec4 base = texture(sTD2DInputs[0], vUV.st);
    float aspect = uTDOutputInfo.res.z / uTDOutputInfo.res.w;

    vec3 fx = vec3(0.0);
    float cover = 0.0;
    for (int i = 0; i < 32; i++) {
        vec4 a = uOrbA[i];
        if (a.w <= 0.0 || a.z <= 0.0)
            continue;
        vec2 d = vUV.st - a.xy;
        d.x *= aspect;
        float r = length(d) / a.z;
        float m = (1.0 - smoothstep(uOrbB[i].w, 1.0, r)) * a.w;
        fx += uOrbB[i].rgb * m;          // premultiplied
        cover = max(cover, m);
    }

    float amt = clamp(uParams.x, 0.0, 1.0);
    fx = clamp(fx, 0.0, 1.0) * amt;
    cover = clamp(cover, 0.0, 1.0) * amt;

    int mode = int(uParams.y + 0.5);
    vec3 rgb;
    float alpha = base.a;
    if (mode == 1) {
        rgb = base.rgb + fx;
    } else if (mode == 2) {
        rgb = 1.0 - (1.0 - base.rgb) * (1.0 - fx);
    } else {
        rgb = fx + base.rgb * (1.0 - cover);
        alpha = cover + base.a * (1.0 - cover);
    }
    fragColor = TDOutputSwizzle(vec4(rgb, alpha));
}
'''

orbs = render.create(textDAT, 'orbs')
place(orbs, 0, 400)
orbs.text = ORBS

cb = render.create(textDAT, 'pool_callbacks')
place(cb, 300, 400)
cb.text = POOL_CALLBACKS

pool = render.create(scriptCHOP, 'pool')
place(pool, 300, 100)
pool.par.callbacks = 'pool_callbacks'

orbs_a = render.create(selectCHOP, 'orbs_a')
place(orbs_a, 600, 200)
orbs_a.inputConnectors[0].connect(pool)
orbs_a.par.channames = 'x y radius alpha'

orbs_b = render.create(selectCHOP, 'orbs_b')
place(orbs_b, 600, 0)
orbs_b.inputConnectors[0].connect(pool)
orbs_b.par.channames = 'r g b core'

shader = render.create(textDAT, 'orb_shader')
place(shader, 600, 400)
shader.text = SHADER

in_image = render.create(inTOP, 'in_image')
place(in_image, 600, -300)

fx = render.create(glslTOP, 'orb_fx')
place(fx, 900, 0)
fx.inputConnectors[0].connect(in_image)
fx.par.pixeldat = 'orb_shader'
fx.seq.vec.numBlocks = 1
fx.par.vec0name = 'uParams'
fx.par.vec0valuex.expr = 'parent(2).par.Fxamount * parent(2).par.Intensity'
fx.par.vec0valuey.expr = 'parent(2).par.Blendmode.menuIndex'
fx.seq.array.numBlocks = 2
for i, (uni, src) in enumerate((('uOrbA', 'orbs_a'), ('uOrbB', 'orbs_b'))):
    getattr(fx.par, 'array%dname' % i).val = uni
    getattr(fx.par, 'array%dtype' % i).val = 'vec4'
    getattr(fx.par, 'array%dchop' % i).val = src
    getattr(fx.par, 'array%darraytype' % i).val = 'uniformarray'

# Exact pass-through when inactive or at zero amount (spec s10.2).
sw = render.create(switchTOP, 'out_switch')
place(sw, 1200, 0)
sw.inputConnectors[0].connect(fx)
sw.inputConnectors[1].connect(in_image)
sw.par.index.expr = ('0 if (parent(2).par.Moduleactive and '
                     'parent(2).par.Fxamount * parent(2).par.Intensity > 0) else 1')

rout = render.create(outTOP, 'out1')
place(rout, 1500, 0)
rout.inputConnectors[0].connect(sw)

# the image enters render through its own In TOP
render.inputConnectors[0].connect(img_in)

out1 = m.create(outTOP, 'out1')
place(out1, 1100, 100)
# a COMP is not a valid source; connect to its output connector
out1.inputConnectors[0].connect(render.outputConnectors[0])

# ---------------------------------------------------------- Reset handling
pe = m.create(parameterexecuteDAT, 'reset_parexec')
place(pe, 300, -400)
pe.par.op = m
pe.par.pars = 'Reset Moduleactive Seed'
pe.par.custom = True
pe.par.builtin = False
pe.par.valuechange = True
pe.par.onpulse = True
pe.par.active = True
pe.text = '''
# Spec s12.1: temporal state clears on Reset; deactivating or reseeding also
# starts clean so the same Seed replays the same orbs.
def onValueChange(par, prev):
    op('render/orbs').module.Reset()
    return

def onPulse(par):
    op('render/orbs').module.Reset()
    return
'''

# ------------------------------------------------ thumbnail background
bg = ROOT.create(constantTOP, BG)
bg.nodeX, bg.nodeY = 7600, -1800
bg.par.outputresolution = 'custom'
bg.par.resmult = False
bg.par.resolutionw = 640
bg.par.resolutionh = 360
bg.par.colorr, bg.par.colorg, bg.par.colorb = 0.04, 0.04, 0.06
bg.par.alpha = 1
m.inputConnectors[0].connect(bg)

print('orb_burst network built in', m.path, '- finishing in a few frames...')

# ------------------------------------------------------ deferred stages
# Stage A: check the shader compiled, then spawn a demo burst.
STAGE_A = '''
b = op(%(build)r)
fx = b.op('render/orb_fx')
fx.cook(force=True)
err = fx.errors()
warn = fx.warnings()
print('  shader            ' + (err or 'compiled, no errors'))
if warn:
    print('  shader warnings   ' + warn)
if err:
    print('FAIL orb_fx has errors; leaving %%s for inspection' %% b.path)
else:
    b.op('render/orbs').module.Demo(8)
    run(%(stage_b)r, delayFrames=4)
'''

# Stage B: render the thumbnail, export, clean up.
STAGE_B = '''
import os
b = op(%(build)r)
out = b.op('out1')
pool = b.op('render/pool')
out.cook(force=True)
alive = b.op('render/orbs').module.Alive()
print('  pool              %%d samples, %%d orbs alive (want 32, 8)'
      %% (pool.numSamples, alive))
print('  thumbnail render  %%dx%%d' %% (out.width, out.height))
if pool.numSamples != 32 or alive == 0:
    print('FAIL pool did not produce orbs; leaving %%s for inspection' %% b.path)
else:
    out.save(%(thumb)r)
    b.op('render/orbs').module.Reset()
    b.inputConnectors[0].disconnect()
    b.save(%(tox)r)
    ok = os.path.isfile(%(tox)r) and os.path.isfile(%(thumb)r)
    for f in (%(tox)r, %(thumb)r):
        print('  wrote', f, os.path.getsize(f) if os.path.isfile(f) else 'MISSING')
    if ok:
        b.destroy()
        op(%(bg)r).destroy()
        print('orb_burst exported; build COMPs removed')
        print('next: load it in hit_host (see CLAUDE.md, Block 4)')
    else:
        print('FAIL export incomplete; leaving', b.path, 'for inspection')
'''

if not os.path.isdir(MODULE_DIR):
    os.makedirs(MODULE_DIR)

_vars = {'build': m.path, 'bg': bg.path, 'tox': TOX, 'thumb': THUMB}
_vars['stage_b'] = STAGE_B % _vars
run(STAGE_A % _vars, delayFrames=5)
