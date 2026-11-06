"""Builds the four-slot stack and the /output safety stage.

Run inside TouchDesigner's textport (Alt+T), after build_brand_source.py:

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_module_host.py').read())

    MOTION_OUT -> every host's in1_motion, and output's
    module_host -> hit_host -> brand_host -> finish_host -> output -> OUTPUT
    (base_scene)   (hit_fx)   (brand_overlay) (finish_fx)  (safety)  (Null TOP)
    BRAND -> brand_host in3_brand     LOGO -> brand_host in4_logo

module_host is the Block 2 wrapper; hit_host (Block 4), brand_host (Block 5)
and finish_host (Block 6) are the same wrapper in later slots, each taking the
previous host's output as its image. output is not a module slot: it is the
runtime's own final safety stage, and OUTPUT is the one terminal a display
reads.

Re-running destroys and rebuilds every host COMP, so it is safe to run repeatedly;
each carries its Modulepath and Moduletype across rebuilds. Because a rebuild
reloads nothing, pulse Load on each host afterwards.

Contract: docs/SCENE_MODULE_SPEC.md sections 9 (standard parameters),
10 (slot connector order) and 12 (lifecycle).
"""

ROOT = op('/project1')

# Lifecycle logic baked into each host's 'host' Text DAT. Kept at top level so
# its indentation is exactly what the DAT receives.
HOST_LOGIC = '''
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
        # externaltox makes this COMP *be* the tox root. loadTox is a fallback
        # because it can nest the tox as a child instead of replacing contents.
        m.par.externaltox = path
        m.par.enableexternaltox = True
        m.par.enableexternaltoxpulse.pulse()
        if m.op('out1') is None:
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

    # Spec s12 steps 6-7: warm the module before wiring its output and
    # validating. An external tox initialises late, so both outputConnectors
    # and out1's resolution read stale if queried right now.
    _status('loading')
    run("op('%s').module.Finish()" % me.path, delayFrames=2)


def Finish():
    h = _host()
    m = Module()
    if m:
        # a COMP is not a valid source; connect to its output connector
        outs = m.outputConnectors
        if outs:
            h.op('module_null').inputConnectors[0].connect(outs[0])
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

    # keep module_null fed so an idle host shows no error badge
    mn = h.op('module_null')
    if not Module() and not mn.inputConnectors[0].connections:
        mn.inputConnectors[0].connect(h.op('black'))

    live = bool(Module()) and bool(h.par.Moduleactive.eval())
    h.op('out_switch').par.index = 0 if live else 1


def Validate():
    m = Module()
    if not m:
        return 'error: module did not load'
    out = m.op('out1')
    if out is None:
        kids = ','.join(c.name for c in m.children) or 'none'
        return 'error: no out1 (children: %s)' % kids
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

HOST_PAREXEC = '''
def onValueChange(par, prev):
    op('host').module.OnValueChange(par)
    return

def onPulse(par):
    op('host').module.OnPulse(par)
    return
'''


def build_host(name, x, y, default_type, image_src=None, extra=None):
    """Destroy and rebuild one wrapper. image_src feeds in0_image (a COMP is
    connected through its output connector, never as a direct source).
    extra maps a host input index to a plain operator, e.g. {3: BRAND}."""
    existing = ROOT.op(name)
    carried = {}
    if existing:
        for nm in ('Modulepath', 'Moduletype'):
            p = getattr(existing.par, nm, None)
            if p is not None:
                carried[nm] = p.eval()
        existing.destroy()

    host = ROOT.create(baseCOMP, name)
    host.nodeX, host.nodeY = x, y
    host.nodeWidth, host.nodeHeight = 900, 300

    # ------------------------------------------------------------ inputs
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
    black.par.colorr = 0
    black.par.colorg = 0
    black.par.colorb = 0
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

    # -------------------------------------------------------- parameters
    page = host.appendCustomPage('Module')

    p = page.appendFile('Modulepath')[0]
    p.default = ''

    p = page.appendMenu('Moduletype')[0]
    p.menuNames = ['base_scene', 'hit_fx', 'brand_overlay', 'finish_fx']
    p.menuLabels = ['Base Scene', 'Hit FX', 'Brand Overlay', 'Finish FX']
    p.default = default_type
    p.val = default_type

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

    # ------------------------------------------------------------- logic
    logic = host.create(textDAT, 'host')
    logic.nodeX, logic.nodeY = 0, -1600
    logic.text = HOST_LOGIC

    pe = host.create(parameterexecuteDAT, 'host_parexec')
    pe.nodeX, pe.nodeY = 400, -1600
    pe.par.op = host
    pe.par.pars = '*'
    pe.par.custom = True
    pe.par.builtin = False
    pe.par.valuechange = True
    pe.par.onpulse = True
    pe.par.active = True
    pe.text = HOST_PAREXEC

    for nm, value in carried.items():
        getattr(host.par, nm).val = value

    # ----------------------------------------------------- host wiring
    motion = ROOT.op('MOTION_OUT')
    if motion:
        host.inputConnectors[1].connect(motion)
    if image_src is not None:
        host.inputConnectors[0].connect(image_src.outputConnectors[0])
    for index, src in (extra or {}).items():
        host.inputConnectors[index].connect(src)

    host.op('host').module.Refresh()

    print('%s built at %s' % (name, host.path))
    try:
        conns = host.inputConnectors
        print('  type          :', host.par.Moduletype.eval())
        print('  image wired   :', bool(conns[0].connections),
              '(from %s)' % image_src.name if image_src is not None else '')
        print('  motion wired  :', bool(conns[1].connections) if len(conns) > 1 else False)
        for index, src in (extra or {}).items():
            print('  input %d wired :' % index, bool(conns[index].connections), '(from %s)' % src.name)
        print('  Modulepath    :', host.par.Modulepath.eval() or '(none)')
        print('  status        :', host.par.Status.eval())
    except Exception as e:
        print('  (diagnostics unavailable: %s)' % e)
    return host


base_host = build_host('module_host', 6400, 0, 'base_scene')
hit_host = build_host('hit_host', 8000, 0, 'hit_fx', image_src=base_host)

# brand_overlay takes prepared brand data (spec s8.2, s10.3). Host inputs 3
# and 4 are in3_brand and in4_logo; they reach the module as its connectors 2
# and 3 through WIRING. BRAND/LOGO come from build_brand_source.py until the
# branding runtime exists.
brand_extra = {}
if ROOT.op('BRAND') is not None:
    brand_extra[3] = ROOT.op('BRAND')
if ROOT.op('LOGO') is not None:
    brand_extra[4] = ROOT.op('LOGO')
if 3 not in brand_extra:
    print('WARNING no /project1/BRAND - run build_brand_source.py, then rebuild')
brand_host = build_host('brand_host', 9600, 0, 'brand_overlay',
                        image_src=hit_host, extra=brand_extra)
finish_host = build_host('finish_host', 11200, 0, 'finish_fx', image_src=brand_host)

# ------------------------------------------------------------------ /output
# Final hardware safety, after every module and never bypassed
# (SCENE_MODULE_SPEC s10.4: finish modules must not bypass it). It owns what
# no module may be trusted with: NaN/Inf removal, a hard 0..1 clamp, the
# blackout_gate lane, a manual blackout and a brightness ceiling for the
# projector. Display routing (a Window COMP) comes later.
OUTPUT_SHADER = r'''
// /output safety stage. Runs on every frame that leaves the runtime.
uniform vec4 uSafety;   // x blackout_gate, y Maxbrightness, z manual blackout (1 = black)

layout(location = 0) out vec4 fragColor;

void main()
{
    vec4 c = texture(sTD2DInputs[0], vUV.st);
    vec3 rgb = c.rgb;
    // NaN/Inf to black: comparisons with NaN are false, so test explicitly
    if (any(isnan(rgb)) || any(isinf(rgb)))
        rgb = vec3(0.0);
    float gain = clamp(uSafety.x, 0.0, 1.0) * clamp(uSafety.y, 0.0, 1.0)
               * (1.0 - clamp(uSafety.z, 0.0, 1.0));
    rgb = clamp(rgb, 0.0, 1.0) * gain;
    fragColor = TDOutputSwizzle(vec4(rgb, 1.0));
}
'''


def build_output(src_host):
    keep = {}
    old = ROOT.op('output')
    if old is not None:
        for nm in ('Maxbrightness', 'Blackout'):
            p = getattr(old.par, nm, None)
            if p is not None:
                keep[nm] = p.eval()
        old.destroy()
    for nm in ('OUTPUT',):
        o = ROOT.op(nm)
        if o is not None:
            o.destroy()

    out = ROOT.create(baseCOMP, 'output')
    out.nodeX, out.nodeY = 12800, 0
    out.nodeWidth, out.nodeHeight = 900, 300

    page = out.appendCustomPage('Output')
    p = page.appendFloat('Maxbrightness', label='Max Brightness')[0]
    p.default = 1
    p.normMin, p.normMax = 0, 1
    p.min, p.max = 0, 1
    p.clampMin = p.clampMax = True
    p.val = keep.get('Maxbrightness', 1)
    p = page.appendToggle('Blackout')[0]
    p.default = 0
    p.val = keep.get('Blackout', 0)

    img = out.create(inTOP, 'in0_image')
    img.nodeX, img.nodeY = 0, 0
    mot = out.create(inCHOP, 'in1_motion')
    mot.nodeX, mot.nodeY = 0, -300

    shader = out.create(textDAT, 'safety_shader')
    shader.nodeX, shader.nodeY = 300, 300
    shader.text = OUTPUT_SHADER

    fx = out.create(glslTOP, 'safety')
    fx.nodeX, fx.nodeY = 300, 0
    fx.inputConnectors[0].connect(img)
    fx.par.pixeldat = 'safety_shader'
    fx.seq.vec.numBlocks = 1
    fx.par.vec0name = 'uSafety'
    # blackout_gate defaults to 1 when the motion input or lane is absent
    fx.par.vec0valuex.expr = ("op('in1_motion')['blackout_gate'].eval() "
                              "if op('in1_motion')['blackout_gate'] is not None else 1")
    fx.par.vec0valuey.expr = 'parent().par.Maxbrightness'
    fx.par.vec0valuez.expr = 'parent().par.Blackout'

    o1 = out.create(outTOP, 'out1')
    o1.nodeX, o1.nodeY = 600, 0
    o1.inputConnectors[0].connect(fx)

    out.inputConnectors[0].connect(src_host.outputConnectors[0])
    motion = ROOT.op('MOTION_OUT')
    if motion is not None:
        out.inputConnectors[1].connect(motion)

    term = ROOT.create(nullTOP, 'OUTPUT')
    term.nodeX, term.nodeY = 14400, 0
    term.nodeWidth, term.nodeHeight = 900, 300
    term.inputConnectors[0].connect(out.outputConnectors[0])

    print('output built at %s -> %s' % (out.path, term.path))
    print('  image from    :', [c.owner.name for c in out.inputConnectors[0].connections])
    print('  motion wired  :', bool(out.inputConnectors[1].connections))
    print('  Maxbrightness :', out.par.Maxbrightness.eval(), ' Blackout:', out.par.Blackout.eval())
    return out


build_output(finish_host)
print('pulse Load on each host to (re)load its module')
