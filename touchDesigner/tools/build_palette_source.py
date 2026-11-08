"""Builds the runtime's palette selection: /project1/palette_source -> PALETTE.

Run inside TouchDesigner's textport (Alt+T), before build_module_host.py:

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_palette_source.py').read())

The runtime owns the palette (SCENE_MODULE_SPEC s8.1; Block 8 decision 2):
one show-level selection feeds the same table to every module that takes a
palette input, so all layers share one colour scheme.

    palette_source (Base COMP, custom par Paletteindex)
      library   Table DAT: name, background, primary, secondary, accent
                ("r,g,b" each). Edit rows to add palettes.
      PALETTE   (written by palette_logic, s8.1 format: role r g b a)
    /project1/PALETTE   Null DAT, wired into module_host and hit_host

Changing Paletteindex, or editing the library, rewrites the table at once.
The index wraps around the library, so any integer is safe. Re-running keeps
the library rows and the current index. Later the runtime state / frontend
(setPalette) will set Paletteindex; for now set it by hand.
"""

ROOT = op('/project1')

DEFAULT_LIBRARY = [
    ['name',     'background',     'primary',        'secondary',      'accent'],
    ['deckglow', '0.02,0.02,0.03', '1.00,0.82,0.10', '0.10,0.35,1.00', '1.00,1.00,1.00'],
    ['ember',    '0.03,0.01,0.01', '1.00,0.35,0.05', '0.90,0.10,0.20', '1.00,0.85,0.60'],
    ['ice',      '0.01,0.02,0.04', '0.30,0.80,1.00', '0.10,0.30,0.90', '0.90,0.95,1.00'],
    ['mono',     '0.02,0.02,0.02', '0.90,0.90,0.90', '0.50,0.50,0.50', '1.00,1.00,1.00'],
]

PALETTE_LOGIC = r'''
# Writes the selected library row into the s8.1 palette table.
ROLES = ('background', 'primary', 'secondary', 'accent')
FALLBACK = {'background': (0.02, 0.02, 0.03), 'primary': (1.0, 0.82, 0.10),
            'secondary': (0.10, 0.35, 1.0), 'accent': (1.0, 1.0, 1.0)}


def _rgb(text, role):
    try:
        v = [float(x) for x in str(text).split(',')]
        if len(v) >= 3:
            return tuple(max(0.0, min(1.0, c)) for c in v[:3])
    except ValueError:
        pass
    return FALLBACK[role]


def Selected():
    lib = parent().op('library')
    n = max(0, lib.numRows - 1)
    if n == 0:
        return None, 0
    i = int(parent().par.Paletteindex.eval()) % n
    return lib[i + 1, 'name'].val, i


def Apply():
    lib = parent().op('library')
    out = parent().op('PALETTE')
    name, i = Selected()
    out.clear()
    out.appendRow(['role', 'r', 'g', 'b', 'a'])
    src = parent()
    override = bool(src.par.Backgroundoverride.eval())
    for role in ROLES:
        if role == 'background' and override:
            # the frontend's background colour (setBackground) beats the palette's
            r, g, b = (max(0.0, min(1.0, float(getattr(src.par, 'Backgroundcolor' + c).eval())))
                       for c in 'rgb')
        else:
            cell = lib[i + 1, role] if name is not None else None
            r, g, b = _rgb(cell.val if cell is not None else '', role)
        out.appendRow([role, '%.4f' % r, '%.4f' % g, '%.4f' % b, '1.0'])
    return name
'''

PAREXEC = r'''
def onValueChange(par, prev):
    op('palette_logic').module.Apply()
    return
'''

DATEXEC = r'''
def onTableChange(dat):
    op('palette_logic').module.Apply()
    return
'''

old = ROOT.op('palette_source')
rows, index = DEFAULT_LIBRARY, 0
bg_override, bg_color = 0, (0.02, 0.02, 0.03)
if old is not None:
    lib_old = old.op('library')
    if lib_old is not None and lib_old.numRows > 1:
        rows = [[c.val for c in lib_old.row(r)] for r in range(lib_old.numRows)]
    index = int(old.par.Paletteindex.eval())
    if getattr(old.par, 'Backgroundoverride', None) is not None:
        bg_override = int(old.par.Backgroundoverride.eval())
        bg_color = tuple(float(getattr(old.par, 'Backgroundcolor' + c).eval()) for c in 'rgb')
    old.destroy()
o = ROOT.op('PALETTE')
if o is not None:
    o.destroy()

# Palettes shipped in installed creator packs (PACK_FORMAT_SPEC s4) join the
# library under '<pack id>/<name>'. They were checked when the pack was
# installed; anything unreadable here is skipped. The runtime still chooses.
import json
import os
packs_dir = os.path.join(project.folder, 'Packs')
have = {r[0] for r in rows}
added = []
if os.path.isdir(packs_dir):
    for pid in sorted(os.listdir(packs_dir)):
        try:
            with open(os.path.join(packs_dir, pid, 'pack.json'), 'r', encoding='utf-8') as f:
                pal_paths = json.load(f).get('palettes', [])
        except (OSError, ValueError):
            continue
        for rel in pal_paths:
            try:
                with open(os.path.join(packs_dir, pid, *rel.split('/')), 'r', encoding='utf-8') as f:
                    pal = json.load(f)
                name = '%s/%s' % (pid, pal['name'])
                row = [name] + [','.join('%.4f' % float(c) for c in pal[k][:3])
                                for k in ('background', 'primary', 'secondary', 'accent')]
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if name not in have:
                rows.append(row)
                have.add(name)
                added.append(name)

src = ROOT.create(baseCOMP, 'palette_source')
src.nodeX, src.nodeY = 4800, -1800
src.nodeWidth, src.nodeHeight = 900, 300

page = src.appendCustomPage('Palette')
p = page.appendInt('Paletteindex', label='Palette Index')[0]
p.default = 0
p.min = 0
p.clampMin = True
p.normMin, p.normMax = 0, max(1, len(rows) - 2)
p.val = index

# Background colour override (FRONTEND_MESSAGE_CONTRACT setBackground): the
# palette's background role - what an empty or switched-off base slot shows.
p = page.appendToggle('Backgroundoverride', label='Override Background')[0]
p.default = 0
p.val = bg_override
pg = page.appendRGB('Backgroundcolor', label='Background Colour')
for par, v in zip(pg, bg_color):
    par.default = 0
    par.val = v

lib = src.create(tableDAT, 'library')
lib.nodeX, lib.nodeY = 0, 0
lib.clear()
for r in rows:
    lib.appendRow(r)

table = src.create(tableDAT, 'PALETTE')
table.nodeX, table.nodeY = 600, 0

logic = src.create(textDAT, 'palette_logic')
logic.nodeX, logic.nodeY = 300, 300
logic.text = PALETTE_LOGIC

pe = src.create(parameterexecuteDAT, 'index_parexec')
pe.nodeX, pe.nodeY = 300, -300
pe.par.op = src
pe.par.pars = 'Paletteindex Backgroundoverride Backgroundcolorr Backgroundcolorg Backgroundcolorb'
pe.par.custom = True
pe.par.builtin = False
pe.par.valuechange = True
pe.par.active = True
pe.text = PAREXEC

de = src.create(datexecuteDAT, 'library_datexec')
de.nodeX, de.nodeY = 0, -300
de.par.dat = 'library'
de.par.tablechange = True
de.par.active = True
de.text = DATEXEC

out = src.create(outDAT, 'out1')
out.nodeX, out.nodeY = 900, 0
out.inputConnectors[0].connect(table)

term = ROOT.create(nullDAT, 'PALETTE')
term.nodeX, term.nodeY = 5600, -1800
term.inputConnectors[0].connect(src.outputConnectors[0])

name = logic.module.Apply()
print('palette source built: %s -> %s' % (src.path, term.path))
print('  library  :', ', '.join('%d %s' % (i, lib[i + 1, 'name'].val) for i in range(lib.numRows - 1)))
print('  selected : %d (%s)' % (src.par.Paletteindex.eval(), name))
print('  from packs:', ', '.join(added) if added else 'none new')
print('  background:', 'override %s' % (bg_color,) if bg_override else "the palette's own")
print('next: run build_module_host.py so module_host and hit_host get PALETTE')
