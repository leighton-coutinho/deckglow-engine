"""Build, verify, install and remove creator packs (docs/PACK_FORMAT_SPEC.md).

Plain Python, runs outside TouchDesigner (it uses TouchDesigner's toeexpand to
inspect module .tox files, as validate_static.py does):

    python -I touchDesigner/tools/pack_tool.py build   <pack folder> [-o out.dgpack]
    python -I touchDesigner/tools/pack_tool.py verify  <file.dgpack>
    python -I touchDesigner/tools/pack_tool.py install <file.dgpack> [--force]
    python -I touchDesigner/tools/pack_tool.py remove  <pack id>
    python -I touchDesigner/tools/pack_tool.py list

Add --json (before the command) for one JSON object on stdout instead of
text - what the desktop app reads: {"ok", "command", "message", "checks",
"pack", "installed", ...}.

Packs install into touchDesigner/Packs/<pack id>/ unless --packs <dir> is
given. Installing never approves anything: in TouchDesigner the scene library
discovers the pack, quarantines each module, and the DJ approves per version.

Exit status 1 on any failure. verify and install write nothing until every
check has passed.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import validate_static as vs  # noqa: E402

PACK_SCHEMA = 'deckglow.pack/1'
MODULE_CONTRACT = 'deckglow.scene-module/1'
RESERVED_PREFIX = 'com.deckglow'
REQUIRED = ('schema', 'id', 'displayName', 'author', 'version', 'runtimeApi',
            'moduleContract', 'modules', 'files', 'signature')
OPTIONAL = ('palettes', 'description', 'license', 'homepage')
MAX_ENTRIES = 2000
MAX_FILE = 256 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MAX_MODULES = 64
PALETTE_ROLES = ('background', 'primary', 'secondary', 'accent')
DEFAULT_PACKS = os.path.normpath(os.path.join(TOOLS, '..', 'Packs'))
FIXED_TIME = (2026, 1, 1, 0, 0, 0)           # reproducible archives


JSON_OUT = None          # a dict in --json mode; commands fill it, main prints it


def _say(*args):
    if JSON_OUT is None:
        print(*args)
    else:
        JSON_OUT.setdefault('log', []).append(' '.join(str(a) for a in args))


def _meta(p):
    """What a person needs to decide whether to install a pack."""
    if not p:
        return None
    out = dict((k, p.get(k)) for k in ('id', 'displayName', 'author', 'version', 'description',
                                       'license', 'homepage', 'runtimeApi', 'signature'))
    out['modules'] = p.get('modules', [])
    out['palettes'] = len(p.get('palettes') or [])
    return out


def _report(**fields):
    if JSON_OUT is not None:
        JSON_OUT.update(fields)


class Result(object):
    def __init__(self):
        self.checks = []

    def add(self, status, check, detail=''):
        self.checks.append({'status': status, 'check': check, 'detail': detail})

    def ok(self, check, detail=''):
        self.add('pass', check, detail)

    def warn(self, check, detail):
        self.add('warn', check, detail)

    def fail(self, check, detail):
        self.add('fail', check, detail)

    @property
    def status(self):
        s = [c['status'] for c in self.checks]
        return 'fail' if 'fail' in s else 'warn' if 'warn' in s else 'pass'

    def show(self, title):
        _say('%s  %s' % (self.status.upper(), title))
        for c in self.checks:
            if c['status'] != 'pass':
                _say('    %-4s %-22s %s' % (c['status'], c['check'], c['detail']))
        _say('    %d checks, %d failed, %d warnings' % (
            len(self.checks), sum(c['status'] == 'fail' for c in self.checks),
            sum(c['status'] == 'warn' for c in self.checks)))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return 'sha256:' + h.hexdigest()


def pack_files(root):
    """Every file under root except pack.json, as forward-slash paths."""
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs.sort()
        for fn in sorted(files):
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, '/')
            if rel != 'pack.json':
                out.append(rel)
    return out


# --------------------------------------------------------- pack checks
def check_pack_dir(root, toeexpand=None):
    """Every pack rule except archive safety, on an unpacked pack folder."""
    r = Result()
    pj = os.path.join(root, 'pack.json')
    try:
        with open(pj, 'r', encoding='utf-8') as f:
            p = json.load(f)
        if not isinstance(p, dict):
            raise ValueError('top level must be an object')
        r.ok('pack.json', 'parses')
    except (OSError, ValueError) as e:
        r.fail('pack.json', 'missing or unreadable: %s' % e)
        return r, None

    missing = [k for k in REQUIRED if k not in p]
    (r.fail if missing else r.ok)('required fields', 'missing ' + ', '.join(missing) if missing else '')
    unknown = sorted(k for k in p if k not in REQUIRED + OPTIONAL)
    if unknown:
        r.warn('unknown fields', ', '.join(unknown) + ' (ignored)')

    (r.ok if p.get('schema') == PACK_SCHEMA else r.fail)('schema', repr(p.get('schema')))
    pid = p.get('id')
    if not (isinstance(pid, str) and vs.ID_RE.match(pid)):
        r.fail('id', '%r (lowercase reverse-domain)' % pid)
        pid = None
    elif pid == RESERVED_PREFIX or pid.startswith(RESERVED_PREFIX + '.'):
        r.fail('id', '%s is reserved for first-party DeckGlow content' % pid)
    else:
        r.ok('id', pid)
    for key in ('displayName', 'author'):
        v = p.get(key)
        (r.ok if isinstance(v, str) and 0 < len(v) <= 48 else r.fail)(key, '%r (1-48 characters)' % v)
    (r.ok if vs._semver(p.get('version')) else r.fail)('version', repr(p.get('version')))
    sat = vs.satisfies(vs.RUNTIME_API, p.get('runtimeApi'))
    if sat is None:
        r.fail('runtimeApi', '%r is not a valid range' % p.get('runtimeApi'))
    else:
        (r.ok if sat else r.fail)('runtimeApi', '%r %s runtime %s' % (
            p.get('runtimeApi'), 'includes' if sat else 'excludes', vs.RUNTIME_API))
    (r.ok if p.get('moduleContract') == MODULE_CONTRACT else r.fail)(
        'moduleContract', repr(p.get('moduleContract')))
    (r.ok if p.get('signature') is None else r.fail)(
        'signature', 'null (reserved in v1)' if p.get('signature') is None else 'must be null in v1')
    for key in ('description', 'license', 'homepage'):
        if key in p and not isinstance(p[key], str):
            r.fail(key, 'must be a string')

    # layout: only pack.json, modules/<folder>/..., palettes/...
    actual = pack_files(root)
    stray = [f for f in actual if not (f.startswith('modules/') or f.startswith('palettes/'))]
    for f in stray[:5]:
        r.fail('layout', '%s is outside modules/ and palettes/' % f)

    # hashes: every file listed, nothing extra, every hash right
    files = p.get('files')
    if not isinstance(files, dict):
        r.fail('files', 'must map each path to its sha256')
    else:
        listed, present = set(files), set(actual)
        for f in sorted(present - listed)[:5]:
            r.fail('files', '%s is in the pack but not listed' % f)
        for f in sorted(listed - present)[:5]:
            r.fail('files', '%s is listed but missing' % f)
        bad = [f for f in sorted(listed & present) if files[f] != sha256(os.path.join(root, f))]
        for f in bad[:5]:
            r.fail('files', '%s does not match its hash' % f)
        if present == listed and not bad:
            r.ok('files', '%d files, all hashes match' % len(present))

    # modules
    mods = p.get('modules')
    reports = []
    if not isinstance(mods, list) or not 1 <= len(mods) <= MAX_MODULES:
        r.fail('modules', 'need 1-%d module entries' % MAX_MODULES)
        mods = []
    folders = {f.split('/')[1] for f in actual if f.startswith('modules/') and f.count('/') >= 2}
    listed_folders = set()
    seen_ids = set()
    for i, e in enumerate(mods):
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) for k in ('folder', 'id', 'version')):
            r.fail('modules', 'entry %d needs folder, id and version' % i)
            continue
        folder, mid, ver = e['folder'], e['id'], e['version']
        listed_folders.add(folder)
        where = 'module %s' % folder
        if '/' in folder or '\\' in folder or folder in ('.', '..'):
            r.fail(where, 'folder must be a plain directory name')
            continue
        if mid in seen_ids:
            r.fail(where, '%s listed twice' % mid)
        seen_ids.add(mid)
        if pid and not mid.startswith(pid + '.'):
            r.fail(where, '%s must start with the pack id %s.' % (mid, pid))
        if mid == RESERVED_PREFIX or mid.startswith(RESERVED_PREFIX + '.'):
            r.fail(where, '%s is reserved for first-party DeckGlow content' % mid)
        mdir = os.path.join(root, 'modules', folder)
        if not os.path.isfile(os.path.join(mdir, 'module.json')):
            r.fail(where, 'no module.json')
            continue
        rep = vs.validate_dir(mdir, toeexpand, scan=True, policy='creator')
        rep.source = pid
        reports.append(rep)
        man = rep.manifest or {}
        if man.get('id') != mid or man.get('version') != ver:
            r.fail(where, 'pack.json says %s %s, module.json says %s %s'
                   % (mid, ver, man.get('id'), man.get('version')))
        for c in rep.checks:
            if c['status'] in ('fail', 'warn'):
                r.add(c['status'], where, '%s: %s' % (c['check'], c['detail']))
        if rep.status == 'pass':
            r.ok(where, '%s %s passes static and creator checks' % (mid, ver))
    for f in sorted(folders - listed_folders)[:5]:
        r.fail('modules', 'modules/%s is not listed in pack.json' % f)

    # palettes
    pals = p.get('palettes', [])
    if not isinstance(pals, list):
        r.fail('palettes', 'must be a list of paths')
        pals = []
    for rel in pals:
        where = 'palette %s' % rel
        if not (isinstance(rel, str) and rel.startswith('palettes/') and rel.endswith('.json')):
            r.fail(where, 'must be a .json under palettes/')
            continue
        full = vs._inside(root, rel)
        try:
            with open(full, 'r', encoding='utf-8') as f:
                pal = json.load(f)
            good = isinstance(pal.get('name'), str) and all(
                isinstance(pal.get(k), list) and len(pal[k]) == 3 and
                all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in pal[k])
                for k in PALETTE_ROLES)
            (r.ok if good else r.fail)(where, 'name and four roles of three 0..1 numbers'
                                        if good else 'needs a name and %s as [r, g, b] in 0..1' % ', '.join(PALETTE_ROLES))
        except (OSError, ValueError, TypeError, AttributeError) as e:
            r.fail(where, 'unreadable: %s' % e)
    return r, p


def check_archive(path, r):
    """Archive safety (PACK_FORMAT_SPEC s5). Returns the zipfile or None."""
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        r.fail('archive', 'not a valid .dgpack: %s' % e)
        return None
    infos = z.infolist()
    if len(infos) > MAX_ENTRIES:
        r.fail('archive', '%d entries, maximum %d' % (len(infos), MAX_ENTRIES))
    total, names = 0, set()
    for i in infos:
        n = i.filename
        parts = n.rstrip('/').split('/')
        if (n.startswith('/') or '\\' in n or re.match(r'^[A-Za-z]:', n) or '..' in parts
                or any(p in ('', '.') for p in parts)):
            r.fail('archive', 'unsafe entry name %r' % n)
        if stat.S_ISLNK(i.external_attr >> 16):
            r.fail('archive', '%r is a symlink' % n)
        if i.flag_bits & 0x1:
            r.fail('archive', '%r is encrypted' % n)
        if i.file_size > MAX_FILE:
            r.fail('archive', '%r is %d bytes, maximum %d' % (n, i.file_size, MAX_FILE))
        if n.lower() in names:
            r.fail('archive', '%r appears twice' % n)
        names.add(n.lower())
        total += i.file_size
    if total > MAX_TOTAL:
        r.fail('archive', '%d bytes unpacked, maximum %d' % (total, MAX_TOTAL))
    if 'pack.json' not in {i.filename for i in infos}:
        r.fail('archive', 'no pack.json at the root')
    if r.status != 'fail':
        r.ok('archive', '%d entries, %d bytes unpacked' % (len(infos), total))
    return z


def verify(path, toeexpand=None, keep=False):
    """All checks on a .dgpack. Returns (Result, pack.json dict, temp dir or None)."""
    r = Result()
    z = check_archive(path, r)
    if z is None or r.status == 'fail':
        return r, None, None
    tmp = tempfile.mkdtemp(prefix='dg_pack_')
    try:
        with z:
            for i in z.infolist():
                if i.is_dir():
                    continue
                dest = os.path.join(tmp, *i.filename.split('/'))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(i) as src, open(dest, 'wb') as out:
                    shutil.copyfileobj(src, out)
        res, p = check_pack_dir(tmp, toeexpand)
        r.checks.extend(res.checks)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if keep and r.status != 'fail':
        return r, p, tmp
    shutil.rmtree(tmp, ignore_errors=True)
    return r, p, None


# ----------------------------------------------------------- commands
def cmd_build(src, out, toeexpand=None):
    pj = os.path.join(src, 'pack.json')
    with open(pj, 'r', encoding='utf-8') as f:
        p = json.load(f)
    p['files'] = {rel: sha256(os.path.join(src, rel)) for rel in pack_files(src)}
    p.setdefault('signature', None)
    with open(pj, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(p, f, indent=2)
        f.write('\n')
    res, p = check_pack_dir(src, toeexpand)
    res.show('pack folder %s' % src)
    if res.status == 'fail':
        _say('not built: fix the failures above')
        return 1
    out = out or os.path.join(os.path.dirname(os.path.abspath(src)),
                              '%s-%s.dgpack' % (p['id'], p['version']))
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in ['pack.json'] + pack_files(src):
            info = zipfile.ZipInfo(rel, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(os.path.join(src, rel), 'rb') as f:
                z.writestr(info, f.read())
    _say('built %s (%d bytes, %s)' % (out, os.path.getsize(out), sha256(out)[:23]))
    return 0


def _installed(packs, pid):
    try:
        with open(os.path.join(packs, pid, 'installed.json'), 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def cmd_verify(path, packs=DEFAULT_PACKS, toeexpand=None):
    res, p, _ = verify(path, toeexpand)
    res.show(path)
    prev = _installed(packs, p['id']) if p and p.get('id') else None
    if p:
        msg = '%s %s' % (p['id'], {'pass': 'passes every check', 'warn': 'passes with warnings'}.get(res.status, 'fails'))
    else:
        msg = 'not a readable pack'
    _report(ok=res.status != 'fail', status=res.status, checks=res.checks, pack=_meta(p),
            installed=prev.get('version') if prev else None, message=msg)
    return 1 if res.status == 'fail' else 0


def cmd_install(path, packs, force=False, toeexpand=None):
    res, p, tmp = verify(path, toeexpand, keep=True)
    res.show(path)
    _report(ok=False, status=res.status, checks=res.checks, pack=_meta(p))
    if res.status == 'fail':
        _say('not installed')
        _report(message='not installed: the pack fails its checks')
        return 1
    try:
        pid, ver = p['id'], p['version']
        prev = _installed(packs, pid)
        if prev and not force and vs._semver(ver) <= vs._semver(prev.get('version', '0.0.0')):
            _say('not installed: %s %s is already installed (use --force to reinstall or downgrade)'
                  % (pid, prev.get('version')))
            _report(code='already_installed', installed=prev.get('version'),
                    message='%s %s is already installed' % (pid, prev.get('version')))
            return 1
        os.makedirs(packs, exist_ok=True)
        dest = os.path.join(packs, pid)
        staging = dest + '.installing'
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(tmp, staging)
        with open(os.path.join(staging, 'installed.json'), 'w', encoding='utf-8') as f:
            json.dump({'id': pid, 'version': ver,
                       'installed': datetime.datetime.now().isoformat(timespec='seconds'),
                       'from': os.path.basename(path), 'archive': sha256(path),
                       'modules': p['modules']}, f, indent=2)
        old = dest + '.old'
        shutil.rmtree(old, ignore_errors=True)
        if os.path.isdir(dest):
            os.rename(dest, old)
        os.rename(staging, dest)
        shutil.rmtree(old, ignore_errors=True)
        _say('installed %s %s into %s%s' % (pid, ver, dest,
              ' (was %s)' % prev.get('version') if prev else ''))
        _say('next: in TouchDesigner, Scan and Validate in the scene library, then Approve each module')
        _report(ok=True, dest=dest, previous=prev.get('version') if prev else None,
                message='installed %s %s' % (pid, ver))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_remove(pid, packs):
    dest = os.path.join(packs, pid)
    if not vs.ID_RE.match(pid or '') or not os.path.isfile(os.path.join(dest, 'installed.json')):
        _say('no installed pack %r in %s' % (pid, packs))
        _report(ok=False, code='not_installed', message='no installed pack %r' % pid)
        return 1
    shutil.rmtree(dest)
    _say('removed %s (approvals in library/approved.json are left; they no longer match a module)' % pid)
    _report(ok=True, message='removed %s' % pid)
    return 0


def cmd_list(packs):
    if not os.path.isdir(packs):
        _say('no packs installed (%s does not exist)' % packs)
        _report(ok=True, packs=[])
        return 0
    rows = [_installed(packs, d) for d in sorted(os.listdir(packs))]
    rows = [x for x in rows if x]
    for x in rows:
        try:
            with open(os.path.join(packs, x['id'], 'pack.json'), 'r', encoding='utf-8') as f:
                x['pack'] = _meta(json.load(f))
        except (OSError, ValueError):
            x['pack'] = None
    _report(ok=True, packs=rows)
    for x in rows:
        _say('%-32s %-8s %d module(s)  installed %s' % (x['id'], x['version'], len(x.get('modules', [])), x['installed']))
    if not rows:
        _say('no packs installed')
    return 0


def main(argv):
    ap = argparse.ArgumentParser(prog='pack_tool.py', description='DeckGlow creator packs')
    ap.add_argument('--packs', default=DEFAULT_PACKS, help='install directory')
    ap.add_argument('--json', action='store_true', help='one JSON object on stdout instead of text')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('folder')
    b.add_argument('-o', '--out')
    sub.add_parser('verify').add_argument('file')
    i = sub.add_parser('install')
    i.add_argument('file')
    i.add_argument('--force', action='store_true')
    sub.add_parser('remove').add_argument('id')
    sub.add_parser('list')
    a = ap.parse_args(argv[1:])
    global JSON_OUT
    if a.json:
        JSON_OUT = {'command': a.cmd}
    try:
        if a.cmd == 'build':
            code = cmd_build(a.folder, a.out)
        elif a.cmd == 'verify':
            code = cmd_verify(a.file, a.packs)
        elif a.cmd == 'install':
            code = cmd_install(a.file, a.packs, a.force)
        elif a.cmd == 'remove':
            code = cmd_remove(a.id, a.packs)
        else:
            code = cmd_list(a.packs)
    except Exception as e:                       # e.g. an unreadable file
        if JSON_OUT is None:
            raise
        JSON_OUT.update(ok=False, code='error', message='%s: %s' % (type(e).__name__, e))
        code = 1
    if JSON_OUT is not None:
        JSON_OUT['ok'] = code == 0
        print(json.dumps(JSON_OUT))
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv))
