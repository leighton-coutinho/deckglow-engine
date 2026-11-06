"""Adds the performer controls to the ENGINE_INPUT -> motion_adapter path.

Run inside TouchDesigner's textport (Alt+T):

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_performer_controls.py').read())

What it builds:

    ENGINE_INPUT -----------+
                            +-> engine_controls (Merge) -> motion_adapter
    performer_controls -----+
    (Constant, six amounts, default 1.0)

and inside /project1/motion_adapter, patched in place:

    lane_<x> --+
               +-> scale_<x> (Math, multiply) -> motion_merge -> clamp_lanes -> out1
    ctl_<amt> -+                                               (Limit 0..1, all
                                                                but sync_sine)

motion_adapter was hand-built in the .toe and has no builder of its own. This
script owns only ctl_*, scale_* and clamp_lanes inside it, plus the input
wiring of motion_merge and out1. Re-running removes what the previous run
added and rebuilds it, so it is safe to repeat. Control values carry across.

After building, it runs diagnose_performer_controls.py two frames later
(TouchDesigner initialises asynchronously - see CLAUDE.md).

Contract: docs/SCENE_MODULE_SPEC.md s9.1 and the lane definitions in
docs/HYBRID_RUNTIME_ARCHITECTURE.md (Motion Lane Meanings).
"""

ROOT = op('/project1')
ENGINE = ROOT.op('ENGINE_INPUT')
A = ROOT.op('motion_adapter')

if ENGINE is None or A is None:
    raise RuntimeError('need /project1/ENGINE_INPUT and /project1/motion_adapter '
                       '(Block 1) - open engine_input_block1.toe first')

CONTROLS = [
    'masterIntensity',
    'motionAmount',
    'flashAmount',
    'textureAmount',
    'toneAmount',
    'brandAmount',
]

# lane -> the controls that scale it, per the lane definitions in
# HYBRID_RUNTIME_ARCHITECTURE.md. Every other lane passes through unscaled.
#
# masterIntensity is the master fader: it multiplies every *energy* lane on top
# of that lane's own amount. It never touches timing (sync_phase/sine/triangle),
# colour (mood_*), the impact_trigger event or blackout_gate. sync_bar_env is an
# accent envelope (an amount, not a phase), so it is scaled like sync_level.
SCALED = {
    'body_level':    ['masterIntensity'],                  # drive
    'body_drift':    ['motionAmount', 'masterIntensity'],  # lag(drive)
    'impact_fast':   ['flashAmount', 'masterIntensity'],   # hit
    'impact_wide':   ['masterIntensity'],                  # lag(hit)
    'sync_level':    ['masterIntensity'],                  # sync
    'sync_bar_env':  ['masterIntensity'],                  # bar accent
    'texture_level': ['textureAmount', 'masterIntensity'], # density
    'texture_jitter':['textureAmount', 'masterIntensity'], # noise * density
    'mood_warmth':   ['toneAmount'],                       # tone
    'brand_pulse':   ['brandAmount', 'masterIntensity'],   # 0.25 * lag(hit)
}

# motion_merge input order. Unchanged from Block 1 so channel indices hold.
LANES = [
    'body_level', 'body_drift',
    'impact_fast', 'impact_wide', 'impact_trigger',
    'sync_level', 'sync_phase', 'sync_sine', 'sync_triangle', 'sync_bar_env',
    'texture_level', 'texture_jitter',
    'mood_warmth', 'mood_softness',
    'brand_pulse', 'blackout_gate',
]

UNCLAMPED = ['sync_sine']   # bipolar -1..1 by definition


def set_inputs(dst, srcs):
    """Replace every input of dst with srcs, in order, then check it took."""
    for conn in reversed(list(dst.inputConnectors)):
        conn.disconnect()
    for i, src in enumerate(srcs):
        if i < len(dst.inputConnectors):
            dst.inputConnectors[i].connect(src)
        else:
            src.outputConnectors[0].connect(dst)
    got = [o.name if o else None for o in dst.inputs]
    want = [o.name for o in srcs]
    if got != want:
        raise RuntimeError('%s inputs are %s, expected %s' % (dst.path, got, want))


def place(o, x, y, w=800, h=250):
    o.nodeX, o.nodeY = x, y
    o.nodeWidth, o.nodeHeight = w, h


# ------------------------------------------------------ preflight (no edits)
need = ['in0_engine', 'motion_merge', 'out1'] + ['lane_' + l for l in LANES]
missing = [n for n in need if A.op(n) is None]
if missing:
    raise RuntimeError('motion_adapter is missing %s - not the Block 1 network' % missing)

# ------------------------------------------- carry values, remove last run
carried = {}
old = ROOT.op('performer_controls')
if old is not None:
    for i in range(old.seq.const.numBlocks):
        nm = getattr(old.par, 'const%dname' % i).eval()
        if nm in CONTROLS:
            carried[nm] = getattr(old.par, 'const%dvalue' % i).eval()

for nm in ('performer_controls', 'engine_controls'):
    o = ROOT.op(nm)
    if o is not None:
        o.destroy()

for o in list(A.children):
    if o.name.startswith(('ctl_', 'scale_')) or o.name == 'clamp_lanes':
        o.destroy()

# ------------------------------------------------------ /project1 controls
pc = ROOT.create(constantCHOP, 'performer_controls')
place(pc, 275, -500, 900, 300)
pc.seq.const.numBlocks = len(CONTROLS)
for i, nm in enumerate(CONTROLS):
    getattr(pc.par, 'const%dname' % i).val = nm
    getattr(pc.par, 'const%dvalue' % i).val = carried.get(nm, 1.0)

ec = ROOT.create(mergeCHOP, 'engine_controls')
place(ec, 1600, -500, 900, 300)
set_inputs(ec, [ENGINE, pc])

# A COMP is a valid destination; only a COMP *source* needs outputConnectors.
A.inputConnectors[0].disconnect()
A.inputConnectors[0].connect(ec)
fed = [c.owner.name for c in A.inputConnectors[0].connections]
if fed != ['engine_controls']:
    raise RuntimeError('motion_adapter input is %s, expected engine_controls' % fed)

# --------------------------------------------- motion_adapter: lane scaling
in0 = A.op('in0_engine')

# one Select per control, shared by every lane that uses it
ctls = {}
for i, ctl in enumerate(CONTROLS):
    sel = A.create(selectCHOP, 'ctl_' + ctl)
    sel.par.channames = ctl
    set_inputs(sel, [in0])
    place(sel, 11200, -9240 - i * 420)
    ctls[ctl] = sel

sources = {}
for lane, amounts in SCALED.items():
    lane_op = A.op('lane_' + lane)

    # Math combines channels by index and keeps the first input's names, so
    # the lane name survives: input 0 must stay the lane.
    mul = A.create(mathCHOP, 'scale_' + lane)
    mul.par.chopop = 'mul'
    set_inputs(mul, [lane_op] + [ctls[c] for c in amounts])
    place(mul, 12800, lane_op.nodeY)

    sources[lane] = mul

merge = A.op('motion_merge')
place(merge, 14400, -4000, 1400, 600)
set_inputs(merge, [sources.get(l) or A.op('lane_' + l) for l in LANES])

# ----------------------------------------------- motion_adapter: output clamp
clamp = A.create(limitCHOP, 'clamp_lanes')
place(clamp, 16200, -4000)
labels = [str(l).lower() for l in clamp.par.type.menuLabels]
idx = next((i for i, l in enumerate(labels) if 'clamp' in l), None)
if idx is None:
    raise RuntimeError('Limit CHOP has no clamp type; labels are %s' % labels)
clamp.par.type.menuIndex = idx
clamp.par.min = 0
clamp.par.max = 1
clamp.par.scope = '* ' + ' '.join('^' + n for n in UNCLAMPED)
set_inputs(clamp, [merge])

out1 = A.op('out1')
place(out1, 17800, -4000)
set_inputs(out1, [clamp])

# --------------------------------------------------------------- report
print('performer controls built')
print('  controls:', ', '.join('%s=%g' % (n, carried.get(n, 1.0)) for n in CONTROLS))
print('  carried :', sorted(carried) or 'none (first build)')
for lane, amounts in SCALED.items():
    print('  scaled  : %-14s * %s' % (lane, ' * '.join(amounts)))
print('  clamp   : type=%s 0..1, scope "%s"' % (clamp.par.type.eval(), clamp.par.scope.eval()))
print('  checking in 2 frames...')

_diag = project.folder + '/tools/diagnose_performer_controls.py'
run('exec(open(%r).read())' % _diag, delayFrames=2)
