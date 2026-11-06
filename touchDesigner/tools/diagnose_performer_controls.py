"""Checks that the performer controls are applied in /project1/motion_adapter.

Run inside TouchDesigner's textport (Alt+T):

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\diagnose_performer_controls.py').read())

build_performer_controls.py runs it automatically. Read-only. Changes nothing.

For each scaled lane it compares the live MOTION_OUT value with
clamp(source * control) computed independently from the source node, so a
PASS means the multiply really happened. With every control at 1.0 that only
proves the wiring; set one to 0.5 on performer_controls and run this again.
masterIntensity at 0.5 should move nine lanes, textureAmount two, and every
other control one. The mood lanes are centred: toneAmount fades both
mood_warmth and mood_softness toward 0.5 (neutral), not toward 0.
"""

TOL = 1e-3

ROOT = op('/project1')
A = ROOT.op('motion_adapter')
PC = ROOT.op('performer_controls')
OUT = ROOT.op('MOTION_OUT')
ENGINE = ROOT.op('ENGINE_INPUT')

EXPECTED_LANES = [
    'body_level', 'body_drift', 'impact_fast', 'impact_wide', 'impact_trigger',
    'sync_level', 'sync_phase', 'sync_sine', 'sync_triangle', 'sync_bar_env',
    'texture_level', 'texture_jitter', 'mood_warmth', 'mood_softness',
    'brand_pulse', 'blackout_gate',
]


def chan(o, key):
    c = o[key] if o is not None else None
    if c is None:
        raise LookupError('%s has no channel %r' % (o.path if o else '?', key))
    return c.eval()


print('=' * 60)
print('PERFORMER CONTROLS')
fails = 0

if PC is None or A is None or OUT is None or ENGINE is None:
    print('  missing performer_controls / motion_adapter / MOTION_OUT / ENGINE_INPUT')
    print('  run build_performer_controls.py first')
    fails += 1
else:
    for i in range(PC.numChans):
        print('  %-16s %.3f' % (PC[i].name, PC[i].eval()))

    fed = [c.owner.name for c in A.inputConnectors[0].connections]
    ok = fed == ['engine_controls']
    fails += not ok
    print('  adapter input    %s %s' % (fed, 'ok' if ok else 'FAIL'))

    print('LANES')
    names = [c.name for c in OUT.chans()]
    ok = names == EXPECTED_LANES
    fails += not ok
    print('  order            %s' % ('ok (16)' if ok else 'FAIL %s' % names))

    # lane, controls, node holding the unscaled source, channel on that node
    M = 'masterIntensity'
    checks = [
        ('body_level',    [M],                  ENGINE,                  'drive'),
        ('body_drift',    ['motionAmount', M],  A.op('lag_body_drift'),  0),
        ('impact_fast',   ['flashAmount', M],   ENGINE,                  'hit'),
        ('impact_wide',   [M],                  A.op('lag_impact_wide'), 0),
        ('sync_level',    [M],                  ENGINE,                  'sync'),
        ('sync_bar_env',  [M],                  A.op('ex_bar'),          0),
        ('texture_level', ['textureAmount', M], ENGINE,                  'density'),
        ('texture_jitter',['textureAmount', M], A.op('mul_jitter'),      0),
        ('brand_pulse',   ['brandAmount', M],   A.op('math_brand'),      0),
    ]
    # centred lanes: 0.5 is neutral, so the amount fades toward 0.5
    centred = [
        ('mood_warmth',   'toneAmount', ENGINE,           'tone'),
        ('mood_softness', 'toneAmount', A.op('ex_soft'),  0),
    ]
    controls = ROOT.op('engine_controls')
    for lane, ctls, src, key in checks:
        try:
            raw = chan(src, key)
            want = raw
            terms = []
            for ctl in ctls:
                amount = chan(controls, ctl)
                want *= amount
                terms.append('%s %.3f' % (ctl, amount))
            want = min(1.0, max(0.0, want))
            got = chan(OUT, lane)
            ok = abs(got - want) <= TOL
            fails += not ok
            print('  %-15s  %.4f  = clamp(%.4f * %s)  %s'
                  % (lane, got, raw, ' * '.join(terms),
                     'PASS' if ok else 'FAIL want %.4f' % want))
        except Exception as e:
            fails += 1
            print('  %-15s  <%s: %s>' % (lane, type(e).__name__, e))
    for lane, ctl, src, key in centred:
        try:
            raw = chan(src, key)
            amount = chan(controls, ctl)
            want = min(1.0, max(0.0, 0.5 + (raw - 0.5) * amount))
            got = chan(OUT, lane)
            ok = abs(got - want) <= TOL
            fails += not ok
            print('  %-15s  %.4f  = 0.5 + (%.4f - 0.5) * %s %.3f  %s'
                  % (lane, got, raw, ctl, amount, 'PASS' if ok else 'FAIL want %.4f' % want))
        except Exception as e:
            fails += 1
            print('  %-15s  <%s: %s>' % (lane, type(e).__name__, e))

    print('CLAMP')
    for c in OUT.chans():
        v = c.eval()
        lo, hi = (-1.0, 1.0) if c.name == 'sync_sine' else (0.0, 1.0)
        if not (lo - TOL <= v <= hi + TOL):
            fails += 1
            print('  %-15s  %.4f out of %g..%g  FAIL' % (c.name, v, lo, hi))
    clamp = A.op('clamp_lanes')
    print('  clamp_lanes      %s' % ('scope "%s"' % clamp.par.scope.eval() if clamp else 'MISSING'))
    fails += clamp is None

print('RESULT', 'ok' if not fails else '%d problem(s)' % fails)
