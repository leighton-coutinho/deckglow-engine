"""Builds /project1/scene_library: discovery, quarantine validation, approval (Block 7).

Run inside TouchDesigner's textport (Alt+T), with engine_input_block1.toe open:

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_scene_library.py').read())

Then, one statement at a time:

    lib = op('/project1/scene_library/library').module
    lib.Scan()                      # discover modules/*/module.json, static checks
    lib.ValidateAll()               # quarantine every module, ~10 s each
    lib.Approve('com.deckglow.orb_burst')
    lib.LoadApproved('hit_host', 'com.deckglow.orb_burst')

Layers, after SCENE_MODULE_SPEC s15:

  s15.1 static   validate_static.py, embedded here as static_checks. Runs on
                 Scan(); also runs outside TouchDesigner.
  s15.2 interface  in quarantine: required In operators by name, family and
                 connector index; render and out1; standard and slot
                 parameters with the right style; menu tokens; reserved names;
                 every declared control matches a custom parameter on the
                 Controls page (type, default, range).
  s15.3 runtime  synthetic motion states drive the module: Idle (stable),
                 Drive (sweep), Hit (one bounded response), Sync (continuous
                 motion for base scenes), Dense (cook time, no operator
                 growth), Reset (state clears), Bypass (exact pass-through
                 for non-base slots). Frames are read back and checked for
                 NaN/Inf.
  s15.4 admission  output resolution matches the stack, nothing outside the
                 quarantine was created or destroyed, cook time is recorded,
                 and a module must be explicitly approved (per version) before
                 LoadApproved() will put it in a host.

Results: the LIBRARY and RESULTS tables, the textport, and one JSON report per
module in touchDesigner/validation/<folder>.json. Approvals are stored in
touchDesigner/library/approved.json, keyed by id and version, so a new version
needs re-approval.

Hosts' own Modulepath + Load still work for development; LoadApproved() is
the gated path.
"""

import os

ROOT = op('/project1')
NAME = 'scene_library'
STATIC_SRC = os.path.join(project.folder, 'tools', 'validate_static.py')

if not os.path.isfile(STATIC_SRC):
    raise RuntimeError('missing %s' % STATIC_SRC)


def menu_pick(par, *candidates):
    """Set a menu to the first candidate matching a token or a label."""
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


LANES = ['body_level', 'body_drift', 'impact_fast', 'impact_wide', 'impact_trigger',
         'sync_level', 'sync_phase', 'sync_sine', 'sync_triangle', 'sync_bar_env',
         'texture_level', 'texture_jitter', 'mood_warmth', 'mood_softness',
         'brand_pulse', 'blackout_gate']

LIBRARY_LOGIC = r'''
# scene_library: discovery, quarantine validation and approval.
# See build_scene_library.py for what each stage checks.
import datetime
import json
import math
import os
import time
import traceback

import numpy as np

LANES = %(lanes)r
IDLE = dict((n, 0.0) for n in LANES)
IDLE['blackout_gate'] = 1.0

STANDARD = [('Moduleactive', 'Toggle'), ('Intensity', 'Float'), ('Seed', 'Int'),
            ('Reset', 'Pulse'), ('Outputwidth', 'Int'), ('Outputheight', 'Int')]

# s10: module-side In operators (name, family, required) in connector order,
# the slot's parameter page and its parameters (name, style, menu tokens).
CONTRACT = {
    'base_scene': {
        'inputs': [('in0_motion', 'CHOP', True), ('in1_palette', 'DAT', False)],
        'page': None, 'pars': []},     # palette choice is the runtime's (s8.1)
    'hit_fx': {
        'inputs': [('in0_image', 'TOP', True), ('in1_motion', 'CHOP', True),
                   ('in2_palette', 'DAT', False)],
        'page': 'Hit FX', 'pars': [('Fxamount', 'Float', None),
                                   ('Blendmode', 'Menu', ['over', 'add', 'screen']),
                                   ('Colorize', 'Float', None)]},
    'brand_overlay': {
        'inputs': [('in0_image', 'TOP', True), ('in1_motion', 'CHOP', True),
                   ('in2_brand', 'DAT', True), ('in3_logo', 'TOP', False)],
        'page': 'Brand', 'pars': [('Logoopacity', 'Float', None), ('Nameopacity', 'Float', None),
                                  ('Placement', 'Menu', ['center', 'top_left', 'top_right',
                                                         'bottom_left', 'bottom_right']),
                                  ('Safearea', 'Float', None)]},
    'finish_fx': {
        'inputs': [('in0_image', 'TOP', True), ('in1_motion', 'CHOP', True)],
        'page': 'Finish', 'pars': [('Contrast', 'Float', None), ('Brightness', 'Float', None),
                                   ('Softness', 'Float', None), ('Outputclamp', 'Toggle', None)]},
}

# synthetic sources fed to each connector, by slot type
WIRING = {
    'base_scene': ['syn_motion', 'syn_palette'],
    'hit_fx': ['syn_image', 'syn_motion', 'syn_palette'],
    'brand_overlay': ['syn_image', 'syn_motion', 'syn_brand', 'syn_logo'],
    'finish_fx': ['syn_image', 'syn_motion'],
}

RESERVED = {'in0_image': 'TOP', 'in0_motion': 'CHOP', 'in1_motion': 'CHOP',
            'in1_palette': 'DAT', 'in2_palette': 'DAT', 'in2_brand': 'DAT',
            'in3_logo': 'TOP', 'render': 'COMP', 'out1': 'TOP'}

STYLE = {'float': ('Float',), 'integer': ('Int',), 'toggle': ('Toggle',),
         'menu': ('Menu', 'StrMenu'), 'color': ('RGB', 'RGBA')}

COLS = ['id', 'folder', 'type', 'version', 'displayName', 'static', 'quarantine', 'approved']

STABLE = 0.02            # max per-pixel change for "the same frame"
PASS_THROUGH = 2.0 / 255 # max per-pixel change for an exact pass-through
COOK_WARN_MS = 4.0       # a quarter of a 60 fps frame: four slots must fit
COOK_FAIL_MS = 16.0

_queue = []
_job = {'gen': None, 'report': None}


# ----------------------------------------------------------- locations
def Paths():
    root = project.folder
    return {'modules': os.path.join(root, 'modules'),
            'reports': os.path.join(root, 'validation'),
            'approved': os.path.join(root, 'library', 'approved.json')}


def _toeexpand():
    p = os.path.join(app.binFolder, 'toeexpand.exe')
    return p if os.path.isfile(p) else None


def _static():
    return op('static_checks').module


def _q():
    return parent().op('quarantine')


# ------------------------------------------------------------- approvals
def _approvals():
    try:
        with open(Paths()['approved'], 'r', encoding='utf-8') as f:
            return json.load(f).get('approved', {})
    except (IOError, OSError, ValueError):
        return {}


def _approval_state(appr, mid, version):
    a = appr.get(mid)
    if not a:
        return 'no'
    return 'yes' if a.get('version') == version else 'stale (%%s)' %% a.get('version')


def _report_path(folder):
    return os.path.join(Paths()['reports'], folder + '.json')


def _load_report(folder):
    try:
        with open(_report_path(folder), 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return None


# ------------------------------------------------------------- discovery
def Scan(quiet=False):
    """Discover modules and run the static checks (s15.1)."""
    reps = _static().discover(Paths()['modules'], _toeexpand())
    appr = _approvals()
    t = parent().op('LIBRARY')
    t.clear()
    t.appendRow(COLS)
    static = {}
    for r in reps:
        d = r.as_dict()
        folder = os.path.basename(r.folder)
        static[folder] = d
        prev = _load_report(folder)
        q = prev.get('result', '') if prev and prev.get('version') == d['version'] else ''
        state = _approval_state(appr, d['id'], d['version'])
        if state == 'yes' and q == 'fail':
            state = 'blocked (fails now)'
        t.appendRow([d['id'] or '', folder, d['type'] or '', d['version'] or '',
                     d['displayName'] or '', d['status'], q or 'not run', state])
    parent().store('static', static)
    if not quiet:
        Summary()
        for d in static.values():
            for c in d['checks']:
                if c['status'] != 'pass':
                    print('  %%-16s %%-4s %%-16s %%s' %% (d['folder'] and os.path.basename(d['folder']),
                                                     c['status'], c['check'], c['detail']))
    return reps


def Summary():
    t = parent().op('LIBRARY')
    print('%%-30s %%-15s %%-14s %%-8s %%-7s %%-10s %%s' %% (
        'id', 'folder', 'type', 'version', 'static', 'quarantine', 'approved'))
    for r in range(1, t.numRows):
        print('%%-30s %%-15s %%-14s %%-8s %%-7s %%-10s %%s' %% tuple(
            t[r, c].val for c in ('id', 'folder', 'type', 'version', 'static', 'quarantine', 'approved')))


def _folder_for(key):
    t = parent().op('LIBRARY')
    for r in range(1, t.numRows):
        if key in (t[r, 'id'].val, t[r, 'folder'].val):
            return t[r, 'folder'].val
    return None


# ------------------------------------------------------------ job runner
def ValidateAll():
    Scan(quiet=True)
    t = parent().op('LIBRARY')
    _queue[:] = [t[r, 'folder'].val for r in range(1, t.numRows)]
    print('validating %%d module(s) in quarantine...' %% len(_queue))
    _next()


def Validate(key):
    Scan(quiet=True)
    folder = _folder_for(key)
    if folder is None:
        print('no module %%r in the library' %% key)
        return
    _queue[:] = [folder]
    _next()


def _next():
    if _job['gen'] is not None:
        return
    if not _queue:
        Scan(quiet=True)
        print('validation finished')
        Summary()
        return
    folder = _queue.pop(0)
    print('-- %%s' %% folder)
    _job['gen'] = _run(folder)
    Tick()


def _cook():
    """Cook the module under test every frame, as a viewer would. Nothing in
    quarantine displays it, so without this it only cooks when a frame is
    read back - and a one-frame impact_trigger is never seen (first run)."""
    m = _q().op('module')
    o = m.op('out1') if m is not None else None
    if o is None:
        return
    t0 = time.perf_counter()
    o.cook(force=True)
    _job['cook_ms'] = (time.perf_counter() - t0) * 1000.0


def Tick():
    g = _job['gen']
    if g is None:
        return
    _cook()
    if _job.get('wait', 0) > 0:
        _job['wait'] -= 1
        run("op(%%r).module.Tick()" %% me.path, delayFrames=1)
        return
    try:
        wait = next(g)
    except StopIteration:
        _job['gen'] = None
        run("op(%%r).module._next()" %% me.path, delayFrames=1)
        return
    except Exception:
        rep = _job.get('report')
        if rep is not None:
            rep['runtime'].append({'check': 'runner', 'status': 'fail',
                                   'detail': traceback.format_exc().splitlines()[-1]})
            _finish(rep)
        _unload()
        print(traceback.format_exc())
        _job['gen'] = None
        run("op(%%r).module._next()" %% me.path, delayFrames=1)
        return
    # tick every frame (so _cook runs every frame) and count the wait down
    _job['wait'] = max(1, int(wait)) - 1
    run("op(%%r).module.Tick()" %% me.path, delayFrames=1)


# --------------------------------------------------------------- helpers
def _set(**lanes):
    c = _q().op('syn_motion')
    vals = dict(IDLE)
    vals.update(lanes)
    for i, n in enumerate(LANES):
        getattr(c.par, 'const%%dvalue' %% i).val = vals[n]


def _sample(top):
    a = top.numpyArray()
    if a is None:
        return None
    return np.array(a[::8, ::8, :3], dtype='float32')


def _diff(a, b):
    if a is None or b is None or a.shape != b.shape:
        return float('inf')
    return float(np.abs(a - b).max())


def _finite(a):
    return a is not None and bool(np.isfinite(a).all())


def _outside():
    q = _q().path + '/'
    return set(o.path for o in op('/project1').findChildren() if not o.path.startswith(q))


def _unload():
    m = _q().op('module')
    if m is not None:
        m.destroy()


def _manifest(folder):
    with open(os.path.join(Paths()['modules'], folder, 'module.json'), 'r', encoding='utf-8') as f:
        return json.load(f)


class _Rec(object):
    def __init__(self, report):
        self.report = report

    def __call__(self, stage, check, ok, detail='', warn=False):
        status = 'pass' if ok else ('warn' if warn else 'fail')
        self.report[stage].append({'check': check, 'status': status, 'detail': detail})
        if status != 'pass':
            print('   %%-4s %%-9s %%-22s %%s' %% (status, stage, check, detail))
        return ok

    def info(self, stage, check, detail):
        self.report[stage].append({'check': check, 'status': 'info', 'detail': detail})


# ---------------------------------------------------------------- stages
def _interface(m, mtype, manifest, rec):
    c = CONTRACT[mtype]
    errs = m.errors(recurse=True)
    rec('interface', 'no errors', not errs, errs[:200])

    inputs = dict((conn.inOP.name, conn.index) for conn in m.inputConnectors if conn.inOP is not None)
    for index, (name, family, required) in enumerate(c['inputs']):
        o = m.op(name)
        if o is None:
            rec('interface', 'input ' + name, not required,
                'missing' if required else 'optional, absent', warn=not required)
            continue
        good = o.family == family and o.OPType.startswith('in')
        rec('interface', 'input ' + name, good, '%%s %%s' %% (o.OPType, '' if good else '(want an In %%s)' %% family))
        if good:
            rec('interface', 'connector ' + name, inputs.get(name) == index,
                'index %%s, want %%d' %% (inputs.get(name), index))
    extra = sorted(set(inputs) - set(n for n, _, _ in c['inputs']))
    if extra:
        rec('interface', 'extra inputs', False, ', '.join(extra), warn=True)

    r = m.op('render')
    rec('interface', 'render', r is not None and r.family == 'COMP' and r.isCOMP,
        r.OPType if r is not None else 'missing')
    o1 = m.op('out1')
    rec('interface', 'out1', o1 is not None and o1.OPType == 'outTOP',
        o1.OPType if o1 is not None else 'missing')

    for name, family in RESERVED.items():
        o = m.op(name)
        if o is not None and o.family != family:
            rec('interface', 'reserved ' + name, False, 'is %%s, reserved for %%s' %% (o.family, family))

    def par_check(page, name, style, tokens=None):
        p = getattr(m.par, name, None)
        if p is None:
            return rec('interface', 'par ' + name, False, 'missing (page %%s)' %% page)
        problems = []
        if p.page.name != page:
            problems.append('on page %%s, want %%s' %% (p.page.name, page))
        if p.style != style:
            problems.append('style %%s, want %%s' %% (p.style, style))
        if tokens is not None and list(p.menuNames) != tokens:
            problems.append('menu %%s, want %%s' %% (list(p.menuNames), tokens))
        return rec('interface', 'par ' + name, not problems, '; '.join(problems))

    for name, style in STANDARD:
        par_check('DeckGlow', name, style)
    for name, style, tokens in c['pars']:
        par_check(c['page'], name, style, tokens)
    if getattr(m.par, 'Paletteindex', None) is not None:
        rec('interface', 'obsolete Paletteindex', False,
            'removed from the contract: the runtime chooses the palette (s8.1)', warn=True)

    # s15.1 last item: every declared control has a matching custom parameter
    declared = set()
    for ctl in manifest.get('controls', []):
        name = ctl.get('parameter')
        declared.add(name)
        p = getattr(m.par, name, None)
        if p is None:
            rec('interface', 'control ' + str(name), False, 'declared but no parameter')
            continue
        problems = []
        if p.page.name != 'Controls':
            problems.append('on page %%s, want Controls' %% p.page.name)
        if p.style not in STYLE.get(ctl.get('type'), ()):
            problems.append('style %%s for type %%s' %% (p.style, ctl.get('type')))
        if ctl.get('type') in ('float', 'integer'):
            for key, actual in (('default', p.default), ('min', p.normMin), ('max', p.normMax)):
                if abs(float(actual) - float(ctl.get(key, 0))) > 1e-6:
                    problems.append('%%s %%s, manifest %%s' %% (key, actual, ctl.get(key)))
        rec('interface', 'control ' + name, not problems, '; '.join(problems))
    page = [pg for pg in m.customPages if pg.name == 'Controls']
    if page:
        undeclared = sorted(p.name for p in page[0].pars if p.name not in declared)
        if undeclared:
            rec('interface', 'undeclared controls', False, ', '.join(undeclared), warn=True)


# A fixed, busy motion state used to compare one module at two resolutions.
PROBE_STATE = dict(body_level=0.5, body_drift=0.5, impact_fast=1.0, impact_wide=1.0,
                   sync_phase=0.25, sync_sine=1.0, sync_triangle=0.5, sync_level=0.6,
                   sync_bar_env=0.8, texture_level=0.5, texture_jitter=0.5,
                   mood_warmth=0.7, mood_softness=0.3, brand_pulse=0.2)
SECOND_RES = (640, 360)
RES_TOLERANCE = 0.05     # mean change per 32x18 block, 0..1


def _grid(a, gw=32, gh=18):
    """Block-average a frame to gw x gh so two resolutions can be compared."""
    h, w = a.shape[0] - a.shape[0] %% gh, a.shape[1] - a.shape[1] %% gw
    a = a[:h, :w, :3]
    return a.reshape(gh, h // gh, gw, w // gw, 3).mean(axis=(1, 3))


def _probe(m, out):
    """Reset, one hit into PROBE_STATE, then read the whole frame 4 frames on.
    Seeded modules replay the same content, so only resolution differs."""
    _set()
    m.par.Reset.pulse()
    yield 3
    _set(impact_trigger=1.0, **PROBE_STATE)
    yield 1
    _set(**PROBE_STATE)
    yield 4
    a = out.numpyArray()
    _job['probe'] = None if a is None else np.array(a, dtype='float32')


def _resolution(m, mtype, rec):
    """Resolution independence (Block 8 decision 4): render the same state at
    the stack resolution and at SECOND_RES, and require the same picture.
    Base scenes get a smaller request; other slots a smaller input image."""
    q = _q()
    out = m.op('out1')
    img = q.op('syn_image')
    base = mtype == 'base_scene'

    for wait in _probe(m, out):
        yield wait
    hi, hi_res = _job.pop('probe', None), (out.width, out.height)

    # The comparison only means something if the probe frame shows the
    # module's own content: a module that drew nothing would match trivially.
    if hi is not None:
        if base:
            seen = float(hi[:, :, :3].mean())
            rec('runtime', 'probe has content', seen > 0.01,
                'mean %%.3f in the probe state' %% seen, warn=True)
        else:
            src = img.numpyArray()
            seen = (float(np.abs(_grid(hi) - _grid(np.array(src, dtype='float32'))).max())
                    if src is not None else 0.0)
            rec('runtime', 'probe has content', seen > STABLE,
                'differs from its input by %%.3f in the probe state' %% seen, warn=True)

    if base:
        m.par.Outputwidth, m.par.Outputheight = SECOND_RES
    else:
        img.par.resolutionw, img.par.resolutionh = SECOND_RES
    yield 3
    for wait in _probe(m, out):
        yield wait
    lo, lo_res = _job.pop('probe', None), (out.width, out.height)

    rec('runtime', 'second resolution', lo_res == SECOND_RES,
        '%%dx%%d for a %%dx%%d %%s' %% (lo_res + SECOND_RES + ('request' if base else 'input',)))
    if hi is None or lo is None or not _finite(lo):
        rec('runtime', 'resolution independent', False, 'no valid frame at one of the sizes')
    else:
        d = np.abs(_grid(hi) - _grid(lo))
        rec('runtime', 'resolution independent', float(d.mean()) < RES_TOLERANCE,
            'mean block change %%.3f, peak %%.3f between %%dx%%d and %%dx%%d'
            %% (float(d.mean()), float(d.max()), hi_res[0], hi_res[1], lo_res[0], lo_res[1]))

    if base:
        m.par.Outputwidth, m.par.Outputheight = 1920, 1080
    else:
        img.par.resolutionw, img.par.resolutionh = 1920, 1080
    _set()
    yield 3


def _runtime(m, mtype, rec, perf):
    q = _q()
    out = m.op('out1')
    img = q.op('syn_image')
    probe = q.op('res_probe')
    base = mtype == 'base_scene'

    # Idle: valid, stable frame at the stack resolution (s15.3, s15.4)
    _set()
    m.par.Reset.pulse()
    yield 6
    a = _sample(out)
    yield 10
    b = _sample(out)
    rec('runtime', 'idle valid', _finite(a) and _finite(b), 'NaN/Inf in frame' if not (_finite(a) and _finite(b)) else '')
    rec('runtime', 'idle stable', _diff(a, b) < STABLE, 'max change %%.3f' %% _diff(a, b))
    want = (probe.width, probe.height) if base else (img.width, img.height)
    rec('runtime', 'resolution', (out.width, out.height) == want,
        '%%dx%%d, stack %%dx%%d' %% (out.width, out.height, want[0], want[1]))
    if base and a is not None:
        mean = float(a.mean())
        rec('runtime', 'idle visible', mean > 0.01,
            ('mean %%.3f' %% mean) if mean > 0.01 else
            'mean %%.3f - black at idle (s10.1: meaningful with all lanes at zero)' %% mean, warn=True)
    idle = b

    # Drive: body lanes sweep 0..1
    ok = True
    for i in range(21):
        v = i / 20.0
        _set(body_level=v, body_drift=v)
        yield 1
        if i %% 5 == 0:
            ok = ok and _finite(_sample(out))
    rec('runtime', 'drive', ok and not m.errors(recurse=True), '' if ok else 'invalid pixels during sweep')

    # Hit: one trigger with shaped envelopes; must settle back (bounded)
    _set()
    yield 3
    responded = 0.0
    for i in range(16):
        k = 1.0 - i / 15.0
        _set(impact_trigger=1.0 if i == 0 else 0.0, impact_fast=k, impact_wide=k ** 0.5)
        yield 1
        if i in (1, 4, 8):
            responded = max(responded, _diff(_sample(out), idle))
    _set()
    settled_after = None
    for step in range(12):
        yield 15
        if _diff(_sample(out), idle) < STABLE:
            settled_after = (step + 1) * 15
            break
    rec('runtime', 'hit bounded', settled_after is not None,
        'settled %%s frames after the envelope' %% settled_after if settled_after else 'still changed after 3 s')
    if mtype == 'hit_fx':
        rec('runtime', 'hit response', responded > STABLE, 'max change %%.3f' %% responded)
    else:
        rec.info('runtime', 'hit response', 'max change %%.3f' %% responded)

    # Sync: phase sweeps and wraps; base scenes must move
    frames, changes, prev = 0, 0, None
    for i in range(72):
        ph = (i / 36.0) %% 1.0
        bar = (i / 144.0) %% 1.0
        _set(sync_phase=ph, sync_sine=math.sin(2 * math.pi * ph),
             sync_triangle=1 - abs(2 * ph - 1), sync_level=max(0.0, 1 - ph * 3),
             sync_bar_env=max(0.0, 1 - bar * 4))
        yield 1
        if i %% 6 == 0:
            s = _sample(out)
            ok = _finite(s)
            if prev is not None and _diff(s, prev) > 0.002:
                changes += 1
            prev = s
            frames += 1
    if base:
        rec('runtime', 'sync motion', changes >= 3, '%%d of %%d samples changed' %% (changes, frames - 1))
    else:
        rec.info('runtime', 'sync motion', '%%d of %%d samples changed' %% (changes, frames - 1))

    # Dense: texture lanes at 1; cook time and operator growth.
    # cook ms = wall time of the forced cook of out1 in _cook(): CPU work plus
    # GPU submission, not GPU execution. gpu ms = TouchDesigner's own
    # childrenGPUCookTime for the module, read alongside.
    kids = len(m.findChildren())
    cooks, gpus, ticks = [], [], []
    t0 = time.perf_counter()
    for i in range(60):
        _set(texture_level=1.0, texture_jitter=0.5 + 0.5 * math.sin(i * 0.7),
             body_level=0.7, impact_trigger=1.0 if i %% 8 == 0 else 0.0,
             impact_fast=1.0 if i %% 8 == 0 else 0.3, impact_wide=0.6)
        yield 1
        cooks.append(float(_job.get('cook_ms', 0.0)))
        gpus.append(float(m.childrenGPUCookTime))
        t1 = time.perf_counter()
        ticks.append((t1 - t0) * 1000.0)
        t0 = t1
    avg = sum(cooks[5:]) / max(1, len(cooks[5:]))
    peak = max(cooks[5:]) if cooks[5:] else 0.0
    gpu = sum(gpus[5:]) / max(1, len(gpus[5:]))
    fps = 1000.0 / (sum(ticks[5:]) / max(1, len(ticks[5:]))) if ticks[5:] else 0.0
    perf.update({'cook_ms_avg': round(avg, 3), 'cook_ms_peak': round(peak, 3),
                 'gpu_ms_avg': round(gpu, 3),
                 'project_fps': round(fps, 1), 'resolution': '%%dx%%d' %% (out.width, out.height)})
    rec('runtime', 'dense cook', avg < COOK_FAIL_MS,
        'avg %%.2f ms, peak %%.2f ms (warn above %%.0f)' %% (avg, peak, COOK_WARN_MS),
        warn=False)
    if COOK_WARN_MS <= avg < COOK_FAIL_MS:
        rec('runtime', 'dense budget', False, 'avg %%.2f ms is over a quarter frame' %% avg, warn=True)
    grown = len(m.findChildren()) - kids
    rec('runtime', 'dense bounded', grown == 0, 'operator count changed by %%d' %% grown)
    rec('runtime', 'dense valid', _finite(_sample(out)), '')

    # Reset: build up state, then Reset must clear it immediately
    _set()
    for i in range(3):
        _set(impact_trigger=1.0, impact_fast=1.0, impact_wide=1.0)
        yield 1
        _set(impact_fast=0.5, impact_wide=0.8)
        yield 8
    _set()
    m.par.Reset.pulse()
    yield 3
    d = _diff(_sample(out), idle)
    rec('runtime', 'reset clears', d < STABLE, 'max change from idle %%.3f, 3 frames after Reset' %% d)

    # Bypass: non-base slots pass the image through exactly (s10.2-10.4)
    if base:
        rec.info('runtime', 'bypass', 'not applicable to base_scene')
    else:
        src = None
        for label, setter, restore in (
                ('bypass inactive', lambda: setattr(m.par, 'Moduleactive', 0), lambda: setattr(m.par, 'Moduleactive', 1)),
                ('bypass intensity 0', lambda: setattr(m.par, 'Intensity', 0), lambda: setattr(m.par, 'Intensity', 1))):
            setter()
            yield 3
            src = _sample(img)
            d = _diff(_sample(out), src)
            rec('runtime', label, d <= PASS_THROUGH, 'max change from input %%.4f' %% d)
            restore()
            yield 2


def _run(folder):
    static = parent().fetch('static', {}).get(folder)
    report = {'folder': folder, 'id': None, 'version': None, 'type': None,
              'started': datetime.datetime.now().isoformat(timespec='seconds'),
              'touchdesigner': '%%s.%%s' %% (app.version, app.build),
              'static': static, 'interface': [], 'runtime': [], 'admission': [],
              'performance': {}}
    _job['report'] = report
    rec = _Rec(report)
    if static is None or static['status'] == 'fail':
        rec('admission', 'static', False, 'static checks failed - not loaded')
        _finish(report)
        return
    report.update(id=static['id'], version=static['version'], type=static['type'])
    mtype = static['type']
    manifest = _manifest(folder)

    q = _q()
    _unload()
    before = _outside()
    m = q.create(baseCOMP, 'module')
    m.nodeX, m.nodeY = 900, 0
    entry = os.path.join(Paths()['modules'], folder, manifest['entry'])
    m.par.externaltox = entry
    m.par.enableexternaltox = True
    m.par.enableexternaltoxpulse.pulse()
    yield 2
    if m.op('out1') is None:
        rec('interface', 'loads', False, 'no out1 after load (children: %%s)' %% ', '.join(c.name for c in m.children))
        _unload()
        _finish(report)
        return
    for index, src in enumerate(WIRING[mtype]):
        if index < len(m.inputConnectors):
            m.inputConnectors[index].connect(q.op(src))
    for name, value in (('Moduleactive', 1), ('Intensity', 1), ('Seed', 1),
                        ('Outputwidth', 1920), ('Outputheight', 1080)):
        if getattr(m.par, name, None) is not None:
            setattr(m.par, name, value)
    if getattr(m.par, 'Reset', None) is not None:
        m.par.Reset.pulse()
    yield 3      # s12 steps 6-7: warm before checking
    rec('interface', 'loads', True, entry)

    _interface(m, mtype, manifest, rec)
    if any(c['status'] == 'fail' for c in report['interface']):
        rec('admission', 'interface', False, 'interface failed - runtime checks skipped')
    else:
        for wait in _runtime(m, mtype, rec, report['performance']):
            yield wait
        for wait in _resolution(m, mtype, rec):
            yield wait

    _unload()
    yield 1
    after = _outside()
    created, destroyed = sorted(after - before), sorted(before - after)
    rec('admission', 'isolation', not created and not destroyed,
        ('created %%s; destroyed %%s' %% (created[:5], destroyed[:5])) if (created or destroyed)
        else 'nothing outside quarantine created or destroyed')
    _finish(report)


def _finish(report):
    stages = ('interface', 'runtime', 'admission')
    statuses = [c['status'] for s in stages for c in report[s]]
    if report.get('static') and report['static'].get('status') == 'fail':
        statuses.append('fail')
    report['result'] = 'fail' if 'fail' in statuses else 'warn' if 'warn' in statuses else 'pass'
    report['finished'] = datetime.datetime.now().isoformat(timespec='seconds')
    folder = report['folder']
    os.makedirs(Paths()['reports'], exist_ok=True)
    with open(_report_path(folder), 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    res = parent().op('RESULTS')
    for r in range(res.numRows - 1, 0, -1):
        if res[r, 'folder'].val == folder:
            res.deleteRow(r)
    for s in stages:
        for c in report[s]:
            res.appendRow([folder, s, c['check'], c['status'], c['detail']])
    perf = report.get('performance') or {}
    print('   => %%s %%s%%s' %% (report['result'].upper(), folder,
                              ('  (cook avg %%s ms, peak %%s ms)' %% (perf.get('cook_ms_avg'), perf.get('cook_ms_peak')))
                              if perf else ''))


# -------------------------------------------------------------- approval
def Approve(key, note=''):
    """Approve the current version of a module that passed (or warned)."""
    Scan(quiet=True)
    folder = _folder_for(key)
    if folder is None:
        print('no module %%r' %% key)
        return False
    rep = _load_report(folder)
    static = parent().fetch('static', {}).get(folder) or {}
    if rep is None or rep.get('version') != static.get('version'):
        print('refused: %%s has no quarantine report for version %%s - run Validate first'
              %% (folder, static.get('version')))
        return False
    if rep.get('result') == 'fail' or static.get('status') == 'fail':
        print('refused: %%s failed validation' %% folder)
        return False
    path = Paths()['approved']
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        data = {'approved': {}}
    data.setdefault('approved', {})[static['id']] = {
        'version': static['version'], 'folder': folder, 'result': rep['result'],
        'validated': rep.get('finished'), 'approved': datetime.datetime.now().isoformat(timespec='seconds'),
        'note': note}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)
    Scan(quiet=True)
    print('approved %%s %%s (%%s)' %% (static['id'], static['version'], rep['result']))
    return True


def Revoke(key):
    Scan(quiet=True)
    folder = _folder_for(key)
    static = parent().fetch('static', {}).get(folder or '') or {}
    path = Paths()['approved']
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return False
    gone = data.get('approved', {}).pop(static.get('id', key), None)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)
    Scan(quiet=True)
    print('revoked %%s' %% key if gone else 'nothing to revoke for %%s' %% key)
    return bool(gone)


def IsApproved(key):
    folder = _folder_for(key)
    static = parent().fetch('static', {}).get(folder or '') or {}
    a = _approvals().get(static.get('id'))
    if not (a and a.get('version') == static.get('version') and static.get('status') != 'fail'):
        return False
    # an approval does not survive a later failed validation of the same version
    rep = _load_report(folder) if folder else None
    return not (rep and rep.get('version') == static.get('version') and rep.get('result') == 'fail')


def LoadApproved(host, key):
    """The gated path into a host: only approved, current-version modules."""
    Scan(quiet=True)
    folder = _folder_for(key)
    if folder is None or not IsApproved(key):
        print('refused: %%s is not approved for its current version' %% key)
        return False
    static = parent().fetch('static', {})[folder]
    manifest = _manifest(folder)
    h = op('/project1/' + host)
    if h is None:
        print('no host %%s' %% host)
        return False
    h.par.Modulepath = os.path.join(Paths()['modules'], folder, manifest['entry']).replace('\\', '/')
    h.par.Moduletype = static['type']
    h.par.Load.pulse()
    print('loading %%s into %%s' %% (static['id'], host))
    return True
'''


def build():
    old = ROOT.op(NAME)
    if old is not None:
        old.destroy()

    lib = ROOT.create(baseCOMP, NAME)
    lib.nodeX, lib.nodeY = 6400, -3000
    lib.nodeWidth, lib.nodeHeight = 900, 300

    static = lib.create(textDAT, 'static_checks')
    static.nodeX, static.nodeY = 0, 300
    with open(STATIC_SRC, 'r', encoding='utf-8') as f:
        static.text = f.read()

    logic = lib.create(textDAT, 'library')
    logic.nodeX, logic.nodeY = 300, 300
    logic.text = LIBRARY_LOGIC % {'lanes': LANES}

    t = lib.create(tableDAT, 'LIBRARY')
    t.nodeX, t.nodeY = 600, 300
    t.clear()

    res = lib.create(tableDAT, 'RESULTS')
    res.nodeX, res.nodeY = 900, 300
    res.clear()
    res.appendRow(['folder', 'stage', 'check', 'status', 'detail'])

    # ------------------------------------------------------- quarantine
    q = lib.create(baseCOMP, 'quarantine')
    q.nodeX, q.nodeY = 300, 0

    mot = q.create(constantCHOP, 'syn_motion')
    mot.nodeX, mot.nodeY = 0, 300
    mot.seq.const.numBlocks = len(LANES)
    for i, n in enumerate(LANES):
        getattr(mot.par, 'const%dname' % i).val = n
        getattr(mot.par, 'const%dvalue' % i).val = 1.0 if n == 'blackout_gate' else 0.0

    keys = q.create(tableDAT, 'syn_image_keys')
    keys.nodeX, keys.nodeY = -300, 0
    keys.clear()
    for row in (['pos', 'r', 'g', 'b', 'a'],
                [0.0, 0.10, 0.20, 0.60, 1.0],
                [1.0, 0.90, 0.60, 0.20, 1.0]):
        keys.appendRow(row)

    # a gradient, not a flat colour, so pass-through differences show
    img = q.create(rampTOP, 'syn_image')
    img.nodeX, img.nodeY = 0, 0
    for d in list(img.docked):
        d.destroy()
    img.par.dat = 'syn_image_keys'
    img.par.outputresolution = 'custom'
    img.par.resmult = False
    img.par.resolutionw = 1920
    img.par.resolutionh = 1080

    # what the stack resolution really is on this machine (licence caps apply)
    probe = q.create(constantTOP, 'res_probe')
    probe.nodeX, probe.nodeY = 0, -300
    probe.par.outputresolution = 'custom'
    probe.par.resmult = False
    probe.par.resolutionw = 1920
    probe.par.resolutionh = 1080

    pal = q.create(tableDAT, 'syn_palette')
    pal.nodeX, pal.nodeY = 0, -600
    pal.clear()
    for row in (['role', 'r', 'g', 'b', 'a'],
                ['background', 0.02, 0.02, 0.03, 1.0],
                ['primary', 1.00, 0.82, 0.10, 1.0],
                ['secondary', 0.10, 0.35, 1.00, 1.0],
                ['accent', 1.00, 1.00, 1.00, 1.0]):
        pal.appendRow(row)

    brand = q.create(tableDAT, 'syn_brand')
    brand.nodeX, brand.nodeY = 0, -900
    brand.clear()
    for row in (['key', 'value'], ['displayName', 'QUARANTINE'], ['mode', 'logo_and_name'],
                ['primaryColor', '1.0,0.82,0.1,1.0'], ['secondaryColor', '0.1,0.35,1.0,1.0'],
                ['scale', '1.0'], ['opacity', '1.0']):
        brand.appendRow(row)

    logo = q.create(textTOP, 'syn_logo')
    logo.nodeX, logo.nodeY = 0, -1200
    logo.par.text = 'Q'
    logo.par.outputresolution = 'custom'
    logo.par.resmult = False
    logo.par.resolutionw = 256
    logo.par.resolutionh = 256
    logo.par.fontautosize = 'nofit'
    menu_pick(logo.par.fontsizexunit, 'px', 'pixels', 'pixel')
    logo.par.keepfontratio = True
    logo.par.fontsizex = 180
    logo.par.alignx = 'center'
    logo.par.aligny = 'center'
    logo.par.bgalpha = 0

    logic.module.Scan()
    print('scene_library built at %s' % lib.path)
    print("next: lib = op('%s').module" % logic.path)
    return lib


build()
