"""Drift check for the frozen module contract, deckglow.scene-module/1.

Plain Python, runs outside TouchDesigner (no TD objects are touched):

    python -I touchDesigner/tools/check_contract.py

docs/contract/deckglow.scene-module-1.json is the machine-readable contract.
This script fails (exit 1) if anything that encodes the contract disagrees
with it:

  - docs/SCENE_MODULE_SPEC.md: the s7 lane list, the s9 standard parameters,
    and every s10 slot's connector table and parameter table
  - validate_static.py: manifest fields, types, tiers, control types, limits
  - build_scene_library.py: lanes, slot connectors and parameters, standard
    parameters, reserved names, control styles
  - build_performer_controls.py and diagnose_performer_controls.py: lane order,
    the performer controls, which control scales which lane, centred lanes,
    the unclamped bipolar lane
  - every module under touchDesigner/modules: its schema and runtimeApi range

Constants are read with ast.literal_eval, never executed. Run it after any
change to the spec, the validator or the runtime builders; under s16 the
contract file itself changes only with a version bump.
"""

import ast
import json
import os
import re
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(TOOLS, '..', '..'))
CONTRACT = os.path.join(REPO, 'docs', 'contract', 'deckglow.scene-module-1.json')
SPEC = os.path.join(REPO, 'docs', 'SCENE_MODULE_SPEC.md')
MODULES = os.path.join(REPO, 'touchDesigner', 'modules')

problems = []
checked = []


def check(label, ok, detail=''):
    checked.append(label)
    if not ok:
        problems.append('%s: %s' % (label, detail))


def assigned(source, name):
    """Literal value of a top-level `name = ...` in Python source."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


c = json.loads(read(CONTRACT))
lanes = [l['name'] for l in c['lanes']]
STYLE_OF = {'Integer': 'Int', 'Float': 'Float', 'Toggle': 'Toggle',
            'Pulse': 'Pulse', 'Menu': 'Menu'}

# ------------------------------------------------------------- the spec
spec = read(SPEC)
check('spec status', 'Status: Frozen' in spec, 'SCENE_MODULE_SPEC.md is not marked frozen')
check('spec contract id', 'Contract id: `%s`' % c['contract'] in spec, 'contract id line missing')

s7 = spec[spec.index('## 7. Shared Motion Contract'):]
block = s7[s7.index('```text') + 7:s7.index('```', s7.index('```text') + 7)]
check('spec s7 lanes', block.split() == lanes, 'spec %s vs contract %s' % (block.split(), lanes))

s9 = spec[spec.index('## 9. Standard Parameters'):spec.index('### 9.1')]
rows = re.findall(r'^\| `(\w+)` \| (\w+) \|', s9, re.M)
want = [(p['name'], p['style']) for p in c['standardParameters']['parameters']]
check('spec s9 parameters', [(n, STYLE_OF.get(t, t)) for n, t in rows] == want,
      'spec %s vs contract %s' % (rows, want))

for title, slot in (('### 10.1 Base Scene', 'base_scene'), ('### 10.2 Hit Effect', 'hit_fx'),
                    ('### 10.3 Brand Overlay', 'brand_overlay'), ('### 10.4 Finish Effect', 'finish_fx')):
    start = spec.index(title)
    end = spec.index('\n### ', start + 5) if '\n### ' in spec[start + 5:] else len(spec)
    end = min(end, spec.index('\n## 11', start))
    sec = spec[start:end]
    conn = re.findall(r'^\| `(\d)` \| `(\w+)` \| (\w+) \| (Yes|No) \|', sec, re.M)
    want_in = [(str(i), x['name'], x['family'], 'Yes' if x['required'] else 'No')
               for i, x in enumerate(c['slots'][slot]['inputs'])]
    check('spec %s connectors' % slot, conn == want_in, 'spec %s vs contract %s' % (conn, want_in))
    pars = re.findall(r'^\| `([A-Z]\w+)` \| (\w+) \|', sec, re.M)
    want_p = [(p['name'], p['style']) for p in c['slots'][slot]['parameters']]
    check('spec %s parameters' % slot, [(n, STYLE_OF.get(t, t)) for n, t in pars] == want_p,
          'spec %s vs contract %s' % (pars, want_p))

# ------------------------------------------------------ validate_static
vs = read(os.path.join(TOOLS, 'validate_static.py'))
m = c['manifest']
for const, want in (('SCHEMA', m['schema']), ('RUNTIME_API', c['runtimeApi']),
                    ('TYPES', tuple(m['types'])), ('TIERS', tuple(m['performanceTiers'])),
                    ('CONTROL_TYPES', tuple(m['controlTypes'])), ('REQUIRED', tuple(m['required'])),
                    ('OPTIONAL', tuple(m['optional'])), ('CAPABILITIES', tuple(m['capabilities']))):
    got = assigned(vs, const)
    check('validate_static %s' % const, got == want, '%r vs contract %r' % (got, want))
for key, pattern in (('displayName', r"0 < len\(v\) <= (\d+)"), ('tags', r"len\(tags\) > (\d+)"),
                     ('controls', r"len\(controls\) > (\d+)")):
    hit = re.search(pattern, vs)
    check('validate_static limit %s' % key, hit and int(hit.group(1)) == m['limits'][key],
          'limit %s not %s' % (hit.group(1) if hit else '?', m['limits'][key]))

# --------------------------------------------------- build_scene_library
sl = read(os.path.join(TOOLS, 'build_scene_library.py'))
check('scene_library LANES', assigned(sl, 'LANES') == lanes, 'lane list differs')
body = sl[sl.index("LIBRARY_LOGIC = r'''") + 20:]
body = body[:body.index("'''")] % {'lanes': lanes}
sc = assigned(body, 'CONTRACT')
for slot, spec_slot in c['slots'].items():
    got_in = [(n, f, r) for n, f, r in sc[slot]['inputs']]
    want_in = [(x['name'], x['family'], x['required']) for x in spec_slot['inputs']]
    check('scene_library %s inputs' % slot, got_in == want_in, '%s vs %s' % (got_in, want_in))
    check('scene_library %s page' % slot, sc[slot]['page'] == spec_slot['page'],
          '%r vs %r' % (sc[slot]['page'], spec_slot['page']))
    got_p = [(n, s, t) for n, s, t in sc[slot]['pars']]
    want_p = [(p['name'], p['style'], p.get('tokens')) for p in spec_slot['parameters']]
    check('scene_library %s parameters' % slot, got_p == want_p, '%s vs %s' % (got_p, want_p))
std = [(p['name'], p['style']) for p in c['standardParameters']['parameters']]
check('scene_library STANDARD', assigned(body, 'STANDARD') == std, 'standard parameters differ')
check('scene_library RESERVED', assigned(body, 'RESERVED') == c['reservedNames'], 'reserved names differ')
check('scene_library STYLE', sorted(assigned(body, 'STYLE')) == sorted(m['controlTypes']),
      'control styles cover %s' % sorted(assigned(body, 'STYLE')))

# --------------------------------------------- performer controls + adapter
pc = read(os.path.join(TOOLS, 'build_performer_controls.py'))
check('performer LANES', assigned(pc, 'LANES') == lanes, 'merge order differs from the contract')
check('performer CONTROLS', assigned(pc, 'CONTROLS') == c['performerControls'], 'controls differ')
scaled, centred = assigned(pc, 'SCALED'), assigned(pc, 'CENTRED')
for lane in c['lanes']:
    got = sorted(scaled.get(lane['name'], [])) or ([centred[lane['name']]] if lane['name'] in centred else [])
    check('performer %s' % lane['name'], sorted(got) == sorted(lane['performer']),
          'scaled by %s, contract %s' % (got, lane['performer']))
    check('performer %s centred' % lane['name'], (lane['name'] in centred) == ('centred' in lane),
          'centred mismatch')
bipolar = [l['name'] for l in c['lanes'] if l['range'] == [-1, 1]]
check('performer UNCLAMPED', assigned(pc, 'UNCLAMPED') == bipolar, 'unclamped lanes differ')
dp = read(os.path.join(TOOLS, 'diagnose_performer_controls.py'))
check('diagnose EXPECTED_LANES', assigned(dp, 'EXPECTED_LANES') == lanes, 'lane list differs')

# ---------------------------------------------------------------- modules
sys.path.insert(0, TOOLS)
import validate_static  # noqa: E402
for name in sorted(os.listdir(MODULES)):
    mf = os.path.join(MODULES, name, 'module.json')
    if not os.path.isfile(mf):
        continue
    man = json.loads(read(mf))
    check('module %s schema' % name, man.get('schema') == c['contract'], repr(man.get('schema')))
    check('module %s runtimeApi' % name,
          validate_static.satisfies(c['runtimeApi'], man.get('runtimeApi')) is True,
          '%r excludes %s' % (man.get('runtimeApi'), c['runtimeApi']))

# ----------------------------------------------------------------- report
print('%s %s (runtime API %s, frozen %s)' % (c['contract'], c['status'], c['runtimeApi'], c['frozen']))
print('%d checks, %d problem(s)' % (len(checked), len(problems)))
for p in problems:
    print('  DRIFT ' + p)
sys.exit(1 if problems else 0)
