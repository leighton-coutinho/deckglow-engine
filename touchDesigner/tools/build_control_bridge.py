"""Builds /project1/control_bridge: the deckglow.control/1 WebSocket server.

Run inside TouchDesigner's textport (Alt+T), after the stack, palette, brand,
scene library and projector builders:

    exec(open(r'C:\\Users\\ljlco\\source\\repos\\CodexProjects\\ReactiveVisualEngineCode\\touchDesigner\\tools\\build_control_bridge.py').read())

Contract: docs/FRONTEND_MESSAGE_CONTRACT.md. The desktop app (and
tools/bridge_client.py) connect to ws://127.0.0.1:<Port>/ and authenticate
with the token in touchDesigner/bridge_token.txt.

    control_bridge
      protocol         bridge_protocol.py, embedded: validation and dispatch
      runtime          the adapter: applies messages to the existing runtime
      server           Web Server DAT (WebSocket), callbacks -> runtime
      frame_exec       Execute DAT: status 4x/s and preview frames
      preview_src      Select TOP of /project1/OUTPUT
      preview          Resolution TOP at the subscribed width (JPEG source)

It changes nothing else in the project: every request goes through the same
parameters and library functions a person would use (host Moduleactive,
LoadApproved, performer_controls, palette_source, brand_table, output, ...).
Re-running rebuilds it; Port and Active carry across.
"""

import json
import os
import secrets

ROOT = op('/project1')
NAME = 'control_bridge'
TOOLS = os.path.join(project.folder, 'tools')
PROTOCOL_SRC = os.path.join(TOOLS, 'bridge_protocol.py')
CONTRACT = os.path.normpath(os.path.join(project.folder, '..', 'docs', 'contract',
                                         'deckglow.scene-module-1.json'))
TOKEN_FILE = os.path.join(project.folder, 'bridge_token.txt')

for path in (PROTOCOL_SRC, CONTRACT):
    if not os.path.isfile(path):
        raise RuntimeError('missing %s' % path)

# Slot parameters a frontend may set, from the frozen contract.
with open(CONTRACT, 'r', encoding='utf-8') as f:
    contract = json.load(f)
SLOT_PARAMS = {}
for slot, spec in contract['slots'].items():
    decls = {}
    for p in spec['parameters']:
        if p['style'] == 'Float':
            lo, hi = p.get('range', [0, 1])
            decls[p['name']] = {'type': 'float', 'min': lo, 'max': hi}
        elif p['style'] == 'Menu':
            decls[p['name']] = {'type': 'menu', 'options': p['tokens']}
        elif p['style'] == 'Toggle':
            decls[p['name']] = {'type': 'toggle'}
        elif p['style'] == 'Int':
            decls[p['name']] = {'type': 'integer', 'min': p.get('range', [0, 1 << 30])[0],
                                'max': p.get('range', [0, 1 << 30])[1]}
    SLOT_PARAMS[slot] = decls

if not os.path.isfile(TOKEN_FILE):
    with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
        f.write(secrets.token_urlsafe(24))

RUNTIME = r'''
# control_bridge runtime adapter. See build_control_bridge.py.
import json
import os
import time

P = op('protocol').module
SLOT_HOST = {'base_scene': 'module_host', 'hit_fx': 'hit_host',
             'brand_overlay': 'brand_host', 'finish_fx': 'finish_host'}
SLOT_PARAMS = %(slot_params)s
TOKEN_FILE = os.path.join(project.folder, 'bridge_token.txt')   # this computer's project folder
STATUS_EVERY = 15                     # frames (4 per second at 60 fps)

_g = {'proto': None, 'frame': 0, 'last_t': None, 'fps': 0.0, 'manifests': {}, 'next_preview': {},
      'ready': True, 'startup': None}


def _proto():
    if _g['proto'] is None:
        with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
            token = f.read().strip()
        _g['proto'] = P.Protocol(Adapter(), token)
    return _g['proto']


def _server():
    return parent().op('server')


def _send(out):
    srv = _server()
    for client, msg in out:
        try:
            srv.webSocketSendText(client, json.dumps(msg))
        except Exception as e:
            print('control_bridge: send to %%s failed: %%s' %% (client, e))


# ------------------------------------------------------- server callbacks
def OnOpen(client):
    if not _proto().open(client):
        print('control_bridge: refused non-local client %%s' %% client)
        _server().webSocketClose(client)


def OnClose(client):
    _proto().close(client)


def OnText(client, data):
    _send(_proto().receive(client, data))


def OnHTTP(request, response):
    if request.get('method') == 'GET' and request.get('uri') == '/health':
        response['statusCode'], response['statusReason'] = 200, 'OK'
        response['data'] = 'deckglow'
    else:
        response['statusCode'], response['statusReason'] = 404, 'Not Found'
        response['data'] = ''
    return response


# -------------------------------------------------------------- startup
HOSTS_ALL = ('module_host', 'hit_host', 'module_host_b', 'hit_host_b', 'brand_host', 'finish_host')
HOST_SLOT = {'module_host': 'base_scene', 'module_host_b': 'base_scene', 'hit_host': 'hit_fx',
             'hit_host_b': 'hit_fx', 'brand_host': 'brand_overlay', 'finish_host': 'finish_fx'}


def _relocate(path):
    """A Modulepath as it should be stored: relative to this project folder.
    A path saved on another computer or in another folder is mapped by the
    part after its touchDesigner/ (or Packs/, modules/) folder."""
    p = (path or '').replace('\\', '/').strip()
    if not p or not os.path.isabs(p):
        return p
    root = project.folder.replace('\\', '/').rstrip('/') + '/'
    if p.lower().startswith(root.lower()):
        return p[len(root):]
    for marker in ('/touchDesigner/', '/Packs/', '/modules/'):
        i = p.find(marker)
        if i >= 0:
            rest = p[i + len(marker):] if marker == '/touchDesigner/' else p[i + 1:]
            if os.path.isfile(os.path.join(project.folder, rest)):
                return rest
    return p


def _apply(m, controls):
    for name, value in (controls or {}).items():
        if isinstance(value, list):
            pars = [getattr(m.par, name + c, None) for c in 'rgb']
            if all(x is not None for x in pars):
                for x, v in zip(pars, value):
                    x.val = v
        elif getattr(m.par, name, None) is not None:
            getattr(m.par, name).val = value


def _norm(p):
    return os.path.normcase(os.path.normpath(p)) if p else ''


def _library_fingerprint():
    """Size and modification time of everything the library's scan is built
    from: each module folder's files (first-party and packs), approved.json
    and the validation reports, with their full paths. Equal fingerprints mean
    the saved scan still describes this folder; a copied project (other
    paths) or an update (new files) differs."""
    import hashlib
    root = project.folder
    entries = []

    def add(path):
        try:
            st = os.stat(path)
        except OSError:
            return
        entries.append((_norm(path), st.st_size, st.st_mtime_ns))

    def add_dir(folder, only=None):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            return
        for n in names:
            f = os.path.join(folder, n)
            if os.path.isfile(f) and (only is None or n.endswith(only)):
                add(f)

    def add_modules(mods):
        try:
            names = sorted(os.listdir(mods))
        except OSError:
            return
        for n in names:
            folder = os.path.join(mods, n)
            if os.path.isfile(os.path.join(folder, 'module.json')):
                add_dir(folder)

    add_modules(os.path.join(root, 'modules'))
    packs = os.path.join(root, 'Packs')
    if os.path.isdir(packs):
        for pid in sorted(os.listdir(packs)):
            add(os.path.join(packs, pid, 'pack.json'))
            add_modules(os.path.join(packs, pid, 'modules'))
    add(os.path.join(root, 'library', 'approved.json'))
    add_dir(os.path.join(root, 'validation'), '.json')
    return hashlib.sha1(repr(entries).encode('utf-8')).hexdigest()


def MarkStarting():
    """The project is opening: clients hear 'starting' until Startup() is done."""
    _g['ready'] = False
    _g['startup'] = {'opened': time.time()}


def _set_ready(ready):
    if _g.get('ready') == ready:
        return
    _g['ready'] = ready
    st = _g.get('startup') or {}
    if ready and 'opened' in st:
        st['ready_after_s'] = round(time.time() - st['opened'], 2)
    try:
        _send(_proto().notify({'type': 'runtime', 'ready': ready, 'startup': st}))
    except Exception as e:
        print('control_bridge: could not announce readiness: %%s' %% e)


def Startup():
    """A moment after the project opens: make every module path relative to
    this folder; rescan the library unless nothing it reads has changed since
    the last startup (a saved scan holds the folders of the computer that saved
    it, and an update brings new versions, approvals and reports); refresh
    pack palettes; reload every module that was not loaded from the file this
    project points to - missing, or another folder's copy (a project copied
    from a repository would otherwise keep running the repository's modules).
    Then tell clients the runtime is ready."""
    t0 = time.perf_counter()
    moved, reload = [], []
    for name in HOSTS_ALL:
        h = op('/project1/' + name)
        if h is None:
            continue
        old = h.par.Modulepath.eval()
        new = _relocate(old)
        if new != old:
            h.par.Modulepath = new
            moved.append(name)
        if not new:
            continue
        want = new if os.path.isabs(new) else os.path.join(project.folder, new)
        m = h.op('module')
        ext = m.par.externaltox.eval() if m is not None else ''
        if m is None or m.op('out1') is None or _norm(ext) != _norm(want) or not os.path.isfile(want):
            reload.append(name)
    t1 = time.perf_counter()
    # the slowest part of startup is a rescan (toeexpand on every module): skip
    # it when nothing it reads has changed since the last startup's scan
    rescanned = False
    lib = op('/project1/scene_library/library')
    if lib is not None:
        fp = _library_fingerprint()
        holder = lib.parent()
        if not holder.fetch('static', {}) or holder.fetch('startup_fingerprint', None) != fp:
            lib.module.Scan(quiet=True)
            holder.store('startup_fingerprint', fp)
            rescanned = True
    t2 = time.perf_counter()
    logic = op('/project1/palette_source/palette_logic')
    if logic is not None and hasattr(logic.module, 'RefreshPacks'):
        logic.module.RefreshPacks()
    for name in reload:
        op('/project1/' + name).par.Load.pulse()
    st = _g.get('startup') or {}
    st.update(paths_s=round(t1 - t0, 3), scan_s=round(t2 - t1, 3), rescanned=rescanned,
              total_s=round(time.perf_counter() - t0, 3), moved=len(moved), reloaded=reload)
    _g['startup'] = st
    print('control_bridge: startup - %%d path(s) made relative, %%s, %%d module(s) reloaded %%s, %%.2f s, project %%s'
          %% (len(moved), 'library rescanned' if rescanned else 'library scan current', len(reload),
             reload, st['total_s'], project.folder))
    if reload:
        # loaded modules warm for a few frames; ready once their controls are back
        run("op(%%r).module._ReapplyControls(%%r)" %% (me.path, reload), delayFrames=10)
    else:
        _set_ready(True)


def _ReapplyControls(names):
    """A reloaded module starts at its defaults: put back what the frontend set."""
    looks = _looks()
    for name in names:
        h = op('/project1/' + name)
        m = h.op('module') if h is not None else None
        if m is None:
            continue
        if looks is not None and name in ('module_host', 'hit_host', 'module_host_b', 'hit_host_b'):
            ctl = looks.op('look_logic').module.Controls(name)
        else:
            ctl = _desired().get(HOST_SLOT[name], {})
        _apply(m, ctl)
    _set_ready(True)


# --------------------------------------------------------------- frames
def Frame():
    p = _proto()
    _g['frame'] += 1
    now = time.perf_counter()
    if _g['last_t'] is not None:
        dt = now - _g['last_t']
        if dt > 0:
            _g['fps'] = 0.9 * _g['fps'] + 0.1 * (1.0 / dt) if _g['fps'] else 1.0 / dt
    _g['last_t'] = now

    if _g['frame'] %% STATUS_EVERY == 0:
        subs = [c for c, _ in p.subscribers('status')]
        if subs:
            msg = {'type': 'status', 'status': Status()}
            _send([(c, msg) for c in subs])

    if _g.get('validating') is not None:
        _watch_validation(p)

    looks = _looks()
    if looks is not None:
        v = int(looks.par.Version.eval())
        if v != _g.get('look_version'):
            _g['look_version'] = v
            _send(p.notify({'type': 'state', 'state': p.rt.state()}))

    viewers = p.subscribers('preview')
    if viewers:
        prev = parent().op('preview')
        width = max(v['width'] for _, v in viewers)
        if prev.par.resolutionw.eval() != width:
            prev.par.resolutionw = width
            prev.par.resolutionh = int(round(width * 9 / 16.0))
        due = []
        for c, v in viewers:
            nxt = _g['next_preview'].get(c, 0)
            if now >= nxt:
                due.append(c)
                _g['next_preview'][c] = now + 1.0 / v['fps']
        if due:
            try:
                # nothing views this TOP, so it never cooks by itself (lazy
                # cooking): without the forced cook saveByteArray returns a
                # stale texture - 256x256 before the first cook, then the
                # input size with the custom resolution never applied
                prev.cook(force=True)
                data = bytes(prev.saveByteArray('.jpg'))
            except Exception as e:
                print('control_bridge: preview failed: %%s' %% e)
                return
            for c in due:
                try:
                    _server().webSocketSendBinary(c, data)
                except Exception:
                    pass


def _watch_validation(p):
    """The scene library runs validation as a chain of delayed calls; this
    notices when its queue drains and tells every client the result."""
    v = _g['validating']
    lib = _lib()
    if lib._job.get('gen') is not None or lib._queue:
        v['idle'] = 0
        return
    v['idle'] += 1
    if v['idle'] < 3:          # _next() rescans one frame after the job ends
        return
    _g['validating'] = None
    rep = lib._load_report(v['folder'])
    _send(p.notify({'type': 'validation', 'module': v['module'], 'phase': 'done',
                    'result': (rep or {}).get('result', 'fail'), 'report': _trim_report(rep)}))
    _send(p.notify({'type': 'libraryChanged', 'module': v['module']}))


def _trim_report(rep):
    """A quarantine report (validation/<folder>.json) as the app shows it."""
    if not rep:
        return None
    checks = []
    for c in ((rep.get('static') or {}).get('checks') or []):
        checks.append({'stage': 'static', 'check': c.get('check'), 'status': c.get('status'), 'detail': c.get('detail', '')})
    for stage in ('interface', 'runtime', 'admission'):
        for c in rep.get(stage) or []:
            checks.append({'stage': stage, 'check': c.get('check'), 'status': c.get('status'), 'detail': c.get('detail', '')})
    return {'module': rep.get('id'), 'version': rep.get('version'), 'type': rep.get('type'),
            'result': rep.get('result'), 'started': rep.get('started'), 'finished': rep.get('finished'),
            'touchdesigner': rep.get('touchdesigner'), 'performance': rep.get('performance') or {},
            'checks': checks}


def Status():
    out = {'fps': round(_g['fps'], 1), 'slots': {}, 'limiter': {}, 'lanes': {},
           'ready': bool(_g.get('ready', True)), 'startup': _g.get('startup')}
    looks = _looks()
    if looks is not None:
        out['take'] = looks.op('look_logic').module.State()
    for slot in SLOT_HOST:
        h = op('/project1/' + _host_name(slot))
        if h is not None:
            out['slots'][slot] = {'status': h.par.Status.eval(),
                                  'cookMs': round(float(h.childrenCPUCookTime), 3)}
    lim = op('/project1/output/limiter')
    if lim is not None:
        for ch in ('held', 'transitions', 'gain'):
            c = lim[ch]
            out['limiter'][ch] = round(c.eval(), 4) if c is not None else None
    mo = op('/project1/MOTION_OUT')
    if mo is not None:
        out['lanes'] = dict((c.name, round(c.eval(), 4)) for c in mo.chans())
    return out


# -------------------------------------------------------------- adapter
def _err(code, message):
    return P.BridgeError(code, message)


def _looks():
    return op('/project1/looks')


def _look_logic():
    l = _looks()
    if l is None:
        raise _err('failed', 'no look runtime - run build_look_runtime.py')
    return l.op('look_logic').module


def _host_name(slot):
    """The host on screen for a slot. Scene and Hits live in two stacks once
    the look runtime exists; every live edit goes to the one being shown."""
    l = _looks()
    if l is not None and slot in ('base_scene', 'hit_fx'):
        return l.op('look_logic').module.ActiveHost(slot)
    return SLOT_HOST[slot]


def _host(slot):
    name = _host_name(slot)
    h = op('/project1/' + name)
    if h is None:
        raise _err('failed', 'no %%s - run build_module_host.py' %% name)
    return h


def _controls_of(slot):
    """Values the frontend set for the module in a slot's host (kept by the
    look runtime per host, so a TAKE and a saved look carry them)."""
    l = _looks()
    if l is not None:
        return l.op('look_logic').module.Controls(_host_name(slot))
    return _desired().setdefault(slot, {})


def _look_call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except Exception as e:
        if hasattr(e, 'code') and hasattr(e, 'message'):      # look_logic.LookError
            raise _err(e.code, e.message)
        raise


def _lib():
    d = op('/project1/scene_library/library')
    if d is None:
        raise _err('failed', 'no scene library - run build_scene_library.py')
    return d.module


def _manifest_at(tox_path):
    """The module.json next to a loaded .tox (cached by path)."""
    if not tox_path:
        return None
    if not os.path.isabs(tox_path):
        tox_path = os.path.join(project.folder, tox_path)
    if tox_path not in _g['manifests']:
        try:
            with open(os.path.join(os.path.dirname(tox_path), 'module.json'), 'r', encoding='utf-8') as f:
                _g['manifests'][tox_path] = json.load(f)
        except (OSError, ValueError):
            _g['manifests'][tox_path] = None
    return _g['manifests'][tox_path]


def _desired():
    d = parent().storage.get('controls')
    if d is None:
        d = dict((s, {}) for s in SLOT_HOST)
        parent().store('controls', d)
    return d


class Adapter(object):
    # ---------------------------------------------------------- reads
    def state(self):
        slots = {}
        for slot in SLOT_HOST:
            h = op('/project1/' + _host_name(slot))
            if h is None:
                continue
            loaded = h.op('module') is not None
            man = _manifest_at(h.par.Modulepath.eval()) if loaded else None
            slots[slot] = {'module': man.get('id') if man else None,
                           'enabled': bool(h.par.Moduleactive.eval()),
                           'intensity': round(float(h.par.Intensity.eval()), 4),
                           'controls': dict(_controls_of(slot))}
        pc = op('/project1/performer_controls')
        perf = {}
        if pc is not None:
            for i in range(pc.seq.const.numBlocks):
                perf[getattr(pc.par, 'const%%dname' %% i).eval()] = round(
                    float(getattr(pc.par, 'const%%dvalue' %% i).eval()), 4)
        ps = op('/project1/palette_source')
        palette, background = {}, None
        if ps is not None:
            name, idx = ps.op('palette_logic').module.Selected()
            palette = {'index': idx, 'name': name}
            if getattr(ps.par, 'Backgroundoverride', None) is not None and ps.par.Backgroundoverride.eval():
                background = [round(float(getattr(ps.par, 'Backgroundcolor' + c).eval()), 4) for c in 'rgb']
        bt = op('/project1/brand_table')
        brand = {}
        if bt is not None:
            rows = dict((bt[r, 0].val, bt[r, 1].val) for r in range(1, bt.numRows))
            brand = {'displayName': rows.get('displayName', ''), 'mode': rows.get('mode', 'logo_and_name'),
                     'subtitle': rows.get('subtitle', ''),
                     'scale': _float(rows.get('scale'), 1.0), 'opacity': _float(rows.get('opacity'), 1.0)}
        o = op('/project1/output')
        output = {}
        if o is not None:
            output = {'blackout': bool(o.par.Blackout.eval()),
                      'maxBrightness': round(float(o.par.Maxbrightness.eval()), 4),
                      'flashLimit': bool(o.par.Flashlimit.eval()),
                      'maxFlashes': int(o.par.Maxflashes.eval())}
        mode = op('/project1/engine_in/engine_input_mode')
        tb = op('/project1/engine_in/test_bpm')
        engine = {'mode': 'demo' if mode is not None and int(mode.par.index.eval()) == 1 else 'live',
                  'bpm': round(float(tb.par.const0value.eval()), 2) if tb is not None else 120.0}
        out = {'schema': P.SHOW, 'slots': slots, 'performer': perf, 'palette': palette,
               'background': background, 'brand': brand, 'output': output, 'engine': engine}
        l = _looks()
        if l is not None:
            ll = l.op('look_logic').module
            out['looks'] = [None if e is None else {'name': e['name'], 'look': e['look']} for e in ll.Bank()]
            out['transition'] = ll.Transition()
            t = ll.State()
            out['take'] = {'phase': t['phase'], 'index': t['index'], 'current': t['current'],
                           'problems': t['problems']}
        return out

    def library(self, rescan=False):
        lib = _lib()
        t = op('/project1/scene_library/LIBRARY')
        if rescan or t.numRows <= 1:
            lib.Scan(quiet=True)        # slow: toeexpand on every module
            logic = op('/project1/palette_source/palette_logic')
            if logic is not None and hasattr(logic.module, 'RefreshPacks'):
                logic.module.RefreshPacks()     # palettes of installed / removed packs
        static = op('/project1/scene_library').fetch('static', {})
        mods = []
        for r in range(1, t.numRows):
            folder = t[r, 'folder'].val
            st = static.get(folder) or {}
            mdir = st.get('folder') or ''
            man = {}
            try:
                with open(os.path.join(mdir, 'module.json'), 'r', encoding='utf-8') as f:
                    man = json.load(f)
            except (OSError, ValueError):
                pass
            mods.append({'id': t[r, 'id'].val, 'type': t[r, 'type'].val,
                         'version': t[r, 'version'].val, 'displayName': t[r, 'displayName'].val,
                         'source': t[r, 'source'].val, 'static': t[r, 'static'].val,
                         'quarantine': t[r, 'quarantine'].val, 'approved': t[r, 'approved'].val,
                         'thumbnail': os.path.join(mdir, man.get('thumbnail', 'thumbnail.png')).replace('\\', '/'),
                         'controls': man.get('controls', [])})
        pal = []
        lt = op('/project1/palette_source/library')
        if lt is not None:
            pal = [lt[r, 0].val for r in range(1, lt.numRows)]
        return {'modules': mods, 'palettes': pal}

    def controls(self, slot):
        decls = dict(SLOT_PARAMS.get(slot, {}))
        h = op('/project1/' + _host_name(slot))
        if h is not None and h.op('module') is not None:
            man = _manifest_at(h.par.Modulepath.eval()) or {}
            for c in man.get('controls', []):
                decls[c.get('parameter')] = {'type': c.get('type'), 'min': c.get('min'),
                                             'max': c.get('max'), 'options': c.get('options', [])}
        return decls

    # --------------------------------------------------------- writes
    def slot_enabled(self, slot, on):
        _host(slot).par.Moduleactive = on

    def slot_intensity(self, slot, v):
        _host(slot).par.Intensity = v

    def slot_module(self, slot, mid):
        h = _host(slot)
        _controls_of(slot).clear()
        if mid is None:
            h.par.Unload.pulse()
            return
        lib = _lib()                     # uses the last Scan; never rescans mid-show
        folder = lib._folder_for(mid)
        if folder is None:
            raise _err('not_approved', '%%s is not in the library' %% mid)
        st = op('/project1/scene_library').fetch('static', {}).get(folder) or {}
        if st.get('type') != slot:
            raise _err('wrong_slot', '%%s is a %%s, not a %%s' %% (mid, st.get('type'), slot))
        if not lib.IsApproved(mid):
            raise _err('not_approved', '%%s is not approved for its current version' %% mid)
        if not lib.LoadApproved(_host_name(slot), mid):
            raise _err('failed', 'LoadApproved refused %%s' %% mid)

    def set_control(self, slot, name, value):
        m = _host(slot).op('module')
        if m is None:
            raise _err('not_loaded', 'no module is loaded in %%s' %% slot)
        if isinstance(value, list):                    # colour control
            for comp, v in zip('rgb', value):
                p = getattr(m.par, name + comp, None)
                if p is None:
                    raise _err('unknown_control', '%%s has no colour parameter %%s' %% (slot, name))
                p.val = v
        else:
            p = getattr(m.par, name, None)
            if p is None:
                raise _err('unknown_control', 'the module in %%s has no parameter %%s' %% (slot, name))
            p.val = value
        _controls_of(slot)[name] = value

    def performer(self, name, v):
        pc = op('/project1/performer_controls')
        for i in range(pc.seq.const.numBlocks):
            if getattr(pc.par, 'const%%dname' %% i).eval() == name:
                getattr(pc.par, 'const%%dvalue' %% i).val = v
                return
        raise _err('failed', 'performer_controls has no %%s' %% name)

    def palette(self, index=None, name=None):
        ps = op('/project1/palette_source')
        if ps is None:
            raise _err('failed', 'no palette_source - run build_palette_source.py')
        lt = ps.op('library')
        names = [lt[r, 0].val for r in range(1, lt.numRows)]
        if name is not None:
            if name not in names:
                raise _err('bad_field', 'no palette %%r (have: %%s)' %% (name, ', '.join(names)))
            index = names.index(name)
        if index >= len(names):
            raise _err('bad_field', 'palette index %%d out of range (0-%%d)' %% (index, len(names) - 1))
        ps.par.Paletteindex = index

    def background(self, rgb):
        ps = op('/project1/palette_source')
        if ps is None or getattr(ps.par, 'Backgroundoverride', None) is None:
            raise _err('failed', 'palette_source has no background override - rebuild it')
        if rgb is not None:
            for comp, v in zip('rgb', rgb):
                getattr(ps.par, 'Backgroundcolor' + comp).val = v
        ps.par.Backgroundoverride = rgb is not None

    def brand(self, fields):
        bt = op('/project1/brand_table')
        if bt is None:
            raise _err('failed', 'no brand_table - run build_brand_source.py')
        for key, value in fields.items():
            text = ('%%g' %% value) if isinstance(value, float) else value
            if key == 'subtitle' and value == '':
                if bt[key, 0] is not None:
                    bt.deleteRow(key)
                continue
            if bt[key, 0] is not None:
                bt[key, 1] = text
            else:
                bt.appendRow([key, text])

    def output(self, fields):
        o = op('/project1/output')
        names = {'blackout': 'Blackout', 'maxBrightness': 'Maxbrightness',
                 'flashLimit': 'Flashlimit', 'maxFlashes': 'Maxflashes'}
        for key, value in fields.items():
            getattr(o.par, names[key]).val = value

    def engine(self, mode, bpm):
        ein = op('/project1/engine_in')
        ein.op('engine_input_mode').par.index = 1 if mode == 'demo' else 0
        if bpm is not None:
            ein.op('test_bpm').par.const0value = bpm
            ein.op('test_beat_phase').par.frequency = bpm / 60.0
            ein.op('test_hit').par.frequency = bpm / 60.0
            ein.op('test_bar_phase').par.frequency = bpm / 240.0

    def projector(self, action):
        w = op('/project1/projector')
        if w is None:
            raise _err('failed', 'no projector - run build_projector_window.py')
        {'open': w.par.winopen, 'perform': w.par.performance, 'close': w.par.winclose}[action].pulse()

    def ready(self):
        return bool(_g.get('ready', True))

    # ----------------------------------------------------------- looks
    def save_look(self, index, name):
        _look_call(_look_logic().SaveLook, index, name)

    def delete_look(self, index):
        _look_call(_look_logic().DeleteLook, index)

    def rename_look(self, index, name):
        _look_call(_look_logic().RenameLook, index, name)

    def set_bank(self, entries):
        _look_call(_look_logic().SetBank, entries)

    def take(self, index, fade, quantize):
        _look_call(_look_logic().Take, index, fade, quantize)

    def transition(self, fade, quantize):
        _look_call(_look_logic().SetTransition, fade, quantize)

    # ------------------------------------------------- library management
    def _folder(self, mid):
        lib = _lib()
        folder = lib._folder_for(mid)
        if folder is None:
            raise _err('unknown_module', '%%s is not in the library - install it, then rescan' %% mid)
        return lib, folder

    def validate(self, mid):
        lib, folder = self._folder(mid)
        if _g.get('validating') is not None or lib._job.get('gen') is not None or lib._queue:
            raise _err('busy', 'a validation is already running - wait for it to finish')
        _g['validating'] = {'module': mid, 'folder': folder, 'idle': 0}
        _send(_proto().notify({'type': 'validation', 'module': mid, 'phase': 'running'}))
        lib.Validate(folder)

    def report(self, mid):
        lib, folder = self._folder(mid)
        return _trim_report(lib._load_report(folder))

    def approve(self, mid, note):
        lib, folder = self._folder(mid)
        static = op('/project1/scene_library').fetch('static', {}).get(folder) or {}
        rep = lib._load_report(folder)
        if rep is None or rep.get('version') != static.get('version'):
            raise _err('not_validated', '%%s %%s has not been validated - validate it first'
                       %% (mid, static.get('version')))
        if rep.get('result') == 'fail' or static.get('status') == 'fail':
            raise _err('validation_failed', '%%s failed validation and cannot be approved' %% mid)
        if not lib.Approve(folder, note):
            raise _err('failed', 'the scene library refused the approval')

    def revoke(self, mid):
        lib, folder = self._folder(mid)
        lib.Revoke(folder)

    def close_client(self, client):
        try:
            _server().webSocketClose(client)
        except Exception:
            pass


def _float(text, default):
    try:
        return float(text)
    except (TypeError, ValueError):
        return default
'''

SERVER_CALLBACKS = r'''
def onHTTPRequest(dat, request, response):
    return op('runtime').module.OnHTTP(request, response)

def onWebSocketOpen(dat, client, uri):
    op('runtime').module.OnOpen(client)

def onWebSocketClose(dat, client):
    op('runtime').module.OnClose(client)

def onWebSocketReceiveText(dat, client, data):
    op('runtime').module.OnText(client, data)

def onWebSocketReceiveBinary(dat, client, data):
    return

def onWebSocketReceivePing(dat, client, data):
    dat.webSocketSendPong(client, data=data)

def onWebSocketReceivePong(dat, client, data):
    return

def onServerStart(dat):
    print('control_bridge: listening on port', dat.par.port.eval())

def onServerStop(dat):
    print('control_bridge: stopped')
'''

FRAME_EXEC_START = r'''
def onStart():
    # clients hear 'starting' until Startup() has run; let the project finish
    # loading first (TouchDesigner initialises asynchronously)
    op('runtime').module.MarkStarting()
    run("op('runtime').module.Startup()", delayFrames=30)
    return
'''

FRAME_EXEC = r'''
def onFrameStart(frame):
    op('runtime').module.Frame()
    return
'''


def build():
    keep = {'Port': 9980, 'Active': 1}
    old = ROOT.op(NAME)
    if old is not None:
        for k in keep:
            p = getattr(old.par, k, None)
            if p is not None:
                keep[k] = p.eval()
        srv = old.op('server')
        if srv is not None:
            srv.par.active = False
        old.destroy()

    b = ROOT.create(baseCOMP, NAME)
    b.nodeX, b.nodeY = 12800, -1800
    b.nodeWidth, b.nodeHeight = 900, 300

    page = b.appendCustomPage('Bridge')
    p = page.appendInt('Port')[0]
    p.default = 9980
    p.val = keep['Port']
    p = page.appendToggle('Active')[0]
    p.default = 1
    p.val = keep['Active']

    proto = b.create(textDAT, 'protocol')
    proto.nodeX, proto.nodeY = 0, 300
    with open(PROTOCOL_SRC, 'r', encoding='utf-8') as f:
        proto.text = f.read()

    rt = b.create(textDAT, 'runtime')
    rt.nodeX, rt.nodeY = 300, 300
    rt.text = RUNTIME % {'slot_params': json.dumps(SLOT_PARAMS, indent=1), 'token_file': TOKEN_FILE}

    cb = b.create(textDAT, 'server_callbacks')
    cb.nodeX, cb.nodeY = 600, 300
    cb.text = SERVER_CALLBACKS

    srv = b.create(webserverDAT, 'server')
    srv.nodeX, srv.nodeY = 600, 0
    srv.par.callbacks = 'server_callbacks'
    srv.par.port.expr = 'parent().par.Port'
    srv.par.active.expr = 'parent().par.Active'

    fx = b.create(executeDAT, 'frame_exec')
    fx.nodeX, fx.nodeY = 300, 0
    fx.text = FRAME_EXEC + FRAME_EXEC_START
    fx.par.framestart = True
    fx.par.start = True          # onStart: Startup() makes the project relocatable
    fx.par.active = True

    src = b.create(selectTOP, 'preview_src')
    src.nodeX, src.nodeY = 0, -300
    src.par.top = '/project1/OUTPUT'

    prev = b.create(resolutionTOP, 'preview')
    prev.nodeX, prev.nodeY = 300, -300
    prev.inputConnectors[0].connect(src)
    prev.par.outputresolution = 'custom'
    prev.par.resmult = False
    prev.par.resolutionw = 480
    prev.par.resolutionh = 270
    if hasattr(prev.par, 'highqualresize'):
        prev.par.highqualresize = True

    print('control_bridge built at %s' % b.path)
    print('  ws://127.0.0.1:%d/   token file %s' % (b.par.Port.eval(), TOKEN_FILE))
    print('  slot parameters from the frozen contract:',
          ', '.join('%s=%d' % (s, len(d)) for s, d in SLOT_PARAMS.items()))
    print('next: run bridge_client.py demo from a terminal, or tell Claude it is built')
    return b


build()
