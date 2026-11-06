"""Makes sync_phase keep the last usable tempo when the engine loses the beat.

Run inside TouchDesigner's textport (Alt+T), with engine_input_block1.toe open:

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_tempo_fallback.py').read())

The spec (HYBRID_RUNTIME_ARCHITECTURE, SCENE_MODULE_SPEC s7) promises that
sync_phase "free-runs at the last usable tempo, so it never stalls
mid-sweep". Block 1 built a fixed 2 Hz LFO instead: always 120 BPM, and a
phase jump at every switch. This replaces it.

engine_in (patched in place):

    oscin1 -> tempo_bpm (Select, rve/v2/tempo/bpm)  -> live_engine_input
    test_bpm (Constant, tempo_bpm 120)               -> test_engine_input

motion_adapter (patched in place):

    in0_engine -> phase_keeper (Script CHOP, channel 'phase')
                     -> lane_sync_phase, ex_sine, ex_tri

    confident (>= 0.20, and 0.25 to re-lock): phase = engine beat_phase,
                                              remember the BPM
    not confident: phase carries on from where it was at the remembered BPM
                   (120 until any tempo has been seen)

The old fallback chain (sel_beat_phase, rn_beat_phase, sel_confidence,
gate_conf, rn_gate, inv_gate, freerun_phase, mul_live, mul_free, add_phase) is
removed. Re-running is safe: it removes what the previous run added, keeps
test_bpm's value, and rewires. Save the .toe afterwards.
"""

ROOT = op('/project1')
EIN = ROOT.op('engine_in')
A = ROOT.op('motion_adapter')

if EIN is None or A is None:
    raise RuntimeError('need /project1/engine_in and /project1/motion_adapter')

OBSOLETE = ['sel_beat_phase', 'rn_beat_phase', 'sel_confidence', 'gate_conf', 'rn_gate',
            'inv_gate', 'freerun_phase', 'mul_live', 'mul_free', 'add_phase']

PHASE_LOGIC = r'''
# sync_phase keeper. See build_tempo_fallback.py.
ENTER_FREE = 0.20      # confidence below this -> free-run (the old gate's bound)
EXIT_FREE = 0.25       # ...and it must reach this to re-lock (no flapping)
DEFAULT_BPM = 120.0    # before any tempo has been seen
BPM_MIN, BPM_MAX = 40.0, 240.0
MAX_DT = 0.1           # a stalled frame never jumps the phase


def _fresh():
    return {'phase': 0.0, 'bpm': None, 'live': False, 't': None}


def _state():
    st = parent().storage.get('tempo')
    if st is None:
        st = _fresh()
        parent().store('tempo', st)
    return st


def Reset():
    parent().store('tempo', _fresh())


def Step(st, now, conf, bpm, live_phase):
    """One frame. Returns the phase. Pure over (st, inputs)."""
    dt = 0.0 if st['t'] is None else max(0.0, min(MAX_DT, now - st['t']))
    st['t'] = now
    usable = BPM_MIN <= bpm <= BPM_MAX
    threshold = ENTER_FREE if st['live'] else EXIT_FREE
    st['live'] = conf >= threshold and usable
    if st['live']:
        st['bpm'] = bpm
        st['phase'] = live_phase % 1.0
    else:
        rate = (st['bpm'] or DEFAULT_BPM) / 60.0
        st['phase'] = (st['phase'] + dt * rate) % 1.0
    return st['phase']


def State():
    st = _state()
    return {'mode': 'live' if st['live'] else 'free-run',
            'bpm_held': st['bpm'], 'bpm_used': st['bpm'] if st['live'] else (st['bpm'] or DEFAULT_BPM),
            'phase': st['phase']}


def Cook(scriptOp):
    src = scriptOp.inputs[0] if scriptOp.inputs else None

    def ch(name):
        c = src[name] if src is not None else None
        return c.eval() if c is not None else 0.0

    phase = Step(_state(), absTime.seconds, ch('tempo_confidence'),
                 ch('tempo_bpm'), ch('beat_phase'))
    scriptOp.clear()
    scriptOp.isTimeSlice = False
    scriptOp.numSamples = 1
    scriptOp.appendChan('phase').vals = [phase]
'''

PHASE_CALLBACKS = r'''
def onSetupParameters(scriptOp):
    return

def onPulse(par):
    return

def onGetCookLevel(scriptOp):
    return CookLevel.WHEN_USED   # the phase advances every frame

def onCook(scriptOp):
    op('phase_logic').module.Cook(scriptOp)
    return
'''


def append_input(dst, src):
    """Connect src to the next free input of a multi-input op."""
    i = len(dst.inputs)
    if i < len(dst.inputConnectors):
        dst.inputConnectors[i].connect(src)
    else:
        src.outputConnectors[0].connect(dst)


def set_inputs(dst, srcs):
    for conn in reversed(list(dst.inputConnectors)):
        conn.disconnect()
    for src in srcs:
        append_input(dst, src)
    got = [o.name for o in dst.inputs]
    if got != [o.name for o in srcs]:
        raise RuntimeError('%s inputs are %s' % (dst.path, got))


# ------------------------------------------------------------- engine_in
keep_bpm = 120.0
old = EIN.op('test_bpm')
if old is not None:
    keep_bpm = old.par.const0value.eval()
for nm in ('tempo_bpm', 'test_bpm'):
    o = EIN.op(nm)
    if o is not None:
        o.destroy()

live = EIN.op('live_engine_input')
test = EIN.op('test_engine_input')
osc = EIN.op('oscin1')
if None in (live, test, osc):
    raise RuntimeError('engine_in is not the Block 1 network')

bpm = EIN.create(selectCHOP, 'tempo_bpm')
bpm.nodeX, bpm.nodeY = osc.nodeX + 1600, osc.nodeY - 3000
bpm.inputConnectors[0].connect(osc)
bpm.par.channames = 'rve/v2/tempo/bpm'
bpm.par.renameto = 'tempo_bpm'
append_input(live, bpm)

tb = EIN.create(constantCHOP, 'test_bpm')
tb.nodeX, tb.nodeY = osc.nodeX + 1600, osc.nodeY - 3400
tb.par.const0name = 'tempo_bpm'
tb.par.const0value = keep_bpm
append_input(test, tb)

# --------------------------------------------------------- motion_adapter
removed = []
for nm in OBSOLETE + ['phase_keeper', 'phase_logic', 'phase_callbacks']:
    o = A.op(nm)
    if o is not None:
        o.destroy()
        if nm in OBSOLETE:
            removed.append(nm)

in0 = A.op('in0_engine')
logic = A.create(textDAT, 'phase_logic')
logic.nodeX, logic.nodeY = 6400, -2100
logic.text = PHASE_LOGIC
cbs = A.create(textDAT, 'phase_callbacks')
cbs.nodeX, cbs.nodeY = 8000, -2100
cbs.text = PHASE_CALLBACKS

keeper = A.create(scriptCHOP, 'phase_keeper')
keeper.nodeX, keeper.nodeY = 8000, -2940
keeper.inputConnectors[0].connect(in0)
keeper.par.callbacks = 'phase_callbacks'

for nm in ('lane_sync_phase', 'ex_sine', 'ex_tri'):
    o = A.op(nm)
    if o is None:
        raise RuntimeError('motion_adapter is missing %s' % nm)
    set_inputs(o, [keeper])

print('tempo fallback built')
print('  engine_in : tempo_bpm (live, from rve/v2/tempo/bpm), test_bpm =', tb.par.const0value.eval())
print('  live merge:', [o.name for o in live.inputs])
print('  test merge:', [o.name for o in test.inputs])
print('  adapter   : phase_keeper -> lane_sync_phase, ex_sine, ex_tri')
print('  removed   :', removed or 'nothing (already rebuilt)')
print('  state     :', A.op('phase_logic').module.State())
print('next: run diagnose_tempo_fallback.py; save the .toe')
