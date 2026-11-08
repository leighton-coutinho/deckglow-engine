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
TOKEN_FILE = %(token_file)r
STATUS_EVERY = 15                     # frames (4 per second at 60 fps)

_g = {'proto': None, 'frame': 0, 'last_t': None, 'fps': 0.0, 'manifests': {}, 'next_preview': {}}


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


def Status():
    out = {'fps': round(_g['fps'], 1), 'slots': {}, 'limiter': {}, 'lanes': {}}
    for slot, name in SLOT_HOST.items():
        h = op('/project1/' + name)
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


def _host(slot):
    h = op('/project1/' + SLOT_HOST[slot])
    if h is None:
        raise _err('failed', 'no %%s - run build_module_host.py' %% SLOT_HOST[slot])
    return h


def _lib():
    d = op('/project1/scene_library/library')
    if d is None:
        raise _err('failed', 'no scene library - run build_scene_library.py')
    return d.module


def _manifest_at(tox_path):
    """The module.json next to a loaded .tox (cached by path)."""
    if not tox_path:
        return None
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
            h = op('/project1/' + SLOT_HOST[slot])
            if h is None:
                continue
            loaded = h.op('module') is not None
            man = _manifest_at(h.par.Modulepath.eval()) if loaded else None
            slots[slot] = {'module': man.get('id') if man else None,
                           'enabled': bool(h.par.Moduleactive.eval()),
                           'intensity': round(float(h.par.Intensity.eval()), 4),
                           'controls': dict(_desired().get(slot, {}))}
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
        return {'schema': P.SHOW, 'slots': slots, 'performer': perf, 'palette': palette,
                'background': background, 'brand': brand, 'output': output, 'engine': engine}

    def library(self, rescan=False):
        lib = _lib()
        t = op('/project1/scene_library/LIBRARY')
        if rescan or t.numRows <= 1:
            lib.Scan(quiet=True)        # slow: toeexpand on every module
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
        h = op('/project1/' + SLOT_HOST[slot])
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
        _desired()[slot] = {}
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
        if not lib.LoadApproved(SLOT_HOST[slot], mid):
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
        _desired()[slot][name] = value

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
    fx.text = FRAME_EXEC
    fx.par.framestart = True
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
