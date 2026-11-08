"""Builds the look runtime: the second stack's mixer and the look bank.

Run inside TouchDesigner's textport (Alt+T), after build_module_host.py:

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_look_runtime.py').read())

HYBRID_RUNTIME_ARCHITECTURE "Stack Model" / SCENE_MODULE_SPEC s12: a scene
change never rebuilds the picture that is on screen. Two stacks hold the
picture layers of a look (base_scene + hit_fx); one is live, the other is
loaded with the next look, warmed, then crossfaded in.

    stack A: module_host   -> hit_host   --+
    stack B: module_host_b -> hit_host_b --+-- look_cross / look_switch -> LOOK_OUT
                                                 -> brand_host -> finish_host -> output

    PALETTE (live selection) --+-- look_pal_a -> PALETTE_A -> stack A
                 look_frozen_a +
                (same for B)

A look = Scene and Hits (module, on/off, intensity, controls), palette and
background colour (the owner's choice, 2026-11-07). The name, finish, output
safety and performance faders are show-wide and never move on a TAKE. During
a fade the outgoing stack reads a frozen copy of its palette while the
incoming one reads the live selection, so each keeps its own colours.

look_switch picks one stack while idle, so the parked stack never cooks;
only during a fade do both render (look_cross).

/project1/looks holds the parameters and the logic:
    Activestack  a/b - which stack is on screen
    Mix          0..1 - how much of stack B is shown (driven during a fade)
    Transitiontime, Quantize (now / beat / bar) - TAKE defaults
    Phase        idle / loading / armed / fading
    Version      bumped on every change, so the control bridge rebroadcasts

TAKE: load the look into the idle stack (only approved modules, through the
scene library's LoadApproved), force-cook it for a few frames (nothing views
it, and TouchDesigner cooks lazily), then wait for the next beat or bar -
at most 4 s, so a TAKE without music still happens - crossfade, swap.

Re-running keeps the look bank, the remembered controls, the active stack
and the transition settings.
"""

ROOT = op('/project1')
NAME = 'looks'

LOOK_LOGIC = r'''
# Look runtime. See build_look_runtime.py.
import json
import os

SLOTS = ('base_scene', 'hit_fx')
HOSTS = {'a': {'base_scene': 'module_host', 'hit_fx': 'hit_host'},
         'b': {'base_scene': 'module_host_b', 'hit_fx': 'hit_host_b'}}
BANK_SIZE = 16
QUANTIZE = ('now', 'beat', 'bar')
WARM_FRAMES = 8          # host Finish() runs 2 frames after Load; then warm
ARM_TIMEOUT = 4.0        # seconds to wait for a beat or bar before going anyway
R = op('/project1')


class LookError(Exception):
    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


def _c():
    return parent()


def _st(key, default):
    v = _c().fetch(key, None)
    if v is None:
        v = default
        _c().store(key, v)
    return v


def _bump():
    _c().par.Version = int(_c().par.Version.eval()) + 1


def _phase(t, ph, **fields):
    # Phase is a plain parameter, set here, so look_switch (whose index reads
    # it) re-cooks the moment it changes; an expression reading storage would
    # give TouchDesigner no dependency to follow.
    t.update(phase=ph, **fields)
    _c().par.Phase = ph
    _bump()


# ------------------------------------------------------------- stacks
def Active():
    return _c().par.Activestack.eval()


def Inactive():
    return 'b' if Active() == 'a' else 'a'


def ActiveHost(slot):
    """The host on screen for a picture slot; None for brand_overlay/finish_fx."""
    return HOSTS[Active()].get(slot)


def _module_id(host):
    h = R.op(host)
    if h is None or h.op('module') is None:
        return None
    path = h.par.Modulepath.eval()
    try:
        with open(os.path.join(os.path.dirname(path), 'module.json'), 'r', encoding='utf-8') as f:
            return json.load(f).get('id')
    except (OSError, ValueError):
        return None


def Controls(host):
    """Control values set from the frontend for the module in a host."""
    return _st('controls', {}).setdefault(host, {})


def ClearControls(host):
    _st('controls', {})[host] = {}


def _apply_controls(host, controls):
    m = R.op(host).op('module') if R.op(host) is not None else None
    applied = {}
    if m is None:
        return applied
    for name, value in (controls or {}).items():
        if isinstance(value, list):
            pars = [getattr(m.par, name + c, None) for c in 'rgb']
            if all(p is not None for p in pars) and len(value) == 3:
                for p, v in zip(pars, value):
                    p.val = v
                applied[name] = value
            continue
        p = getattr(m.par, name, None)
        if p is None:
            continue
        if p.isMenu and value not in p.menuNames:
            continue
        p.val = value
        applied[name] = value
    return applied


# --------------------------------------------------------------- bank
def Bank():
    b = _st('bank', [None] * BANK_SIZE)
    if len(b) < BANK_SIZE:
        b.extend([None] * (BANK_SIZE - len(b)))
    return b


def SetBank(entries):
    b = Bank()
    for i in range(BANK_SIZE):
        b[i] = entries[i] if i < len(entries) else None
    t = Take_state()
    if t.get('current') is not None and b[t['current']] is None:
        t['current'] = None              # the look on screen is no longer in the bank
    _bump()


def Capture():
    """The look on screen: Scene + Hits, palette, background."""
    slots = {}
    for slot in SLOTS:
        host = ActiveHost(slot)
        h = R.op(host)
        slots[slot] = {'module': _module_id(host),
                       'enabled': bool(h.par.Moduleactive.eval()) if h is not None else True,
                       'intensity': round(float(h.par.Intensity.eval()), 4) if h is not None else 1.0,
                       'controls': dict(Controls(host))}
    ps = R.op('palette_source')
    palette, background = None, None
    if ps is not None:
        palette = ps.op('palette_logic').module.Selected()[0]
        if ps.par.Backgroundoverride.eval():
            background = [round(float(getattr(ps.par, 'Backgroundcolor' + c).eval()), 4) for c in 'rgb']
    return {'slots': slots, 'palette': palette, 'background': background}


def SaveLook(index, name):
    Bank()[index] = {'name': name, 'look': Capture()}
    _bump()


def DeleteLook(index):
    Bank()[index] = None
    t = Take_state()
    if t.get('current') == index:
        t['current'] = None
    _bump()


def RenameLook(index, name):
    b = Bank()
    if b[index] is None:
        raise LookError('bad_field', 'look %d is empty' % (index + 1))
    b[index]['name'] = name
    _bump()


# ------------------------------------------------------------ palette
def _freeze(stack):
    """Copy the live palette into the stack's own table and read that."""
    live, frozen = R.op('PALETTE'), R.op('look_frozen_' + stack)
    if live is not None and frozen is not None:
        frozen.clear()
        for r in range(live.numRows):
            frozen.appendRow([c.val for c in live.row(r)])
    setattr(_c().par, 'Frozen' + stack, 1)


def _thaw(stack):
    setattr(_c().par, 'Frozen' + stack, 0)


def _select_palette(look, problems):
    ps = R.op('palette_source')
    if ps is None:
        return
    name = look.get('palette')
    if name:
        lib = ps.op('library')
        names = [lib[r, 0].val for r in range(1, lib.numRows)]
        if name in names:
            ps.par.Paletteindex = names.index(name)
        else:
            problems.append('palette %r is not installed - kept the current one' % name)
    bg = look.get('background')
    if bg:
        for comp, v in zip('rgb', bg):
            getattr(ps.par, 'Backgroundcolor' + comp).val = v
    ps.par.Backgroundoverride = bool(bg)


# --------------------------------------------------------------- TAKE
def Take_state():
    return _st('take', {'phase': 'idle', 'index': None, 'current': None})


def Transition():
    return {'fade': round(float(_c().par.Transitiontime.eval()), 3), 'quantize': _c().par.Quantize.eval()}


def SetTransition(fade=None, quantize=None):
    if fade is not None:
        _c().par.Transitiontime = fade
    if quantize is not None:
        _c().par.Quantize = quantize
    _bump()


def Take(index, fade=None, quantize=None):
    """Start a TAKE of bank entry `index`. Raises LookError on refusal."""
    entry = Bank()[index]
    if entry is None:
        raise LookError('empty_look', 'look %d is empty - save one there first' % (index + 1))
    t = Take_state()
    if t['phase'] == 'loading':
        raise LookError('busy', 'a look is still loading - try again in a moment')
    if t['phase'] == 'fading':
        _complete()                      # a new TAKE mid-fade: finish this one now
    look = entry['look']
    lib = R.op('/project1/scene_library/library')
    if lib is None:
        raise LookError('failed', 'no scene library - run build_scene_library.py')
    lib = lib.module
    for slot in SLOTS:
        mid = (look['slots'].get(slot) or {}).get('module')
        if mid and not lib.IsApproved(mid):
            raise LookError('not_approved', '%s in look %d is not approved for its current version' % (mid, index + 1))
    if t['phase'] == 'armed':            # replace a TAKE still waiting for its beat
        _phase(t, 'idle')
    target = Inactive()
    problems = []
    _freeze(Active())                    # outgoing look keeps its colours
    _select_palette(look, problems)      # the live selection becomes the new look's
    _thaw(target)
    for slot in SLOTS:
        s = look['slots'].get(slot) or {}
        host = HOSTS[target][slot]
        h = R.op(host)
        if h is None:
            raise LookError('failed', 'no %s - run build_module_host.py' % host)
        mid = s.get('module')
        if mid is None:
            h.par.Unload.pulse()
        elif _module_id(host) == mid:
            h.par.Reset.pulse()          # already loaded there: reuse, fresh state
        elif not lib.LoadApproved(host, mid):
            raise LookError('failed', 'could not load %s into %s' % (mid, host))
        ClearControls(host)
    _phase(t, 'loading', index=index, target=target, frames=0, problems=problems,
           fade=float(Transition()['fade'] if fade is None else fade),
           quantize=Transition()['quantize'] if quantize is None else quantize,
           look=look, armed=None, start=None, progress=0.0)


def _cook_inactive():
    h = R.op(HOSTS[Inactive()]['hit_fx'])
    o = h.op('out1') if h is not None else None
    if o is not None:
        o.cook(force=True)


def _phase_now(prev):
    """(beat wrapped, bar wrapped) since the previous frame."""
    mo, ei = R.op('MOTION_OUT'), R.op('ENGINE_INPUT')
    beat = mo['sync_phase'].eval() if mo is not None and mo['sync_phase'] is not None else None
    bar = ei['bar_phase'].eval() if ei is not None and ei['bar_phase'] is not None else None
    wrapped = lambda a, b: a is not None and b is not None and a - b > 0.5
    out = (wrapped(prev.get('beat'), beat), wrapped(prev.get('bar'), bar))
    prev['beat'], prev['bar'] = beat, bar
    return out


def Frame():
    t = Take_state()
    prev = _st('phase_prev', {})
    beat, bar = _phase_now(prev)
    ph = t['phase']
    if ph == 'idle':
        return
    if ph == 'loading':
        _cook_inactive()
        t['frames'] += 1
        if t['frames'] == 3:             # hosts have run Finish(): set the look's values
            for slot in SLOTS:
                s = t['look']['slots'].get(slot) or {}
                host = HOSTS[t['target']][slot]
                h = R.op(host)
                h.par.Moduleactive = bool(s.get('enabled', True))
                h.par.Intensity = float(s.get('intensity', 1.0))
                Controls(host).update(_apply_controls(host, s.get('controls')))
        if t['frames'] >= WARM_FRAMES:
            _phase(t, 'armed', armed=absTime.seconds)
        return
    if ph == 'armed':
        _cook_inactive()
        q = t['quantize']
        on_time = {'now': True, 'beat': beat, 'bar': bar if prev.get('bar') is not None else beat}[q]
        # without music the clock may stand still: never wait more than ARM_TIMEOUT
        if on_time or absTime.seconds - t['armed'] > ARM_TIMEOUT:
            if t['fade'] <= 0:
                _complete()
                return
            _phase(t, 'fading', start=absTime.seconds, progress=0.0)
        return
    if ph == 'fading':
        p = min(1.0, (absTime.seconds - t['start']) / t['fade'])
        t['progress'] = p
        _c().par.Mix = p if t['target'] == 'b' else 1.0 - p
        if p >= 1.0:
            _complete()


def _complete():
    t = Take_state()
    if t['phase'] == 'idle':
        return
    _c().par.Activestack = t['target']
    _c().par.Mix = 1.0 if t['target'] == 'b' else 0.0
    _phase(t, 'idle', current=t['index'], progress=1.0, look=None)


def State():
    t = Take_state()
    return {'phase': t['phase'], 'index': t.get('index'), 'current': t.get('current'),
            'progress': round(float(t.get('progress') or 0.0), 3), 'problems': list(t.get('problems') or []),
            'active': Active()}


# -------------------------------------------------------------- wiring
def Wire():
    """(Re)connect the stacks, palettes and mixer. Safe to call any time:
    after build_module_host.py, build_palette_source.py or this builder."""
    done = []
    pal, hit_a, hit_b = R.op('PALETTE'), R.op('hit_host'), R.op('hit_host_b')
    for stack in ('a', 'b'):
        sw = R.op('look_pal_' + stack)
        if sw is not None and pal is not None:
            sw.inputConnectors[0].connect(pal)
            sw.inputConnectors[1].connect(R.op('look_frozen_' + stack))
    for stack in ('a', 'b'):
        term = R.op('PALETTE_' + stack.upper())
        for slot in SLOTS:
            h = R.op(HOSTS[stack][slot])
            if h is not None and term is not None:
                h.inputConnectors[2].connect(term)
    base_b = R.op('module_host_b')
    if hit_b is not None and base_b is not None:
        hit_b.inputConnectors[0].connect(base_b.outputConnectors[0])
    cross, switch = R.op('look_cross'), R.op('look_switch')
    if hit_a is not None and hit_b is not None and cross is not None:
        cross.inputConnectors[0].connect(hit_a.outputConnectors[0])
        cross.inputConnectors[1].connect(hit_b.outputConnectors[0])
        switch.inputConnectors[0].connect(hit_a.outputConnectors[0])
        switch.inputConnectors[1].connect(hit_b.outputConnectors[0])
        switch.inputConnectors[2].connect(cross)
        done.append('mixer')
    brand = R.op('brand_host')
    if brand is not None and R.op('LOOK_OUT') is not None:
        brand.inputConnectors[0].connect(R.op('LOOK_OUT'))
        done.append('brand_host <- LOOK_OUT')
    return done
'''

FRAME_EXEC = r'''
def onFrameStart(frame):
    op('look_logic').module.Frame()
    return
'''


def menu(page, name, label, names, labels, value):
    p = page.appendMenu(name, label=label)[0]
    p.menuNames, p.menuLabels = names, labels
    p.default = names[0]
    p.val = value
    return p


def build():
    keep = {'bank': None, 'controls': None, 'take': None, 'Activestack': 'a',
            'Transitiontime': 2.0, 'Quantize': 'bar'}
    old = ROOT.op(NAME)
    if old is not None:
        for k in ('bank', 'controls'):
            keep[k] = old.fetch(k, None)
        t = old.fetch('take', None) or {}
        keep['take'] = {'phase': 'idle', 'index': None, 'current': t.get('current')}
        for k in ('Activestack', 'Transitiontime', 'Quantize'):
            p = getattr(old.par, k, None)
            if p is not None:
                keep[k] = p.eval()
        old.destroy()
    for nm in ('look_cross', 'look_switch', 'LOOK_OUT', 'look_pal_a', 'look_pal_b',
               'look_frozen_a', 'look_frozen_b', 'PALETTE_A', 'PALETTE_B'):
        o = ROOT.op(nm)
        if o is not None:
            o.destroy()

    c = ROOT.create(baseCOMP, NAME)
    c.nodeX, c.nodeY = 8800, -1600
    c.nodeWidth, c.nodeHeight = 900, 300
    page = c.appendCustomPage('Looks')
    menu(page, 'Activestack', 'Active Stack', ['a', 'b'], ['A', 'B'], keep['Activestack'])
    p = page.appendFloat('Mix', label='Mix (B amount)')[0]
    p.normMin, p.normMax = 0, 1
    p.val = 1.0 if keep['Activestack'] == 'b' else 0.0
    p = page.appendFloat('Transitiontime', label='Transition Time (s)')[0]
    p.default = 2.0
    p.normMin, p.normMax = 0, 10
    p.min, p.max = 0, 30
    p.clampMin = p.clampMax = True
    p.val = keep['Transitiontime']
    menu(page, 'Quantize', 'Start On', ['now', 'beat', 'bar'], ['Now', 'Next Beat', 'Next Bar'], keep['Quantize'])
    p = page.appendStr('Phase')[0]
    p.val = 'idle'                       # set by look_logic._phase()
    p = page.appendInt('Version')[0]
    p.val = 0
    for stack in ('a', 'b'):
        p = page.appendToggle('Frozen' + stack, label='Frozen Palette ' + stack.upper())[0]
        p.val = 0

    logic = c.create(textDAT, 'look_logic')
    logic.nodeX, logic.nodeY = 0, 0
    logic.text = LOOK_LOGIC
    fx = c.create(executeDAT, 'frame_exec')
    fx.nodeX, fx.nodeY = 300, 0
    fx.text = FRAME_EXEC
    fx.par.framestart = True
    fx.par.active = True
    for k in ('bank', 'controls', 'take'):
        if keep[k] is not None:
            c.store(k, keep[k])

    # mixer: one stack while idle (the other never cooks), both while fading
    cross = ROOT.create(crossTOP, 'look_cross')
    cross.nodeX, cross.nodeY = 9600, -1200
    cross.par.cross.expr = "op('looks').par.Mix"
    switch = ROOT.create(switchTOP, 'look_switch')
    switch.nodeX, switch.nodeY = 9600, -900
    switch.par.index.expr = ("2 if op('looks').par.Phase.eval() == 'fading' "
                             "else (1 if op('looks').par.Activestack.eval() == 'b' else 0)")
    out = ROOT.create(nullTOP, 'LOOK_OUT')
    out.nodeX, out.nodeY = 9900, -900
    out.inputConnectors[0].connect(switch)

    # per-stack palettes: live selection, or a frozen copy while fading out
    for i, stack in enumerate(('a', 'b')):
        frozen = ROOT.create(tableDAT, 'look_frozen_' + stack)
        frozen.nodeX, frozen.nodeY = 5600, -2200 - i * 600
        frozen.clear()
        frozen.appendRow(['role', 'r', 'g', 'b', 'a'])
        sw = ROOT.create(switchDAT, 'look_pal_' + stack)
        sw.nodeX, sw.nodeY = 5900, -2000 - i * 600
        sw.par.index.expr = "1 if op('looks').par.Frozen%s else 0" % stack
        term = ROOT.create(nullDAT, 'PALETTE_' + stack.upper())
        term.nodeX, term.nodeY = 6200, -2000 - i * 600
        term.inputConnectors[0].connect(sw)

    done = logic.module.Wire()
    print('look runtime built at %s' % c.path)
    print('  wired      :', ', '.join(done) or 'nothing - run build_module_host.py first')
    print('  active     : stack %s; transition %.1f s, start on %s' % (
        c.par.Activestack.eval().upper(), c.par.Transitiontime.eval(), c.par.Quantize.eval()))
    print('  looks saved:', sum(1 for x in logic.module.Bank() if x))
    missing = [n for n in ('module_host', 'hit_host', 'module_host_b', 'hit_host_b', 'brand_host', 'PALETTE')
               if ROOT.op(n) is None]
    if missing:
        print('WARNING missing:', ', '.join(missing))
    print('next: rebuild the control bridge (build_control_bridge.py) so the app can use looks')
    return c


build()
