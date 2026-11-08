"""Tests the look runtime's logic (build_look_runtime.py LOOK_LOGIC) outside
TouchDesigner, with stand-in hosts, palette, scene library, motion lanes and a
controllable clock.

    python -I touchDesigner/tools/test_look_logic.py

Also run by the app's npm test. Prints ALL OK, or stops at the first failure.
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'build_look_runtime.py'), encoding='utf-8').read()
i = src.index("LOOK_LOGIC = r'''") + len("LOOK_LOGIC = r'''")
LOGIC = src[i:src.index("'''", i)]


# ------------------------------------------------------------ stand-ins
class Par(object):
    def __init__(self, val=None, menu=None):
        self.val, self.pulses, self.menuNames = val, 0, menu or []
        self.isMenu = bool(menu)

    def eval(self):
        return self.val

    def pulse(self):
        self.pulses += 1
        if self.on_pulse:
            self.on_pulse()

    on_pulse = None


class Pars(object):
    def __init__(self, **kw):
        object.__setattr__(self, '_p', {k: v if isinstance(v, Par) else Par(v) for k, v in kw.items()})

    def __getattr__(self, k):
        return self._p.get(k)

    def __setattr__(self, k, v):
        self._p[k].val = v


class Cell(object):
    def __init__(self, v):
        self.val = v


class Table(object):
    def __init__(self, rows=None):
        self.rows = [list(map(str, r)) for r in (rows or [])]

    numRows = property(lambda self: len(self.rows))

    def row(self, r):
        return [Cell(v) for v in self.rows[r]]

    def clear(self):
        self.rows = []

    def appendRow(self, r):
        self.rows.append([str(x) for x in r])

    def __getitem__(self, k):
        r, c = k
        return Cell(self.rows[r][c]) if r < len(self.rows) else None


class Chan(object):
    def __init__(self, v):
        self.v = v

    def eval(self):
        return self.v


class Chop(object):
    def __init__(self, **chans):
        self.chans = {k: Chan(v) for k, v in chans.items()}

    def __getitem__(self, k):
        return self.chans.get(k)


class Out1(object):
    cooks = 0

    def cook(self, force=False):
        self.cooks += 1


class Module(object):
    def __init__(self, controls):
        self.par = Pars(**controls)


class Host(object):
    def __init__(self, name):
        self.name = name
        self.par = Pars(Modulepath='', Moduleactive=True, Intensity=1.0, Status='empty',
                        Load=Par(), Unload=Par(), Reset=Par())
        self.par.Unload.on_pulse = self.unload
        self.module, self.out1 = None, Out1()

    def unload(self):
        self.module, self.par.Modulepath = None, ''

    def op(self, n):
        return {'module': self.module, 'out1': self.out1}.get(n)


class Comp(object):
    def __init__(self):
        self.storage = {}
        self.par = Pars(Activestack=Par('a', ['a', 'b']), Mix=0.0, Transitiontime=2.0,
                        Quantize=Par('bar', ['now', 'beat', 'bar']), Phase='idle', Version=0, Frozena=0, Frozenb=0)

    def fetch(self, k, d=None):
        return self.storage.get(k, d)

    def store(self, k, v):
        self.storage[k] = v


class Clock(object):
    seconds = 100.0


tmp = tempfile.mkdtemp(prefix='looktest_')
MODULES = {
    'com.deckglow.kinetic_stripes': ('base_scene', {'Flash': 1.0}),
    'com.deckglow.solid_background': ('base_scene', {'Breathe': 0.15}),
    'com.deckglow.orb_burst': ('hit_fx', {'Spawncount': 4, 'Blendmode': Par('over', ['over', 'add', 'screen'])}),
    'com.example.unapproved': ('base_scene', {}),
}
for mid in MODULES:
    os.makedirs(os.path.join(tmp, mid))
    with open(os.path.join(tmp, mid, 'module.json'), 'w') as f:
        json.dump({'id': mid}, f)
APPROVED = {'com.deckglow.kinetic_stripes', 'com.deckglow.solid_background', 'com.deckglow.orb_burst'}
loads = []


class Library(object):
    def IsApproved(self, mid):
        return mid in APPROVED

    def LoadApproved(self, host, mid):
        loads.append((host, mid))
        h = OPS[host]
        h.par.Modulepath = os.path.join(tmp, mid, 'module.tox')
        ctl = MODULES[mid][1]
        h.module = Module({k: (Par(v.val, v.menuNames) if isinstance(v, Par) else v) for k, v in ctl.items()})
        h.par.Reset.pulses += 1                  # host Load() pulses Reset
        return True


PAL = [['name', 'background', 'primary', 'secondary', 'accent'],
       ['deckglow', '0.02,0.02,0.03', '1,0.82,0.1', '0.1,0.35,1', '1,1,1'],
       ['ember', '0.03,0.01,0.01', '1,0.35,0.05', '0.9,0.1,0.2', '1,0.85,0.6']]
palette_source = type('PS', (), {})()
palette_source.par = Pars(Paletteindex=0, Backgroundoverride=False, Backgroundcolorr=0.0, Backgroundcolorg=0.0,
                          Backgroundcolorb=0.0)
pal_lib = Table(PAL)
selected = lambda: (pal_lib[palette_source.par.Paletteindex.eval() + 1, 0].val, palette_source.par.Paletteindex.eval())
palette_source.op = lambda n: {'library': pal_lib, 'palette_logic': type('M', (), {'module': type('X', (), {'Selected': staticmethod(selected)})})}[n]
OPS = {n: Host(n) for n in ('module_host', 'hit_host', 'module_host_b', 'hit_host_b')}
OPS.update({'palette_source': palette_source, 'PALETTE': Table([['role', 'r', 'g', 'b', 'a'], ['background', 0.02, 0.02, 0.03, 1]]),
            'look_frozen_a': Table(), 'look_frozen_b': Table(),
            'MOTION_OUT': Chop(sync_phase=0.1), 'ENGINE_INPUT': Chop(bar_phase=0.1),
            '/project1/scene_library/library': type('D', (), {'module': Library()})()})
root = type('Root', (), {'op': staticmethod(lambda n: OPS.get(n))})()
comp = Comp()
g = {'parent': lambda: comp, 'absTime': Clock, 'op': lambda p: root if p == '/project1' else OPS.get(p)}
exec(LOGIC, g)
L = type('L', (), g)
LookError = g['LookError']


def frames(n, dt=1 / 60.0, beat=None, bar=None):
    for _ in range(n):
        Clock.seconds += dt
        if beat is not None:
            OPS['MOTION_OUT'].chans['sync_phase'].v = beat
        if bar is not None:
            OPS['ENGINE_INPUT'].chans['bar_phase'].v = bar
        g['Frame']()


def refused(code, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except LookError as e:
        assert e.code == code, (code, e.code, e.message)
        return e.message
    raise AssertionError('expected %s' % code)


# stack A is live with stripes + orbs (Spawncount 8 set from the frontend)
Library().LoadApproved('module_host', 'com.deckglow.kinetic_stripes')
Library().LoadApproved('hit_host', 'com.deckglow.orb_burst')
g['Controls']('hit_host')['Spawncount'] = 8
assert g['ActiveHost']('base_scene') == 'module_host' and g['ActiveHost']('brand_overlay') is None

# ----------------------------------------------------------- save / bank
g['SaveLook'](0, 'Stripes')
look0 = g['Bank']()[0]['look']
assert look0 == {'slots': {'base_scene': {'module': 'com.deckglow.kinetic_stripes', 'enabled': True, 'intensity': 1.0, 'controls': {}},
                           'hit_fx': {'module': 'com.deckglow.orb_burst', 'enabled': True, 'intensity': 1.0, 'controls': {'Spawncount': 8}}},
                 'palette': 'deckglow', 'background': None}, look0
v0 = comp.par.Version.eval()
g['SetBank']([g['Bank']()[0], {'name': 'Wash', 'look': {
    'slots': {'base_scene': {'module': 'com.deckglow.solid_background', 'enabled': True, 'intensity': 0.7, 'controls': {'Breathe': 0.4, 'Nope': 1}},
              'hit_fx': {'module': None, 'enabled': False, 'intensity': 1.0, 'controls': {}}},
    'palette': 'ember', 'background': [0.25, 0.0, 0.35]}}])
assert len(g['Bank']()) == 16 and g['Bank']()[2] is None and comp.par.Version.eval() > v0
print('ok  save captures Scene + Hits, controls, palette; bank holds 16')

# --------------------------------------------------------------- refusals
assert 'empty' in refused('empty_look', g['Take'], 5)
g['SaveLook'](3, 'Bad')
g['Bank']()[3]['look']['slots']['base_scene']['module'] = 'com.example.unapproved'
refused('not_approved', g['Take'], 3)
assert g['Take_state']()['phase'] == 'idle' and OPS['module_host_b'].module is None, 'a refused TAKE changes nothing'
print('ok  empty look and unapproved module refused before anything changes')

# ------------------------------------------------------- TAKE, on the beat
g['Take'](1, fade=1.0, quantize='beat')
t = g['Take_state']()
assert t['phase'] == 'loading' and comp.par.Phase.eval() == 'loading' and t['target'] == 'b'
assert comp.par.Frozena.eval() == 1 and comp.par.Frozenb.eval() == 0, 'outgoing stack reads its frozen palette'
assert OPS['look_frozen_a'].rows == OPS['PALETTE'].rows, 'frozen copy of the live palette'
assert palette_source.par.Paletteindex.eval() == 1 and palette_source.par.Backgroundoverride.eval() is True
assert [palette_source.par.Backgroundcolorr.eval(), palette_source.par.Backgroundcolorb.eval()] == [0.25, 0.35]
assert ('module_host_b', 'com.deckglow.solid_background') in loads and OPS['hit_host_b'].par.Unload.pulses == 1
refused('busy', g['Take'], 0)
assert g['ActiveHost']('base_scene') == 'module_host', 'stack A stays on screen while B loads'
frames(3)
mb = OPS['module_host_b'].module
assert mb.par.Breathe.eval() == 0.4 and OPS['module_host_b'].par.Intensity.eval() == 0.7
assert OPS['hit_host_b'].par.Moduleactive.eval() is False
assert g['Controls']('module_host_b') == {'Breathe': 0.4}, 'unknown controls skipped, known ones remembered'
frames(5)
assert t['phase'] == 'armed', t['phase']
cooks = OPS['hit_host_b'].out1.cooks
assert cooks >= 8, 'the idle stack is force-cooked while it warms (nothing views it)'
frames(10, beat=0.9)
assert t['phase'] == 'armed', 'waits for the beat'
frames(1, beat=0.02)
assert t['phase'] == 'fading' and comp.par.Phase.eval() == 'fading'
frames(30)
assert 0.4 < comp.par.Mix.eval() < 0.6, comp.par.Mix.eval()
frames(40)
assert t['phase'] == 'idle' and comp.par.Activestack.eval() == 'b' and comp.par.Mix.eval() == 1.0
assert t['current'] == 1 and g['ActiveHost']('base_scene') == 'module_host_b'
print('ok  TAKE: idle stack loaded and warmed, armed until the beat, 1 s crossfade, stacks swapped')

# ---------------------------------------------- bar quantize, then timeout
g['Take'](0, fade=0, quantize='bar')
assert g['Take_state']()['target'] == 'a'
frames(8)
assert g['Take_state']()['phase'] == 'armed'
frames(30, beat=0.02, bar=0.3)
frames(30, beat=0.9, bar=0.9)
frames(1, beat=0.02, bar=0.97)
assert g['Take_state']()['phase'] == 'armed', 'a beat is not a bar'
frames(1, bar=0.01)
assert g['Take_state']()['phase'] == 'idle' and comp.par.Activestack.eval() == 'a', 'fade 0 cuts on the bar'
assert OPS['module_host'].par.Reset.pulses >= 1
assert g['Controls']('hit_host') == {'Spawncount': 8} and OPS['hit_host'].module.par.Spawncount.eval() == 8
print('ok  bar quantize ignores beats, fade 0 is a cut; stack A reused, controls re-applied')

g['Take'](1, fade=0.5, quantize='bar')
frames(8)
frames(int(g['ARM_TIMEOUT'] * 60) + 5, bar=0.5)    # the bar clock stands still (no music)
assert g['Take_state']()['phase'] in ('fading', 'idle'), 'a TAKE never waits more than ARM_TIMEOUT'
frames(40)
assert comp.par.Activestack.eval() == 'b'
print('ok  no bar for %.0f s: the TAKE goes anyway' % g['ARM_TIMEOUT'])

# ------------------------------------------- new TAKE mid-fade, missing palette
g['SaveLook'](4, 'Gone palette')
g['Bank']()[4]['look']['palette'] = 'com.example.removed/sunset'
g['Take'](0, fade=2.0, quantize='now')                 # look 0: deckglow palette
frames(9)
assert g['Take_state']()['phase'] == 'fading'
idx = palette_source.par.Paletteindex.eval()
g['Take'](4, fade=0, quantize='now')                 # mid-fade: the first one completes at once
assert comp.par.Activestack.eval() == 'a' and g['Take_state']()['target'] == 'b'
assert palette_source.par.Paletteindex.eval() == idx, 'an uninstalled palette leaves the selection alone'
frames(9)
assert g['Take_state']()['phase'] == 'idle' and comp.par.Activestack.eval() == 'b'
assert any('not installed' in p for p in g['State']()['problems'])
print('ok  a TAKE mid-fade finishes the first one; a missing palette is reported and kept')

g['DeleteLook'](4)
assert g['Bank']()[4] is None and g['State']()['current'] is None
refused('bad_field', g['RenameLook'], 4, 'x')
g['RenameLook'](1, 'Purple wash')
assert g['Bank']()[1]['name'] == 'Purple wash'
g['SetTransition'](fade=3.5, quantize='beat')
assert g['Transition']() == {'fade': 3.5, 'quantize': 'beat'}
g['Take'](1, fade=0, quantize='now')
frames(10)
assert g['State']()['current'] == 1
g['SetBank']([g['Bank']()[0]])
assert g['State']()['current'] is None, 'a bank without the look on screen clears current'
print('ok  delete clears current; rename; transition defaults; SetBank clears a vanished current')

shutil.rmtree(tmp, ignore_errors=True)
print('ALL OK')
