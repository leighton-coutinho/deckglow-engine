"""Checks the sync_phase keeper: mode, held tempo, and the real phase speed.

Run inside TouchDesigner's textport (Alt+T):

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\diagnose_tempo_fallback.py').read())

Prints the keeper's state at once, then samples sync_phase every frame for one
second and reports the measured speed as BPM, the largest frame-to-frame jump,
and PASS if the speed matches the tempo the keeper says it is using. Only a
temporary probe in /project1's storage is written, and removed at the end.
"""

A = op('/project1/motion_adapter')
ENGINE = op('/project1/ENGINE_INPUT')
logic = A.op('phase_logic') if A else None
keeper = A.op('phase_keeper') if A else None

print('=' * 60)
print('TEMPO FALLBACK')
if logic is None or keeper is None:
    print('  no phase_keeper - run build_tempo_fallback.py first')
else:
    def chan(name):
        c = ENGINE[name] if ENGINE is not None else None
        return round(c.eval(), 3) if c is not None else 'missing'

    s = logic.module.State()
    print('  engine        bpm %s  confidence %s  beat_phase %s'
          % (chan('tempo_bpm'), chan('tempo_confidence'), chan('beat_phase')))
    print('  keeper        mode %s  held %s  using %s BPM'
          % (s['mode'], s['bpm_held'], round(s['bpm_used'], 2)))
    print('  measuring sync_phase for 1 s...')

    STEP = r'''
root = op('/project1')
p = root.fetch('_tempo_probe', None)
k = op('/project1/motion_adapter/phase_keeper')
k.cook(force=True)
p['samples'].append((absTime.seconds, k['phase'].eval()))
if len(p['samples']) <= 60:
    run(p['src'], delayFrames=1)
else:
    sm = p['samples']
    steps = []
    for (t0, a), (t1, b) in zip(sm, sm[1:]):
        d = (b - a) % 1.0
        steps.append(d - 1.0 if d > 0.5 else d)
    elapsed = sm[-1][0] - sm[0][0]
    bpm = sum(steps) / elapsed * 60.0 if elapsed > 0 else 0.0
    mean = sum(steps) / len(steps)
    worst = max(abs(x - mean) for x in steps)
    s = op('/project1/motion_adapter/phase_logic').module.State()
    want = s['bpm_used']
    ok = want and abs(bpm - want) / want < 0.02
    print('  measured      %.2f BPM over %.2f s (keeper says %.2f, mode %s)' % (bpm, elapsed, want, s['mode']))
    print('  largest jump  %.4f cycles from the average step (%.4f)' % (worst, mean))
    print('RESULT', 'PASS' if ok else 'FAIL - phase speed does not match the tempo in use')
    root.unstore('_tempo_probe')
'''
    op('/project1').store('_tempo_probe', {'samples': [], 'src': STEP})
    run(STEP, delayFrames=1)
