"""Builds /project1/projector, the Window COMP that shows OUTPUT on a display.

Run inside TouchDesigner's textport (Alt+T), after build_module_host.py:

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_projector_window.py').read())

It only builds the window; it never opens it. Open it yourself:

    op('/project1/projector').par.winopen.pulse()      # test: separate window
    op('/project1/projector').par.performance.pulse()  # show: Perform Mode
    op('/project1/projector').par.winclose.pulse()     # close

Escape (or Shift+Escape) over the window closes it; Escape also leaves
Perform Mode. TouchDesigner's docs recommend Perform Mode, not a separate
window, for final output.

The window shows OUTPUT - after the /output safety stage and flash limiter -
filling the chosen display with no borders, always on top, the cursor shown
only while it moves. It picks the first non-primary display (the projector);
with one display it uses the primary, so opening it covers this screen.
Re-running keeps the display you chose.

OUTPUT is referenced by name, so rebuilding the stack does not break it.
"""

ROOT = op('/project1')


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


if ROOT.op('OUTPUT') is None:
    raise RuntimeError('no /project1/OUTPUT - run build_module_host.py first')

try:
    mons = [monitors[i] for i in range(len(monitors))]
except Exception:
    mons = []

old = ROOT.op('projector')
kept_display = None
if old is not None:
    try:
        old.par.winclose.pulse()
    except Exception:
        pass
    kept_display = old.par.display.eval()
    old.destroy()

if kept_display is not None and any(m.index == kept_display for m in mons):
    display = kept_display
    why = 'kept from previous build'
else:
    secondary = [m for m in mons if not m.isPrimary]
    primary = [m for m in mons if m.isPrimary]
    if secondary:
        display, why = secondary[0].index, 'first non-primary display'
    elif primary:
        display, why = primary[0].index, 'only display (primary) - opening covers this screen'
    else:
        display, why = 0, 'no monitor info available'

w = ROOT.create(windowCOMP, 'projector')
w.nodeX, w.nodeY = 16000, 0
w.nodeWidth, w.nodeHeight = 900, 300

w.par.winop = '/project1/OUTPUT'
w.par.title = 'DeckGlow Output'
menu_pick(w.par.justifyoffsetto, 'specifydisplay', 'specify display')
w.par.display = display
w.par.ignoretaskbar = True
menu_pick(w.par.justifyh, 'center')
menu_pick(w.par.justifyv, 'center')
menu_pick(w.par.size, 'fill', 'fill location')
w.par.borders = False
w.par.alwaysontop = True
menu_pick(w.par.cursorvisible, 'cursoronmove', 'when moving')
w.par.interact = False
w.par.closeescape = True

print('projector built at %s (not opened)' % w.path)
print('  shows      :', w.par.winop.eval())
print('  display    : %d  (%s)' % (display, why))
for m in mons:
    print('    display %d: %dx%d%s  %s' % (m.index, m.width, m.height,
                                          '  primary' if m.isPrimary else '',
                                          getattr(m, 'displayName', '')))
print('  open to test:  op(%r).par.winopen.pulse()' % w.path)
print('  open for show: op(%r).par.performance.pulse()' % w.path)
print('  close:         op(%r).par.winclose.pulse()   (or Escape)' % w.path)
