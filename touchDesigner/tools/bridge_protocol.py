"""deckglow.control/1 message handling (docs/FRONTEND_MESSAGE_CONTRACT.md).

Pure Python, no TouchDesigner imports: every effect goes through a runtime
adapter object (`rt`), so this file is tested outside TouchDesigner with a
fake adapter and embedded unchanged into /project1/control_bridge by
build_control_bridge.py.

The adapter provides:
    state() -> show state dict           library(rescan) -> {'modules', 'palettes'}
    controls(slot) -> {name: decl}       decl: {'type', 'min', 'max', 'options'}
    slot_enabled(slot, bool)             slot_intensity(slot, v)
    slot_module(slot, id_or_None)        set_control(slot, name, value)
    performer(name, v)                   palette(index=None, name=None)
    background(rgb_or_None)              brand(fields)
    output(fields)                       engine(mode, bpm)
    projector(action)                    close_client(client)
    validate(module_id)                  report(module_id) -> dict or None
    approve(module_id, note)             revoke(module_id)
    save_look(index, name)               delete_look(index)
    rename_look(index, name)             set_bank(entries)
    take(index, fade_or_None, quantize_or_None)
    transition(fade_or_None, quantize_or_None)
Adapter methods raise BridgeError for refusals; anything else is 'failed'.

Runtime-initiated messages (validation progress, libraryChanged) are built
with notify(msg), which returns the (client, msg) pairs for every
authenticated client.
"""

import json
import re

PROTOCOL = 'deckglow.control/1'
SHOW = 'deckglow.show/1'
RUNTIME_API = '2.0.0'
MODULE_CONTRACT = 'deckglow.scene-module/1'
SLOTS = ('base_scene', 'hit_fx', 'brand_overlay', 'finish_fx')
PERFORMER = ('masterIntensity', 'motionAmount', 'flashAmount',
             'textureAmount', 'toneAmount', 'brandAmount')
BRAND_MODES = ('logo', 'name', 'logo_and_name')
CONFIRM_STROBE = 'venue-allows-strobing'     # confirm phrase to switch the flash limit off
LOCAL_PREFIXES = ('127.0.0.1', '::1', '[::1]', 'localhost', '::ffff:127.0.0.1')
MAX_BAD_HELLOS = 3
MAX_MESSAGE = 256 * 1024


class BridgeError(Exception):
    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


def _num(value, lo, hi, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        raise BridgeError('bad_field', '%s must be a number' % what)
    if not lo <= value <= hi:
        raise BridgeError('bad_field', '%s must be between %s and %s' % (what, lo, hi))
    return float(value)


def _bool(value, what):
    if not isinstance(value, bool):
        raise BridgeError('bad_field', '%s must be true or false' % what)
    return value


def _str(value, what, max_len=48):
    if not isinstance(value, str) or len(value) > max_len:
        raise BridgeError('bad_field', '%s must be text of at most %d characters' % (what, max_len))
    return value


def _rgb(value, what='color'):
    if (not isinstance(value, list) or len(value) != 3 or
            not all(isinstance(c, (int, float)) and not isinstance(c, bool) and 0 <= c <= 1 for c in value)):
        raise BridgeError('bad_field', '%s must be [r, g, b] with each in 0..1' % what)
    return [float(c) for c in value]


BANK_SIZE = 16                                # looks in the bank
LOOK_SLOTS = ('base_scene', 'hit_fx')         # what a look holds (with palette, background)
QUANTIZE = ('now', 'beat', 'bar')
MAX_FADE = 30.0                               # seconds
PARAM_NAME_RE = re.compile(r'^[A-Z][a-z0-9]{0,31}$')   # TouchDesigner custom parameter names
MODULE_ID_RE = re.compile(r'^[a-z][a-z0-9]*(\.[a-z0-9][a-z0-9_-]*)+$')   # validate_static ID_RE


def _module_id(msg):
    mid = msg.get('module')
    if not isinstance(mid, str) or len(mid) > 128 or not MODULE_ID_RE.match(mid):
        raise BridgeError('bad_field', 'module must be a module id such as com.example.pack.scene')
    return mid


def _index(msg):
    i = msg.get('index')
    if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < BANK_SIZE:
        raise BridgeError('bad_field', 'index must be a look number 0..%d' % (BANK_SIZE - 1))
    return i


def _fade_quantize(msg):
    fade = None if msg.get('fade') is None else _num(msg['fade'], 0, MAX_FADE, 'fade')
    q = msg.get('quantize')
    if q is not None and q not in QUANTIZE:
        raise BridgeError('bad_field', 'quantize must be one of %s' % ', '.join(QUANTIZE))
    return fade, q


def _look(value, where):
    """A look from a show file: Scene + Hits, palette, background - checked
    field by field, since it reaches the runtime without a setControl."""
    if not isinstance(value, dict) or not isinstance(value.get('slots'), dict):
        raise BridgeError('bad_field', '%s must be {"slots": {...}, "palette", "background"}' % where)
    slots = {}
    for slot, sv in value['slots'].items():
        w = '%s.slots.%s' % (where, slot)
        if slot not in LOOK_SLOTS:
            raise BridgeError('bad_field', '%s: a look holds only %s' % (w, ', '.join(LOOK_SLOTS)))
        if not isinstance(sv, dict):
            raise BridgeError('bad_field', '%s must be an object' % w)
        mid = sv.get('module')
        if mid is not None and (not isinstance(mid, str) or not MODULE_ID_RE.match(mid)):
            raise BridgeError('bad_field', '%s.module must be a module id or null' % w)
        controls = sv.get('controls') or {}
        if not isinstance(controls, dict) or len(controls) > 64:
            raise BridgeError('bad_field', '%s.controls must be an object' % w)
        clean = {}
        for name, cv in controls.items():
            if not isinstance(name, str) or not PARAM_NAME_RE.match(name):
                raise BridgeError('bad_field', '%s.controls: %r is not a parameter name' % (w, name))
            if isinstance(cv, list):
                cv = _rgb(cv, '%s.controls.%s' % (w, name))
            elif isinstance(cv, str):
                cv = _str(cv, '%s.controls.%s' % (w, name), 64)
            elif not isinstance(cv, (bool, int, float)) or cv != cv:
                raise BridgeError('bad_field', '%s.controls.%s has an unsupported value' % (w, name))
            clean[name] = cv
        slots[slot] = {'module': mid,
                       'enabled': _bool(sv.get('enabled', True), w + '.enabled'),
                       'intensity': _num(sv.get('intensity', 1.0), 0, 1, w + '.intensity'),
                       'controls': clean}
    pal = value.get('palette')
    if pal is not None:
        pal = _str(pal, where + '.palette', 128)
    bg = value.get('background')
    return {'slots': slots, 'palette': pal, 'background': None if bg is None else _rgb(bg, where + '.background')}


def _bank(value):
    if not isinstance(value, list) or len(value) > BANK_SIZE:
        raise BridgeError('bad_field', 'looks must be a list of at most %d entries' % BANK_SIZE)
    out = []
    for i, e in enumerate(value):
        if e is None:
            out.append(None)
            continue
        if not isinstance(e, dict):
            raise BridgeError('bad_field', 'looks[%d] must be {"name", "look"} or null' % i)
        out.append({'name': _str(e.get('name') or 'Look %d' % (i + 1), 'looks[%d].name' % i, 32),
                    'look': _look(e.get('look'), 'looks[%d].look' % i)})
    return out


def _slot(msg):
    slot = msg.get('slot')
    if slot not in SLOTS:
        raise BridgeError('bad_field', 'slot must be one of %s' % ', '.join(SLOTS))
    return slot


def check_control(decl, value, name):
    """Validate a control value against its declaration; return the clean value."""
    t = decl.get('type')
    if t in ('float', 'integer'):
        v = _num(value, decl.get('min', float('-inf')), decl.get('max', float('inf')), name)
        if t == 'integer':
            if v != int(v):
                raise BridgeError('bad_field', '%s must be a whole number' % name)
            return int(v)
        return v
    if t == 'toggle':
        return _bool(value, name)
    if t == 'menu':
        if value not in decl.get('options', []):
            raise BridgeError('bad_field', '%s must be one of %s' % (name, ', '.join(decl.get('options', []))))
        return value
    if t == 'color':
        return _rgb(value, name)
    raise BridgeError('unknown_control', '%s has an unsupported type %r' % (name, t))


class Protocol(object):
    def __init__(self, rt, token):
        self.rt = rt
        self.token = token
        self.clients = {}            # client -> {'auth', 'bad', 'status', 'preview'}
        self._notes = []             # broadcasts a handler queues besides state

    # ------------------------------------------------------- connection
    def open(self, client):
        """Return False (and do not register) for a non-local client."""
        if not str(client).startswith(LOCAL_PREFIXES):
            return False
        self.clients[client] = {'auth': False, 'bad': 0, 'status': False, 'preview': None}
        return True

    def close(self, client):
        self.clients.pop(client, None)

    def authenticated(self):
        return [c for c, s in self.clients.items() if s['auth']]

    def subscribers(self, what):
        return [(c, s[what]) for c, s in self.clients.items() if s['auth'] and s[what]]

    def notify(self, msg):
        """A runtime-initiated message for every authenticated client."""
        return [(c, msg) for c in self.authenticated()]

    # ---------------------------------------------------------- receive
    def receive(self, client, text):
        """Handle one text frame. Returns a list of (client, message dict)."""
        sess = self.clients.get(client)
        if sess is None:
            return []
        if len(text) > MAX_MESSAGE:
            return [(client, self._err(None, 'bad_json', 'message too large'))]
        try:
            msg = json.loads(text)
            if not isinstance(msg, dict):
                raise ValueError('not an object')
        except ValueError as e:
            return [(client, self._err(None, 'bad_json', 'not a JSON object: %s' % e))]
        mid = msg.get('id')
        mtype = msg.get('type')

        if not sess['auth']:
            if mtype != 'hello':
                return [(client, self._err(mid, 'unauthenticated', 'send hello with the token first'))]
            if msg.get('token') != self.token or msg.get('protocol', PROTOCOL) != PROTOCOL:
                sess['bad'] += 1
                out = [(client, self._err(mid, 'unauthenticated', 'wrong token or protocol'))]
                if sess['bad'] >= MAX_BAD_HELLOS:
                    self.rt.close_client(client)
                    self.close(client)
                return out
            sess['auth'] = True
            return [(client, {'type': 'welcome', 'id': mid, 'protocol': PROTOCOL,
                              'runtimeApi': RUNTIME_API, 'moduleContract': MODULE_CONTRACT,
                              'state': self.rt.state()})]

        handler = getattr(self, '_on_' + str(mtype), None) if isinstance(mtype, str) else None
        if handler is None or mtype == 'hello':
            return [(client, self._err(mid, 'unknown_type', 'unknown message type %r' % mtype))]
        self._notes = []
        try:
            reply, changed = handler(client, msg)
        except BridgeError as e:
            return [(client, self._err(mid, e.code, e.message))]
        except Exception as e:                          # adapter failure
            return [(client, self._err(mid, 'failed', '%s: %s' % (type(e).__name__, e)))]
        reply = dict(reply or {'type': 'ack'})
        reply['id'] = mid
        out = [(client, reply)]
        if changed:
            state = {'type': 'state', 'state': self.rt.state()}
            out += [(c, state) for c in self.authenticated()]
        for note in self._notes:
            out += self.notify(note)
        self._notes = []
        return out

    @staticmethod
    def _err(mid, code, message):
        return {'type': 'error', 'id': mid, 'code': code, 'error': message}

    # --------------------------------------------------------- handlers
    # each returns (reply dict or None, state_changed)
    def _on_getState(self, client, msg):
        return {'type': 'state', 'state': self.rt.state()}, False

    def _on_getLibrary(self, client, msg):
        rescan = _bool(msg.get('rescan', False), 'rescan')
        lib = self.rt.library(rescan=rescan)
        if rescan:                 # every window should re-read what changed
            self._notes.append({'type': 'libraryChanged', 'module': None})
        return {'type': 'library', 'modules': lib.get('modules', []),
                'palettes': lib.get('palettes', [])}, False

    def _on_setSlotEnabled(self, client, msg):
        self.rt.slot_enabled(_slot(msg), _bool(msg.get('enabled'), 'enabled'))
        return None, True

    def _on_setSlotIntensity(self, client, msg):
        self.rt.slot_intensity(_slot(msg), _num(msg.get('value'), 0, 1, 'value'))
        return None, True

    def _on_setSlotModule(self, client, msg):
        slot = _slot(msg)
        mod = msg.get('module')
        if mod is not None:
            _str(mod, 'module', 128)
        self.rt.slot_module(slot, mod)
        return None, True

    def _on_setControl(self, client, msg):
        slot = _slot(msg)
        name = msg.get('parameter')
        decls = self.rt.controls(slot)
        if not isinstance(name, str) or name not in decls:
            raise BridgeError('unknown_control', '%r is not a control of the module in %s (have: %s)'
                              % (name, slot, ', '.join(sorted(decls)) or 'none'))
        self.rt.set_control(slot, name, check_control(decls[name], msg.get('value'), name))
        return None, True

    def _on_setPerformer(self, client, msg):
        name = msg.get('name')
        if name not in PERFORMER:
            raise BridgeError('bad_field', 'name must be one of %s' % ', '.join(PERFORMER))
        self.rt.performer(name, _num(msg.get('value'), 0, 1, 'value'))
        return None, True

    def _on_setPalette(self, client, msg):
        if 'index' in msg:
            idx = msg['index']
            if isinstance(idx, bool) or not isinstance(idx, int) or idx < 0:
                raise BridgeError('bad_field', 'index must be a whole number >= 0')
            self.rt.palette(index=idx)
        elif 'name' in msg:
            self.rt.palette(name=_str(msg['name'], 'name', 128))
        else:
            raise BridgeError('bad_field', 'give index or name')
        return None, True

    def _on_setBackground(self, client, msg):
        color = msg.get('color')
        self.rt.background(None if color is None else _rgb(color))
        return None, True

    def _on_setBrand(self, client, msg):
        f = {}
        if 'displayName' in msg:
            f['displayName'] = _str(msg['displayName'], 'displayName')
        if 'subtitle' in msg:
            f['subtitle'] = _str(msg['subtitle'], 'subtitle')
        if 'mode' in msg:
            if msg['mode'] not in BRAND_MODES:
                raise BridgeError('bad_field', 'mode must be one of %s' % ', '.join(BRAND_MODES))
            f['mode'] = msg['mode']
        if 'scale' in msg:
            f['scale'] = _num(msg['scale'], 0.1, 5, 'scale')
        if 'opacity' in msg:
            f['opacity'] = _num(msg['opacity'], 0, 1, 'opacity')
        if not f:
            raise BridgeError('bad_field', 'nothing to change')
        self.rt.brand(f)
        return None, True

    def _on_setOutput(self, client, msg):
        f = {}
        if 'blackout' in msg:
            f['blackout'] = _bool(msg['blackout'], 'blackout')
        if 'maxBrightness' in msg:
            f['maxBrightness'] = _num(msg['maxBrightness'], 0, 1, 'maxBrightness')
        if 'maxFlashes' in msg:
            v = _num(msg['maxFlashes'], 1, 10, 'maxFlashes')
            if v != int(v):
                raise BridgeError('bad_field', 'maxFlashes must be a whole number')
            f['maxFlashes'] = int(v)
        if 'flashLimit' in msg:
            on = _bool(msg['flashLimit'], 'flashLimit')
            if not on and msg.get('confirm') != CONFIRM_STROBE:
                raise BridgeError('confirm_required',
                                  'turning the flash limit off needs "confirm": "%s"' % CONFIRM_STROBE)
            f['flashLimit'] = on
        if not f:
            raise BridgeError('bad_field', 'nothing to change')
        self.rt.output(f)
        return None, True

    def _on_setEngine(self, client, msg):
        mode = msg.get('mode')
        if mode not in ('live', 'demo'):
            raise BridgeError('bad_field', 'mode must be live or demo')
        bpm = msg.get('bpm')
        self.rt.engine(mode, None if bpm is None else _num(bpm, 40, 240, 'bpm'))
        return None, True

    def _on_projector(self, client, msg):
        action = msg.get('action')
        if action not in ('open', 'perform', 'close'):
            raise BridgeError('bad_field', 'action must be open, perform or close')
        self.rt.projector(action)
        return None, False

    def _on_subscribe(self, client, msg):
        sess = self.clients[client]
        if 'status' in msg:
            sess['status'] = _bool(msg['status'], 'status')
        if 'preview' in msg:
            p = msg['preview']
            if p is False or p is None:
                sess['preview'] = None
            elif isinstance(p, dict):
                sess['preview'] = {'fps': _num(p.get('fps', 10), 1, 30, 'preview.fps'),
                                   'width': int(_num(p.get('width', 480), 160, 960, 'preview.width'))}
            else:
                raise BridgeError('bad_field', 'preview must be {"fps", "width"} or false')
        return None, False

    # --------------------------------------------------------------- looks
    # A look is Scene + Hits (module, on/off, intensity, controls), palette and
    # background. take loads it into the idle stack and crossfades it in.
    def _on_saveLook(self, client, msg):
        i = _index(msg)
        self.rt.save_look(i, _str(msg.get('name') or 'Look %d' % (i + 1), 'name', 32))
        return None, True

    def _on_deleteLook(self, client, msg):
        self.rt.delete_look(_index(msg))
        return None, True

    def _on_renameLook(self, client, msg):
        i = _index(msg)
        self.rt.rename_look(i, _str(msg.get('name'), 'name', 32))
        return None, True

    def _on_take(self, client, msg):
        i = _index(msg)
        fade, q = _fade_quantize(msg)
        self.rt.take(i, fade, q)
        return None, True

    def _on_setTransition(self, client, msg):
        fade, q = _fade_quantize(msg)
        if fade is None and q is None:
            raise BridgeError('bad_field', 'setTransition needs fade and/or quantize')
        self.rt.transition(fade, q)
        return None, True

    # ------------------------------------------------ library management
    # Validation runs in TouchDesigner's quarantine (about 10 s a module);
    # the runtime broadcasts {"type": "validation"} as it starts and ends.
    def _on_validateModule(self, client, msg):
        self.rt.validate(_module_id(msg))
        return None, False

    def _on_getReport(self, client, msg):
        mid = _module_id(msg)
        return {'type': 'report', 'module': mid, 'report': self.rt.report(mid)}, False

    def _on_approveModule(self, client, msg):
        mid = _module_id(msg)
        note = _str(msg.get('note', ''), 'note', 200)
        self.rt.approve(mid, note)
        self._notes.append({'type': 'libraryChanged', 'module': mid})
        return None, False

    def _on_revokeModule(self, client, msg):
        mid = _module_id(msg)
        self.rt.revoke(mid)
        self._notes.append({'type': 'libraryChanged', 'module': mid})
        return None, False

    def _on_applyShow(self, client, msg):
        show = msg.get('show')
        if not isinstance(show, dict) or show.get('schema') != SHOW:
            raise BridgeError('bad_field', 'show must be a %s object' % SHOW)
        problems = []

        def attempt(label, fn):
            try:
                fn()
            except BridgeError as e:
                problems.append('%s: %s' % (label, e.message))
            except Exception as e:
                problems.append('%s: %s: %s' % (label, type(e).__name__, e))

        known = {'schema', 'slots', 'performer', 'palette', 'background', 'brand', 'output', 'engine',
                 'looks', 'transition', 'take'}       # take: live TAKE status, nothing to apply
        for k in sorted(set(show) - known):
            problems.append('unknown field %r ignored' % k)

        # order: engine, palette, background, brand, performer, slots, output last
        if 'engine' in show:
            e = show['engine'] or {}
            attempt('engine', lambda: self._on_setEngine(client, dict(e)))
        if 'palette' in show:
            p = show['palette'] or {}
            attempt('palette', lambda: self._on_setPalette(
                client, {'index': p['index']} if 'index' in p else {'name': p.get('name')}))
        if 'background' in show:
            attempt('background', lambda: self._on_setBackground(client, {'color': show['background']}))
        if show.get('brand'):
            attempt('brand', lambda: self._on_setBrand(client, dict(show['brand'])))
        if 'looks' in show:
            attempt('looks', lambda: self.rt.set_bank(_bank(show['looks'])))
        if show.get('transition'):
            attempt('transition', lambda: self.rt.transition(*_fade_quantize(dict(show['transition']))))
        for name, v in (show.get('performer') or {}).items():
            attempt('performer.%s' % name, lambda name=name, v=v: self._on_setPerformer(
                client, {'name': name, 'value': v}))
        for slot, s in (show.get('slots') or {}).items():
            if slot not in SLOTS or not isinstance(s, dict):
                problems.append('slots.%s: not a slot' % slot)
                continue
            if 'module' in s:
                attempt('slots.%s.module' % slot, lambda slot=slot, s=s: self._on_setSlotModule(
                    client, {'slot': slot, 'module': s['module']}))
            if 'enabled' in s:
                attempt('slots.%s.enabled' % slot, lambda slot=slot, s=s: self._on_setSlotEnabled(
                    client, {'slot': slot, 'enabled': s['enabled']}))
            if 'intensity' in s:
                attempt('slots.%s.intensity' % slot, lambda slot=slot, s=s: self._on_setSlotIntensity(
                    client, {'slot': slot, 'value': s['intensity']}))
            for pname, pv in (s.get('controls') or {}).items():
                attempt('slots.%s.controls.%s' % (slot, pname),
                        lambda slot=slot, pname=pname, pv=pv: self._on_setControl(
                            client, {'slot': slot, 'parameter': pname, 'value': pv}))
        if show.get('output'):
            o = dict(show['output'])
            if o.get('flashLimit') is False:
                o['confirm'] = CONFIRM_STROBE if msg.get('confirm') == CONFIRM_STROBE else None
            attempt('output', lambda: self._on_setOutput(client, o))
        return {'type': 'ack', 'problems': problems}, True
