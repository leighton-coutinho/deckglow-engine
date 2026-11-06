"""Builds and exports the clean_lockup brand_overlay module (Block 5).

Run inside TouchDesigner's textport (Alt+T), with engine_input_block1.toe open
and build_brand_source.py already run (the thumbnail uses LOGO, plus a fixed
demo brand table of its own so it never depends on brand_table edits):

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_clean_lockup.py').read())

Writes modules/clean_lockup/module.tox and thumbnail.png next to module.json.

How it works:

    in2_brand (DAT) --> render/layout (Python: reads keys, computes rects)
                           |                 |
                           v                 v
    render/name_text, render/sub_text     uniforms on render/lockup_fx
    (Text TOPs sized to their on-screen height, so text stays crisp)
    in0_image, in3_logo, name_text, sub_text --> render/lockup_fx (GLSL)
                                             \-> render/out_switch -> out1

- Modes from the brand DAT's `mode` key: logo, name, logo_and_name. Without a
  logo image, logo and logo_and_name fall back to the name.
- The lockup is a vertical stack (logo, name, subtitle) anchored by
  Placement inside a safe area inset Safearea x frame height from each edge,
  and shrunk to fit if it would not.
- brand_pulse brightens it slightly (never impact_trigger, spec s10.3).
- A soft dark backing behind every glyph and the logo keeps it legible on
  bright and dark images (Backing control).
- Name uses primaryColor, subtitle secondaryColor; the logo keeps its own
  colours. Brand `opacity` and `scale` apply to everything.
- Moduleactive off, Intensity 0, or both opacities 0 pass in0_image through.

Uses Python (layout), so module.json declares capabilities.usesPython.

Contract: docs/SCENE_MODULE_SPEC.md sections 6, 8.2, 9, 10.3, 11 and 12.
"""

import os

MODULE_DIR = os.path.join(project.folder, 'modules', 'clean_lockup')
TOX = os.path.join(MODULE_DIR, 'module.tox')
THUMB = os.path.join(MODULE_DIR, 'thumbnail.png')

ROOT = op('/project1')
BUILD = '_clean_lockup_build'
BG = '_clean_lockup_thumb_bg'
DEMO = '_clean_lockup_thumb_brand'

# The thumbnail uses its own fixed demo brand, not /project1/BRAND, so it is
# the same whatever the owner has typed into brand_table (mode, name, ...).
DEMO_ROWS = [
    ['key',            'value'],
    ['displayName',    'DJ NAME'],
    ['mode',           'logo_and_name'],
    ['primaryColor',   '1.0,0.82,0.1,1.0'],
    ['secondaryColor', '0.1,0.35,1.0,1.0'],
    ['scale',          '1.0'],
    ['opacity',        '1.0'],
]

if ROOT.op('LOGO') is None:
    raise RuntimeError('run build_brand_source.py first: the thumbnail needs '
                       '/project1/LOGO')

for nm in (BUILD, BG, DEMO):
    old = ROOT.op(nm)
    if old:
        old.destroy()


def menu_pick(par, *candidates):
    """Set a menu to the first candidate matching a token or a label.
    Some menus are undocumented, and labels can be abbreviated: the Text TOP
    unit menus read px / f / a / pt, not Pixels / Fraction / ..."""
    names = [str(n).lower() for n in par.menuNames]
    labels = [str(l).lower() for l in par.menuLabels]
    for c in candidates:
        c = c.lower()
        for options in (names, labels):
            if c in options:
                par.menuIndex = options.index(c)
                return
    raise RuntimeError('%s has none of %s; tokens %s, labels %s'
                       % (par.name, candidates, names, labels))


def place(o, x, y):
    o.nodeX, o.nodeY = x, y


m = ROOT.create(baseCOMP, BUILD)
m.nodeX, m.nodeY = 9600, -1800

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

# -------------------------------------------- brand_overlay parameters s10.3
brand_page = m.appendCustomPage('Brand')

for name, label in (('Logoopacity', 'Logo Opacity'), ('Nameopacity', 'Name Opacity')):
    p = brand_page.appendFloat(name, label=label)[0]
    p.default = 1
    p.val = 1
    p.normMin, p.normMax = 0, 1
    p.min, p.max = 0, 1
    p.clampMin = p.clampMax = True

p = brand_page.appendMenu('Placement')[0]
p.menuNames = ['center', 'top_left', 'top_right', 'bottom_left', 'bottom_right']
p.menuLabels = ['Center', 'Top Left', 'Top Right', 'Bottom Left', 'Bottom Right']
p.default = 'bottom_right'
p.val = 'bottom_right'

p = brand_page.appendFloat('Safearea', label='Safe Area')[0]
p.default = 0.05
p.val = 0.05
p.normMin, p.normMax = 0, 0.25
p.min, p.max = 0, 0.25
p.clampMin = p.clampMax = True

# -------------------------------------------- creative controls (spec s11)
# Keep in sync with module.json.
CONTROLS = [
    # name,       label,        default, min,  max
    ('Logosize', 'Logo Size',   0.22,    0.05, 0.6),
    ('Textsize', 'Text Size',   0.08,    0.02, 0.25),
    ('Backing',  'Backing',     0.5,     0.0,  1.0),
]
ctl = m.appendCustomPage('Controls')
for name, label, default, lo, hi in CONTROLS:
    p = ctl.appendFloat(name, label=label)[0]
    p.default = default
    p.val = default
    p.normMin, p.normMax = lo, hi
    p.min, p.max = lo, hi
    p.clampMin = p.clampMax = True

# ------------------------------------------------------- required operators
img_in = m.create(inTOP, 'in0_image')
place(img_in, 0, 300)

mot_in = m.create(inCHOP, 'in1_motion')
place(mot_in, 0, 100)

brand_in = m.create(inDAT, 'in2_brand')
place(brand_in, 0, -100)

logo_in = m.create(inTOP, 'in3_logo')
place(logo_in, 0, -300)

motion = m.create(nullCHOP, 'motion')
place(motion, 300, 100)
motion.inputConnectors[0].connect(mot_in)

render = m.create(baseCOMP, 'render')
place(render, 700, 0)

# ------------------------------------------------------------ layout logic
LAYOUT = r'''
# clean_lockup layout. Pure functions of the brand DAT, parameters and the
# image size, cached once per frame. See build_clean_lockup.py.

NAME_ASPECT = 8.0        # name_text is 8:1
SUB_ASPECT = 16.0        # sub_text is 16:1
MODES = ('logo', 'name', 'logo_and_name')

_cache = {'frame': None, 'value': None}


def _root():
    return parent(2)


def Brand(key, default=''):
    dat = _root().op('in2_brand')
    try:
        c = dat[key, 1]
        return c.val if c is not None else default
    except Exception:
        return default


def _num(key, default):
    try:
        return float(Brand(key, ''))
    except ValueError:
        return default


def Color(key, default):
    try:
        v = [float(x) for x in Brand(key, '').split(',')]
        return (v + [1.0])[:4] if len(v) >= 3 else default
    except ValueError:
        return default


def LogoPresent():
    """True when the logo input carries visible pixels. An unwired In TOP
    still yields a blank texture, so test its alpha: render/logo_probe
    (Analyze, average) -> render/logo_alpha (TOP to CHOP), every frame.

    1.0.0 read the image back with numpyArray() at most every 60 frames, so
    right after load it saw the not-yet-cooked logo as absent, showed the
    name-only fallback, then jumped to logo_and_name about a second later.
    The quarantine validator caught it ('hit bounded' / 'reset clears')."""
    probe = parent().op('logo_alpha')
    c = probe['a'] if probe is not None else None
    return c is not None and c.eval() > 1e-4


def Mode():
    mode = Brand('mode', 'logo_and_name').strip().lower()
    if mode not in MODES:
        mode = 'logo_and_name'
    if mode != 'name' and not LogoPresent():
        mode = 'name'                  # no logo: fall back to the name
    return mode


def Align():
    p = _root().par.Placement.eval()
    return 'left' if p.endswith('left') else 'right' if p.endswith('right') else 'center'


def Size():
    img = _root().op('in0_image')
    w, h = img.width, img.height
    if w < 2 or h < 2:
        w, h = _root().par.Outputwidth.eval(), _root().par.Outputheight.eval()
    return w, h


def _compute():
    root = _root()
    w, h = Size()
    aspect = float(w) / float(h)
    scale = max(0.0, _num('scale', 1.0))
    safe = float(root.par.Safearea.eval())
    place = root.par.Placement.eval()
    mode = Mode()
    name = Brand('displayName', '').strip()
    sub = Brand('subtitle', '').strip()

    logo_h = float(root.par.Logosize.eval()) * scale if mode != 'name' else 0.0
    if logo_h > 0:
        lt = root.op('in3_logo')
        logo_w = logo_h * (float(lt.width) / max(1.0, float(lt.height)))
    else:
        logo_w = 0.0
    name_h = float(root.par.Textsize.eval()) * scale if (mode != 'logo' and name) else 0.0
    name_w = name_h * NAME_ASPECT
    sub_h = 0.45 * name_h if (name_h > 0 and sub) else 0.0
    sub_w = sub_h * SUB_ASPECT
    gap1 = 0.2 * name_h if (logo_h > 0 and name_h > 0) else 0.0
    gap2 = 0.15 * name_h if sub_h > 0 else 0.0

    total_h = logo_h + gap1 + name_h + gap2 + sub_h
    box_w = max(logo_w, name_w, sub_w)

    # shrink to fit the safe area if needed
    room_w, room_h = aspect - 2 * safe, 1.0 - 2 * safe
    k = 1.0
    if box_w > room_w > 0:
        k = min(k, room_w / box_w)
    if total_h > room_h > 0:
        k = min(k, room_h / total_h)
    logo_h, logo_w, name_h, name_w, sub_h, sub_w, gap1, gap2, total_h, box_w = [
        v * k for v in (logo_h, logo_w, name_h, name_w, sub_h, sub_w, gap1, gap2, total_h, box_w)]

    if place.endswith('left'):
        x0 = safe
    elif place.endswith('right'):
        x0 = aspect - safe - box_w
    else:
        x0 = (aspect - box_w) / 2.0
    if place.startswith('top'):
        top = 1.0 - safe
    elif place.startswith('bottom'):
        top = safe + total_h
    else:
        top = 0.5 + total_h / 2.0

    align = Align()

    def rect(ew, eh, ytop):
        if ew <= 0 or eh <= 0:
            return (0.0, 0.0, 0.0, 0.0)
        if align == 'left':
            ex = x0
        elif align == 'right':
            ex = x0 + box_w - ew
        else:
            ex = x0 + (box_w - ew) / 2.0
        return (ex / aspect, ytop - eh, (ex + ew) / aspect, ytop)

    y = top
    r_logo = rect(logo_w, logo_h, y)
    y -= logo_h + gap1
    r_name = rect(name_w, name_h, y)
    y -= name_h + gap2
    r_sub = rect(sub_w, sub_h, y)

    return {
        'logo': r_logo, 'name': r_name, 'sub': r_sub,
        'name_px': max(8, int(round(name_h * h))),
        'sub_px': max(8, int(round(sub_h * h))),
        'mode': mode, 'size': (w, h),
    }


def Layout():
    f = absTime.frame
    if _cache['frame'] != f or _cache['value'] is None:
        _cache['value'] = _compute()
        _cache['frame'] = f
    return _cache['value']


def R(which, i):
    return Layout()[which][i]


def Params(i):
    root = _root()
    k = float(root.par.Intensity.eval()) * max(0.0, min(1.0, _num('opacity', 1.0)))
    mo = root.op('motion')
    c = mo['brand_pulse'] if mo is not None else None
    pulse = c.eval() if c is not None else 0.0
    return (
        float(root.par.Logoopacity.eval()) * k,
        float(root.par.Nameopacity.eval()) * k,
        float(root.par.Backing.eval()),
        1.0 + 1.5 * pulse,             # restrained emphasis
    )[i]


def Visible():
    return bool(_root().par.Moduleactive.eval()) and (Params(0) > 0 or Params(1) > 0)
'''

SHADER = r'''
// clean_lockup: places logo, name and subtitle over the image with a soft
// legibility backing. Rects are (x0, y0, x1, y1) in uv; zero area = hidden.
uniform vec4 uLogo;
uniform vec4 uName;
uniform vec4 uSub;
uniform vec4 uColA;     // name colour (brand primaryColor)
uniform vec4 uColB;     // subtitle colour (brand secondaryColor)
uniform vec4 uParams;   // x logo alpha, y text alpha, z backing, w emphasis

layout(location = 0) out vec4 fragColor;

vec4 placed(sampler2D s, vec4 r, vec2 uv)
{
    if (r.z <= r.x || r.w <= r.y)
        return vec4(0.0);
    vec2 t = (uv - r.xy) / (r.zw - r.xy);
    if (t.x < 0.0 || t.y < 0.0 || t.x > 1.0 || t.y > 1.0)
        return vec4(0.0);
    return texture(s, t);
}

float cover(vec2 uv)
{
    return max(placed(sTD2DInputs[1], uLogo, uv).a * uParams.x,
           max(placed(sTD2DInputs[2], uName, uv).a,
               placed(sTD2DInputs[3], uSub, uv).a) * uParams.y);
}

void main()
{
    vec2 uv = vUV.st;
    vec4 base = texture(sTD2DInputs[0], uv);
    float aspect = uTDOutputInfo.res.z / uTDOutputInfo.res.w;

    // soft backing: widest coverage over a ring of 8 taps
    float sr = 0.006;
    float shadow = 0.0;
    for (int i = 0; i < 8; i++) {
        float ang = 6.2831853 * float(i) / 8.0;
        vec2 o = vec2(cos(ang) * sr / aspect, sin(ang) * sr);
        shadow = max(shadow, cover(uv + o));
    }
    vec3 rgb = base.rgb * (1.0 - 0.7 * uParams.z * shadow);

    float e = uParams.w;
    vec4 lg = placed(sTD2DInputs[1], uLogo, uv) * uParams.x;   // premultiplied
    rgb = lg.rgb * e + rgb * (1.0 - lg.a);

    float na = placed(sTD2DInputs[2], uName, uv).a * uParams.y;
    rgb = uColA.rgb * e * na + rgb * (1.0 - na);

    float sa = placed(sTD2DInputs[3], uSub, uv).a * uParams.y;
    rgb = uColB.rgb * e * sa + rgb * (1.0 - sa);

    fragColor = TDOutputSwizzle(vec4(clamp(rgb, 0.0, 1.0), base.a));
}
'''

layout = render.create(textDAT, 'layout')
place(layout, 0, 500)
layout.text = LAYOUT

shader = render.create(textDAT, 'lockup_shader')
place(shader, 300, 500)
shader.text = SHADER

in_image = render.create(inTOP, 'in_image')
place(in_image, 0, 200)
in_logo = render.create(inTOP, 'in_logo')
place(in_logo, 0, -100)

# per-frame "is there a logo" probe: average alpha, downloaded as one value
logo_probe = render.create(analyzeTOP, 'logo_probe')
place(logo_probe, 0, -400)
logo_probe.inputConnectors[0].connect(in_logo)
logo_probe.par.op = 'average'
logo_alpha = render.create(toptoCHOP, 'logo_alpha')
place(logo_alpha, 300, -400)
logo_alpha.par.top = 'logo_probe'
# immediate, not nextframe: under lazy cooking a probe nobody read last frame
# would return a stale value on its first read. One pixel, so it is cheap.
logo_alpha.par.downloadtype = 'immediate'


def text_top(name, aspect, px_key, x, y):
    t = render.create(textTOP, name)
    place(t, x, y)
    t.par.outputresolution = 'custom'
    t.par.resmult = False
    t.par.resolutionh.expr = "op('layout').module.Layout()['%s']" % px_key
    t.par.resolutionw.expr = "int(op('layout').module.Layout()['%s'] * %r)" % (px_key, aspect)
    t.par.fontautosize = 'fitiffat'    # long names shrink instead of clipping
    menu_pick(t.par.fontsizexunit, 'px', 'pixels', 'pixel')
    t.par.keepfontratio = True
    t.par.fontsizex.expr = "op('layout').module.Layout()['%s'] * 0.78" % px_key
    t.par.alignx.expr = "op('layout').module.Align()"
    t.par.aligny = 'center'
    t.par.fontcolorr = t.par.fontcolorg = t.par.fontcolorb = 1
    t.par.fontalpha = 1
    t.par.bgalpha = 0
    return t


name_text = text_top('name_text', 8.0, 'name_px', 300, 100)
name_text.par.text.expr = "op('layout').module.Brand('displayName', '')"
name_text.par.bold = True

sub_text = text_top('sub_text', 16.0, 'sub_px', 300, -250)
sub_text.par.text.expr = "op('layout').module.Brand('subtitle', '')"

# GLSL TOP takes at most three inputs; four are needed, so GLSL Multi TOP
# (same pixel shader / Vectors / Arrays parameters, unlimited inputs).
fx = render.create(glslmultiTOP, 'lockup_fx')
place(fx, 700, 0)
for i, src in enumerate((in_image, in_logo, name_text, sub_text)):
    # a multi-input op only shows one spare connector at a time
    if i < len(fx.inputConnectors):
        fx.inputConnectors[i].connect(src)
    else:
        src.outputConnectors[0].connect(fx)
got = [o.name for o in fx.inputs]
if got != ['in_image', 'in_logo', 'name_text', 'sub_text']:
    raise RuntimeError('lockup_fx inputs are %s' % got)
fx.par.pixeldat = 'lockup_shader'
# output resolution stays at the default (first input), preserving the image size

VECS = [
    ('uLogo',   ["op('layout').module.R('logo', %d)" % i for i in range(4)]),
    ('uName',   ["op('layout').module.R('name', %d)" % i for i in range(4)]),
    ('uSub',    ["op('layout').module.R('sub', %d)" % i for i in range(4)]),
    ('uColA',   ["op('layout').module.Color('primaryColor', (1.0, 0.82, 0.1, 1.0))[%d]" % i for i in range(4)]),
    ('uColB',   ["op('layout').module.Color('secondaryColor', (0.1, 0.35, 1.0, 1.0))[%d]" % i for i in range(4)]),
    ('uParams', ["op('layout').module.Params(%d)" % i for i in range(4)]),
]
fx.seq.vec.numBlocks = len(VECS)
for b, (uni, exprs) in enumerate(VECS):
    getattr(fx.par, 'vec%dname' % b).val = uni
    for comp, e in zip('xyzw', exprs):
        getattr(fx.par, 'vec%dvalue%s' % (b, comp)).expr = e

sw = render.create(switchTOP, 'out_switch')
place(sw, 1000, 0)
sw.inputConnectors[0].connect(fx)
sw.inputConnectors[1].connect(in_image)
sw.par.index.expr = "0 if op('layout').module.Visible() else 1"

rout = render.create(outTOP, 'out1')
place(rout, 1300, 0)
rout.inputConnectors[0].connect(sw)

# render's In TOPs sort as in_image, in_logo -> connectors 0, 1
render.inputConnectors[0].connect(img_in)
render.inputConnectors[1].connect(logo_in)

out1 = m.create(outTOP, 'out1')
place(out1, 1100, 0)
out1.inputConnectors[0].connect(render.outputConnectors[0])

# ------------------------------------------------ thumbnail background
bg = ROOT.create(constantTOP, BG)
bg.nodeX, bg.nodeY = 9200, -1800
bg.par.outputresolution = 'custom'
bg.par.resmult = False
bg.par.resolutionw = 640
bg.par.resolutionh = 360
bg.par.colorr, bg.par.colorg, bg.par.colorb = 0.06, 0.06, 0.09
bg.par.alpha = 1
demo = ROOT.create(tableDAT, DEMO)
demo.nodeX, demo.nodeY = 9200, -2200
demo.clear()
for r in DEMO_ROWS:
    demo.appendRow(r)
m.inputConnectors[0].connect(bg)
m.inputConnectors[2].connect(demo)
m.inputConnectors[3].connect(ROOT.op('LOGO'))

print('clean_lockup network built in', m.path, '- finishing in a few frames...')

STAGE = '''
import os
b = op(%(build)r)
fx = b.op('render/lockup_fx')
out = b.op('out1')
lay = b.op('render/layout').module
out.cook(force=True)
err = fx.errors()
L = lay.Layout()
print('  shader            ' + (err or 'compiled, no errors'))
if fx.warnings():
    print('  shader warnings   ' + fx.warnings())
print('  layout            mode=%%s size=%%dx%%d logo=%%s name=%%s'
      %% (L['mode'], L['size'][0], L['size'][1],
         tuple(round(v, 3) for v in L['logo']), tuple(round(v, 3) for v in L['name'])))
print('  name text         %%dx%%d' %% (b.op('render/name_text').width, b.op('render/name_text').height))
print('  switch            %%s (0 = lockup shown)' %% b.op('render/out_switch').par.index.eval())
if err or L['mode'] != 'logo_and_name':
    print('FAIL expected a compiled shader and mode logo_and_name; leaving %%s for inspection' %% b.path)
else:
    out.save(%(thumb)r)
    for i in (0, 2, 3):
        b.inputConnectors[i].disconnect()
    b.save(%(tox)r)
    ok = os.path.isfile(%(tox)r) and os.path.isfile(%(thumb)r)
    for f in (%(tox)r, %(thumb)r):
        print('  wrote', f, os.path.getsize(f) if os.path.isfile(f) else 'MISSING')
    if ok:
        b.destroy()
        op(%(bg)r).destroy()
        op(%(demo)r).destroy()
        print('clean_lockup exported; build COMPs removed')
        print('next: load it in brand_host (see CLAUDE.md, Block 5)')
    else:
        print('FAIL export incomplete; leaving', b.path, 'for inspection')
'''

if not os.path.isdir(MODULE_DIR):
    os.makedirs(MODULE_DIR)

run(STAGE % {'build': m.path, 'bg': bg.path, 'demo': demo.path, 'tox': TOX, 'thumb': THUMB},
    delayFrames=10)
