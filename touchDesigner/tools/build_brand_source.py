"""Builds a stand-in brand source: /project1/BRAND (DAT) and /project1/LOGO (TOP).

Run inside TouchDesigner's textport (Alt+T), before build_module_host.py:

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_brand_source.py').read())

The real branding runtime (V2_ARCHITECTURE, later block) owns the DJ's logo
file, image decoding and fonts, and hands brand_overlay modules *prepared*
data. Until it exists, this provides the same two outputs so Block 5 can be
built and tested:

    brand_table (Table DAT) -> BRAND (Null DAT)   spec s8.2 key/value table
    logo_art    (Text TOP)  -> LOGO  (Null TOP)   placeholder RGBA logo, "DG"

Edit brand_table to try other names and modes; mode is one of
logo, name, logo_and_name. Re-running rebuilds everything but keeps the
table's current rows.
"""

ROOT = op('/project1')

DEFAULT_ROWS = [
    ['key',            'value'],
    ['displayName',    'DJ NAME'],
    ['subtitle',       'LIVE'],
    ['mode',           'logo_and_name'],
    ['primaryColor',   '1.0,0.82,0.1,1.0'],
    ['secondaryColor', '0.1,0.35,1.0,1.0'],
    ['scale',          '1.0'],
    ['opacity',        '1.0'],
]


def menu_pick(par, *candidates):
    """Set a menu to the first candidate matching a token or a label.
    Some menus are undocumented, and labels can be abbreviated: the Text TOP
    unit menus read px / f / a / pt, not Pixels / Fraction / ..."""
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


rows = DEFAULT_ROWS
old = ROOT.op('brand_table')
if old is not None and old.numRows > 1:
    rows = [[c.val for c in old.row(r)] for r in range(old.numRows)]

for nm in ('brand_table', 'BRAND', 'logo_art', 'LOGO'):
    o = ROOT.op(nm)
    if o is not None:
        o.destroy()

table = ROOT.create(tableDAT, 'brand_table')
table.nodeX, table.nodeY = 4800, -900
table.clear()
for r in rows:
    table.appendRow(r)

brand = ROOT.create(nullDAT, 'BRAND')
brand.nodeX, brand.nodeY = 5600, -900
brand.inputConnectors[0].connect(table)

art = ROOT.create(textTOP, 'logo_art')
art.nodeX, art.nodeY = 4800, -1300
art.par.text = 'DG'
art.par.outputresolution = 'custom'
art.par.resmult = False
art.par.resolutionw = 512
art.par.resolutionh = 512
art.par.bold = True
art.par.fontautosize = 'nofit'
menu_pick(art.par.fontsizexunit, 'px', 'pixels', 'pixel')
art.par.keepfontratio = True
art.par.fontsizex = 300
art.par.alignx = 'center'
art.par.aligny = 'center'
art.par.fontcolorr, art.par.fontcolorg, art.par.fontcolorb = 1.0, 0.82, 0.1
art.par.fontalpha = 1
art.par.bgalpha = 0

logo = ROOT.create(nullTOP, 'LOGO')
logo.nodeX, logo.nodeY = 5600, -1300
logo.inputConnectors[0].connect(art)

print('brand source built: %s (%d keys), %s' % (brand.path, table.numRows - 1, logo.path))
for r in range(1, table.numRows):
    print('  %-15s %s' % (table[r, 0].val, table[r, 1].val))
print('next: run build_module_host.py so brand_host picks up BRAND and LOGO')
