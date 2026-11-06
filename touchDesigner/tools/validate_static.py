"""Static package checks for scene modules (SCENE_MODULE_SPEC s15.1).

Pure Python - runs outside TouchDesigner as well as inside it:

    python -I touchDesigner/tools/validate_static.py touchDesigner/modules

prints one block per module and exits 1 if any module fails. Inside
TouchDesigner, build_scene_library.py embeds this file in a DAT and calls
discover() / validate_dir() the same way.

Checks: required files, manifest JSON and every field rule in s5.1, optional
field types (s5.2), paths kept inside the module directory, the runtimeApi
range against RUNTIME_API (s16: never load outside it), the thumbnail's PNG
signature and 16:9 size (s4), control declarations (s11), duplicate ids across
the library, and - when TouchDesigner's toeexpand is available - absolute paths
baked into the .tox (s4: no dependency outside the module directory).

What needs TouchDesigner (connectors, parameters, declared controls matching
custom parameters, runtime behaviour) is checked in quarantine instead.
"""

import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

RUNTIME_API = '2.0.0'
SCHEMA = 'deckglow.scene-module/1'
TYPES = ('base_scene', 'hit_fx', 'brand_overlay', 'finish_fx')
TIERS = ('light', 'standard', 'heavy')
CONTROL_TYPES = ('float', 'integer', 'toggle', 'menu', 'color')
REQUIRED = ('schema', 'id', 'type', 'displayName', 'author', 'version',
            'runtimeApi', 'entry', 'thumbnail', 'performanceTier', 'tags', 'controls')
OPTIONAL = ('description', 'license', 'homepage', 'contentRating', 'capabilities')
CAPABILITIES = ('usesPython', 'usesAudioFileIn', 'supportsAlphaAssets')

ID_RE = re.compile(r'^[a-z][a-z0-9]*(\.[a-z0-9][a-z0-9_-]*)+$')
SEMVER_RE = re.compile(r'^(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?$')
COMPARATOR_RE = re.compile(r'^(>=|<=|>|<|=)?(\d+)\.(\d+)\.(\d+)$')
TAG_RE = re.compile(r'^[a-z0-9][a-z0-9-]*$')
PARAM_RE = re.compile(r'^[A-Z][a-z0-9]*$')      # TouchDesigner custom par naming
ABS_PATH_RE = re.compile(rb'(?<![A-Za-z])[A-Za-z]:[/\\][^\s"\']{2,}|/Users/[^\s"\']+|/home/[^\s"\']+')

DEFAULT_TOEEXPAND = r'C:\Program Files\Derivative\TouchDesigner\bin\toeexpand.exe'


# --------------------------------------------------------------- helpers
class Report(object):
    def __init__(self, folder):
        self.folder = folder
        self.checks = []
        self.manifest = None

    def add(self, check, status, detail=''):
        self.checks.append({'check': check, 'status': status, 'detail': detail})

    def ok(self, check, detail=''):
        self.add(check, 'pass', detail)

    def warn(self, check, detail):
        self.add(check, 'warn', detail)

    def fail(self, check, detail):
        self.add(check, 'fail', detail)

    @property
    def status(self):
        s = [c['status'] for c in self.checks]
        return 'fail' if 'fail' in s else 'warn' if 'warn' in s else 'pass'

    def as_dict(self):
        m = self.manifest or {}
        return {'folder': self.folder, 'id': m.get('id'), 'type': m.get('type'),
                'version': m.get('version'), 'displayName': m.get('displayName'),
                'status': self.status, 'checks': self.checks}


def _semver(text):
    m = SEMVER_RE.match(text or '')
    return tuple(int(m.group(i)) for i in (1, 2, 3)) if m else None


def satisfies(version, range_text):
    """True/False for a space-separated comparator range, None if malformed."""
    v = _semver(version)
    parts = (range_text or '').split()
    if v is None or not parts:
        return None
    for part in parts:
        m = COMPARATOR_RE.match(part)
        if not m:
            return None
        op, ref = m.group(1) or '=', tuple(int(m.group(i)) for i in (2, 3, 4))
        if not {'>=': v >= ref, '<=': v <= ref, '>': v > ref,
                '<': v < ref, '=': v == ref}[op]:
            return False
    return True


def _inside(folder, rel):
    """Resolve a manifest path; None if absolute or escaping the folder."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel) or re.match(r'^[A-Za-z]:', rel):
        return None
    full = os.path.normpath(os.path.join(folder, rel))
    root = os.path.normpath(folder)
    return full if os.path.commonpath([full, root]) == root else None


def png_size(path):
    with open(path, 'rb') as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b'\x89PNG\r\n\x1a\n' or head[12:16] != b'IHDR':
        return None
    return struct.unpack('>II', head[16:24])


def scan_tox(tox, toeexpand=None):
    """Absolute paths baked into a .tox. Returns (hits, note): hits is a list
    when the scan ran, 'unreadable' when toeexpand could not read the file,
    None when the scan could not run at all (no toeexpand)."""
    exe = toeexpand or DEFAULT_TOEEXPAND
    if not os.path.isfile(exe):
        return None, 'toeexpand not found'
    tmp = tempfile.mkdtemp(prefix='dg_tox_')
    try:
        copy = os.path.join(tmp, 'm.tox')
        shutil.copyfile(tox, copy)
        # toeexpand prints success and exits 1 (CLAUDE.md): check the output dir
        res = subprocess.run([exe, copy], cwd=tmp, capture_output=True, timeout=60)
        expanded = copy + '.dir'
        if not os.path.isdir(expanded):
            said = (res.stdout + res.stderr).decode('utf-8', 'replace').strip().replace('\n', ' ')
            return 'unreadable', said or 'no output'
        hits = []
        for dirpath, _, files in os.walk(expanded):
            for fn in files:
                if fn.endswith(('.data', '.chop', '.ts', '.oldacbo')):
                    continue                        # binary payloads
                with open(os.path.join(dirpath, fn), 'rb') as f:
                    for m in ABS_PATH_RE.finditer(f.read()):
                        rel = os.path.relpath(os.path.join(dirpath, fn), expanded)
                        hits.append('%s: %s' % (rel, m.group(0).decode('utf-8', 'replace')[:80]))
        return hits, ''
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------ the checks
def _check_controls(r, controls):
    if not isinstance(controls, list):
        r.fail('controls', 'must be a list')
        return
    if len(controls) > 8:
        r.fail('controls', '%d declared, maximum 8' % len(controls))
    seen = set()
    problems = []
    for i, c in enumerate(controls):
        where = 'controls[%d]' % i
        if not isinstance(c, dict):
            problems.append('%s is not an object' % where)
            continue
        p = c.get('parameter')
        if not isinstance(p, str) or not PARAM_RE.match(p):
            problems.append('%s parameter %r must be Capitalised (TouchDesigner custom name)' % (where, p))
        elif p in seen:
            problems.append('%s parameter %s declared twice' % (where, p))
        seen.add(p)
        if not isinstance(c.get('label'), str) or not c.get('label'):
            problems.append('%s has no label' % where)
        t = c.get('type')
        if t not in CONTROL_TYPES:
            problems.append('%s type %r not one of %s' % (where, t, ', '.join(CONTROL_TYPES)))
            continue
        if t in ('float', 'integer'):
            lo, hi, d = c.get('min'), c.get('max'), c.get('default')
            nums = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lo, hi, d))
            if not nums:
                problems.append('%s needs numeric min, max and default' % where)
            elif not lo <= d <= hi:
                problems.append('%s default %s outside %s..%s' % (where, d, lo, hi))
            if t == 'integer' and nums and not all(float(v).is_integer() for v in (lo, hi, d)):
                problems.append('%s is integer but has fractional values' % where)
        elif t == 'toggle' and not isinstance(c.get('default'), bool):
            problems.append('%s toggle default must be true/false' % where)
        elif t == 'menu':
            opts = c.get('options')
            if not isinstance(opts, list) or not opts:
                problems.append('%s menu needs a non-empty options list' % where)
            elif c.get('default') not in opts:
                problems.append('%s menu default not in options' % where)
    if problems:
        for p in problems:
            r.fail('controls', p)
    else:
        r.ok('controls', '%d declared' % len(controls))


def validate_dir(folder, toeexpand=None, scan=True):
    """Static checks for one module directory. Returns a Report."""
    r = Report(folder)
    mpath = os.path.join(folder, 'module.json')
    if not os.path.isfile(mpath):
        r.fail('files', 'module.json missing')
        return r
    try:
        with open(mpath, 'r', encoding='utf-8') as f:
            m = json.load(f)
    except (ValueError, UnicodeDecodeError) as e:
        r.fail('manifest', 'does not parse: %s' % e)
        return r
    if not isinstance(m, dict):
        r.fail('manifest', 'top level must be an object')
        return r
    r.manifest = m
    r.ok('manifest', 'parses')

    missing = [k for k in REQUIRED if k not in m]
    if missing:
        r.fail('required fields', 'missing ' + ', '.join(missing))
    else:
        r.ok('required fields')
    unknown = [k for k in m if k not in REQUIRED + OPTIONAL]
    if unknown:
        r.warn('unknown fields', ', '.join(sorted(unknown)) + ' (ignored)')

    (r.ok if m.get('schema') == SCHEMA else r.fail)('schema', repr(m.get('schema')))
    mid = m.get('id')
    (r.ok if isinstance(mid, str) and ID_RE.match(mid) else r.fail)(
        'id', '%r (lowercase reverse-domain)' % mid)
    (r.ok if m.get('type') in TYPES else r.fail)('type', repr(m.get('type')))
    for key in ('displayName', 'author'):
        v = m.get(key)
        good = isinstance(v, str) and 0 < len(v) <= 48
        (r.ok if good else r.fail)(key, '%r (1-48 characters)' % v)
    (r.ok if _semver(m.get('version')) else r.fail)('version', '%r (semantic version)' % m.get('version'))

    sat = satisfies(RUNTIME_API, m.get('runtimeApi'))
    if sat is None:
        r.fail('runtimeApi', '%r is not a valid range' % m.get('runtimeApi'))
    elif not sat:
        r.fail('runtimeApi', '%r excludes this runtime (%s)' % (m.get('runtimeApi'), RUNTIME_API))
    else:
        r.ok('runtimeApi', '%s satisfies %r' % (RUNTIME_API, m.get('runtimeApi')))

    (r.ok if m.get('performanceTier') in TIERS else r.fail)(
        'performanceTier', repr(m.get('performanceTier')))

    tags = m.get('tags')
    if not isinstance(tags, list) or len(tags) > 8 or not all(
            isinstance(t, str) and TAG_RE.match(t) for t in tags):
        r.fail('tags', '%r (0-8 lowercase tags)' % (tags,))
    else:
        r.ok('tags', '%d' % len(tags))

    _check_controls(r, m.get('controls'))

    caps = m.get('capabilities')
    if caps is not None:
        bad = [k for k, v in caps.items() if k in CAPABILITIES and not isinstance(v, bool)] \
            if isinstance(caps, dict) else ['(not an object)']
        (r.fail if bad else r.ok)('capabilities', ('non-boolean: ' + ', '.join(bad)) if bad else 'ok')
    for key in ('description', 'license', 'homepage', 'contentRating'):
        if key in m and not isinstance(m[key], str):
            r.fail(key, 'must be a string')

    entry = _inside(folder, m.get('entry'))
    if entry is None:
        r.fail('entry', '%r must be a relative path inside the module' % m.get('entry'))
    elif not os.path.isfile(entry):
        r.fail('entry', '%s not found' % m.get('entry'))
    elif not entry.lower().endswith('.tox'):
        r.fail('entry', '%s is not a .tox' % m.get('entry'))
    else:
        r.ok('entry', m.get('entry'))
        if scan:
            hits, note = scan_tox(entry, toeexpand)
            if hits is None:
                r.warn('tox paths', 'not scanned: ' + note)
            elif hits == 'unreadable':
                r.fail('entry', 'TouchDesigner cannot read the .tox: ' + note)
            elif hits:
                for h in hits[:5]:
                    r.fail('tox paths', 'absolute path baked in - ' + h)
            else:
                r.ok('tox paths', 'no absolute paths')

    thumb = _inside(folder, m.get('thumbnail'))
    if thumb is None:
        r.fail('thumbnail', '%r must be a relative path inside the module' % m.get('thumbnail'))
    elif not os.path.isfile(thumb):
        r.fail('thumbnail', '%s not found' % m.get('thumbnail'))
    else:
        size = png_size(thumb)
        if size is None:
            r.fail('thumbnail', 'not a PNG')
        else:
            w, h = size
            if abs(w / float(h) - 16 / 9.0) > 0.01:
                r.warn('thumbnail', '%dx%d is not 16:9' % size)
            elif size != (640, 360):
                r.warn('thumbnail', '%dx%d (640x360 recommended)' % size)
            else:
                r.ok('thumbnail', '640x360 PNG')
    return r


def discover(modules_root, toeexpand=None, scan=True):
    """Validate every directory under modules_root that has a module.json."""
    reports = []
    for name in sorted(os.listdir(modules_root)):
        folder = os.path.join(modules_root, name)
        if os.path.isdir(folder) and os.path.isfile(os.path.join(folder, 'module.json')):
            reports.append(validate_dir(folder, toeexpand, scan))
    ids = {}
    for r in reports:
        mid = (r.manifest or {}).get('id')
        if mid:
            ids.setdefault(mid, []).append(r)
    for mid, rs in ids.items():
        if len(rs) > 1:
            for r in rs:
                r.fail('id unique', '%s also used by %s' % (
                    mid, ', '.join(os.path.basename(o.folder) for o in rs if o is not r)))
    return reports


def main(argv):
    root = argv[1] if len(argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'modules')
    reports = discover(root)
    worst = 0
    for r in reports:
        d = r.as_dict()
        print('%-5s %-18s %s %s' % (d['status'].upper(), os.path.basename(r.folder),
                                     d['id'], d['version']))
        for c in d['checks']:
            if c['status'] != 'pass':
                print('        %-4s %-16s %s' % (c['status'], c['check'], c['detail']))
        worst = max(worst, {'pass': 0, 'warn': 0, 'fail': 1}[d['status']])
    print('%d module(s): %d pass, %d warn, %d fail' % (
        len(reports), sum(r.status == 'pass' for r in reports),
        sum(r.status == 'warn' for r in reports), sum(r.status == 'fail' for r in reports)))
    return worst


if __name__ == '__main__':
    sys.exit(main(sys.argv))
