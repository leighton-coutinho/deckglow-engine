"""A stand-in control bridge for developing the desktop app without TouchDesigner.

Runs outside TouchDesigner, standard library only:

    python -I touchDesigner/tools/mock_bridge.py            # ws://127.0.0.1:9980/
    python -I touchDesigner/tools/mock_bridge.py --port 9981

It speaks deckglow.control/1 (docs/FRONTEND_MESSAGE_CONTRACT.md) using the
*real* protocol code, bridge_protocol.py - the same module the TouchDesigner
bridge embeds - so authentication, validation, error codes, broadcasts and
applyShow ordering are exactly the runtime's. Only the adapter is fake: it
keeps the show state in memory, reads the library from modules/ manifests
and library/approved.json (approval per id and version, as the scene
library does), and declares controls from the frozen contract plus each
manifest, as build_control_bridge.py does.

Preview frames are PNGs (browsers decode them like the JPEGs TouchDesigner
sends): the base module's thumbnail while the base slot is on and filled,
otherwise a flat frame of the background colour - so the background switch
is visible in the app. Status carries synthetic lanes moving at the show BPM.

The token is read from touchDesigner/bridge_token.txt, created if missing,
exactly like the real bridge. Do not run it while TouchDesigner's bridge is
on the same port.
"""

import base64
import hashlib
import json
import math
import os
import secrets
import socket
import socketserver
import struct
import sys
import threading
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
TD = os.path.normpath(os.path.join(HERE, '..'))
ROOT = os.path.normpath(os.path.join(TD, '..'))
sys.path.insert(0, HERE)
import bridge_protocol as bp  # noqa: E402

TOKEN_FILE = os.path.join(TD, 'bridge_token.txt')
CONTRACT = os.path.join(ROOT, 'docs', 'contract', 'deckglow.scene-module-1.json')
GUID = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
PALETTES = [  # build_palette_source.py's default library
    ('deckglow', (0.02, 0.02, 0.03), (1.00, 0.82, 0.10)),
    ('ember', (0.03, 0.01, 0.01), (1.00, 0.35, 0.05)),
    ('ice', (0.01, 0.02, 0.04), (0.30, 0.80, 1.00)),
    ('mono', (0.02, 0.02, 0.02), (0.90, 0.90, 0.90)),
]
SLOT_DEFAULTS = {'base_scene': 'com.deckglow.kinetic_stripes', 'hit_fx': 'com.deckglow.orb_burst',
                 'brand_overlay': 'com.deckglow.clean_lockup', 'finish_fx': 'com.deckglow.projector_safe'}
LANES = ('body_level', 'body_drift', 'impact_fast', 'impact_wide', 'impact_trigger', 'sync_level',
         'sync_phase', 'sync_sine', 'sync_triangle', 'sync_bar_env', 'texture_level',
         'texture_jitter', 'mood_warmth', 'mood_softness', 'brand_pulse', 'blackout_gate')


def png(width, height, rgb):
    """A flat-colour PNG, standard library only."""
    px = bytes(int(max(0.0, min(1.0, c)) * 255 + 0.5) for c in rgb)
    raw = b''.join(b'\x00' + px * width for _ in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def slot_params():
    """Slot parameters a frontend may set, from the frozen contract (as the real bridge)."""
    with open(CONTRACT, 'r', encoding='utf-8') as f:
        contract = json.load(f)
    out = {}
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
                lo, hi = p.get('range', [0, 1 << 30])
                decls[p['name']] = {'type': 'integer', 'min': lo, 'max': hi}
        out[slot] = decls
    return out


class FakeRuntime(object):
    """The adapter interface of build_control_bridge.py, in memory."""

    def __init__(self, server):
        self.server = server
        self.slot_params = slot_params()
        self.modules = self._scan()
        self.palette_index = 0
        self.bg = None
        self.slots = {}
        for slot, mid in SLOT_DEFAULTS.items():
            ok = mid in self.modules and self.modules[mid]['approved'] == 'yes'
            self.slots[slot] = {'module': mid if ok else None, 'enabled': True, 'intensity': 1.0, 'controls': {}}
        self.perf = dict((n, 1.0) for n in bp.PERFORMER)
        self.brand_rows = {'displayName': 'KOUTINHO', 'mode': 'name', 'subtitle': '', 'scale': 1.0, 'opacity': 1.0}
        self.out = {'blackout': False, 'maxBrightness': 1.0, 'flashLimit': True, 'maxFlashes': 3}
        self.eng = {'mode': 'live', 'bpm': 120.0}
        self.projector_state = 'closed'

    # ------------------------------------------------------------ library
    def _scan(self):
        approved = {}
        try:
            with open(os.path.join(TD, 'library', 'approved.json'), 'r', encoding='utf-8') as f:
                approved = json.load(f).get('approved', {})
        except (OSError, ValueError):
            pass
        mods = {}
        roots = [(os.path.join(TD, 'modules'), 'com.deckglow')]
        packs = os.path.join(TD, 'Packs')
        if os.path.isdir(packs):
            roots += [(os.path.join(packs, p), p) for p in sorted(os.listdir(packs))]
        for base, source in roots:
            if not os.path.isdir(base):
                continue
            for folder in sorted(os.listdir(base)):
                path = os.path.join(base, folder, 'module.json')
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        man = json.load(f)
                except (OSError, ValueError):
                    continue
                a = approved.get(man.get('id'), {})
                ok = a.get('version') == man.get('version') and a.get('result') == 'pass'
                mods[man['id']] = {
                    'id': man['id'], 'type': man.get('type'), 'version': man.get('version'),
                    'displayName': man.get('displayName', folder), 'source': source,
                    'static': 'pass', 'quarantine': a.get('result', 'not run') if a else 'not run',
                    'approved': 'yes' if ok else ('stale' if a else 'no'),
                    'thumbnail': os.path.join(base, folder, man.get('thumbnail', 'thumbnail.png')).replace('\\', '/'),
                    'controls': man.get('controls', [])}
        return mods

    def library(self, rescan=False):
        if rescan:
            time.sleep(0.5)                       # the real rescan takes seconds
            self.modules = self._scan()
        return {'modules': list(self.modules.values()), 'palettes': [p[0] for p in PALETTES]}

    def controls(self, slot):
        decls = dict(self.slot_params.get(slot, {}))
        mid = self.slots[slot]['module']
        for c in (self.modules.get(mid, {}).get('controls', []) if mid else []):
            decls[c.get('parameter')] = {'type': c.get('type'), 'min': c.get('min'),
                                         'max': c.get('max'), 'options': c.get('options', [])}
        return decls

    # --------------------------------------------------------------- reads
    def state(self):
        name = PALETTES[self.palette_index][0]
        return {'schema': bp.SHOW,
                'slots': json.loads(json.dumps(self.slots)),
                'performer': dict(self.perf),
                'palette': {'index': self.palette_index, 'name': name},
                'background': list(self.bg) if self.bg else None,
                'brand': dict(self.brand_rows), 'output': dict(self.out), 'engine': dict(self.eng)}

    def background_rgb(self):
        return self.bg or PALETTES[self.palette_index][1]

    # -------------------------------------------------------------- writes
    def slot_enabled(self, slot, on):
        self.slots[slot]['enabled'] = on

    def slot_intensity(self, slot, v):
        self.slots[slot]['intensity'] = round(v, 4)

    def slot_module(self, slot, mid):
        self.slots[slot]['controls'] = {}
        if mid is None:
            self.slots[slot]['module'] = None
            return
        m = self.modules.get(mid)
        if m is None:
            raise bp.BridgeError('not_approved', '%s is not in the library' % mid)
        if m['type'] != slot:
            raise bp.BridgeError('wrong_slot', '%s is a %s, not a %s' % (mid, m['type'], slot))
        if m['approved'] != 'yes':
            raise bp.BridgeError('not_approved', '%s is not approved for its current version' % mid)
        time.sleep(0.15)                          # loading takes a few frames
        self.slots[slot]['module'] = mid

    def set_control(self, slot, name, value):
        if self.slots[slot]['module'] is None:
            raise bp.BridgeError('not_loaded', 'no module is loaded in %s' % slot)
        self.slots[slot]['controls'][name] = value

    def performer(self, name, v):
        self.perf[name] = round(v, 4)

    def palette(self, index=None, name=None):
        names = [p[0] for p in PALETTES]
        if name is not None:
            if name not in names:
                raise bp.BridgeError('bad_field', 'no palette %r (have: %s)' % (name, ', '.join(names)))
            index = names.index(name)
        if index >= len(names):
            raise bp.BridgeError('bad_field', 'palette index %d out of range (0-%d)' % (index, len(names) - 1))
        self.palette_index = index

    def background(self, rgb):
        self.bg = None if rgb is None else [round(c, 4) for c in rgb]

    def brand(self, fields):
        self.brand_rows.update(fields)

    def output(self, fields):
        self.out.update(fields)

    def engine(self, mode, bpm):
        self.eng['mode'] = mode
        if bpm is not None:
            self.eng['bpm'] = round(float(bpm), 2)

    def projector(self, action):
        self.projector_state = 'closed' if action == 'close' else action

    def close_client(self, client):
        self.server.drop(client)

    # -------------------------------------------------------------- status
    def status(self, fps):
        t = time.time()
        beat = (t * self.eng['bpm'] / 60.0) % 1.0
        bar = (t * self.eng['bpm'] / 240.0) % 1.0
        m = self.perf['masterIntensity']
        lanes = dict((n, 0.0) for n in LANES)
        lanes.update({
            'body_level': 0.65 * m, 'body_drift': 0.5 * self.perf['motionAmount'] * m,
            'impact_fast': max(0.0, 1 - beat * 4) * self.perf['flashAmount'] * m,
            'impact_wide': max(0.0, 1 - beat * 2) * m, 'impact_trigger': 1.0 if beat < 0.05 else 0.0,
            'sync_level': max(0.0, 1 - beat * 3) * m, 'sync_phase': beat,
            'sync_sine': math.sin(beat * 2 * math.pi), 'sync_triangle': 1 - abs(beat * 2 - 1),
            'sync_bar_env': max(0.0, 1 - bar * 4) * m, 'texture_level': 0.45 * self.perf['textureAmount'] * m,
            'texture_jitter': 0.5 + 0.3 * math.sin(t * 1.7), 'mood_warmth': 0.5, 'mood_softness': 0.5,
            'brand_pulse': 0.25 * max(0.0, 1 - beat * 2) * self.perf['brandAmount'] * m,
            'blackout_gate': 0.0 if self.out['blackout'] else 1.0})
        slots = {}
        for slot, s in self.slots.items():
            slots[slot] = {'status': ('ok: 1280x720' if s['enabled'] else 'bypassed') if s['module'] else 'empty',
                           'cookMs': 0.3 if s['module'] else 0.0}
        return {'fps': round(fps, 1), 'slots': slots, 'lanes': dict((k, round(v, 4)) for k, v in lanes.items()),
                'limiter': {'held': 0.0, 'transitions': 1.0, 'gain': 1.0}}

    def preview(self, width):
        height = int(round(width * 9 / 16.0))
        base = self.slots['base_scene']
        if base['enabled'] and base['module'] and not self.out['blackout']:
            thumb = self.modules.get(base['module'], {}).get('thumbnail')
            try:
                with open(thumb, 'rb') as f:
                    return f.read()
            except (OSError, TypeError):
                pass
        rgb = (0, 0, 0) if self.out['blackout'] else self.background_rgb()
        return png(width, height, [c * self.out['maxBrightness'] for c in rgb])


# ------------------------------------------------------------------ server
class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port):
        socketserver.ThreadingTCPServer.__init__(self, ('127.0.0.1', port), Handler)
        if not os.path.isfile(TOKEN_FILE):
            with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
                f.write(secrets.token_urlsafe(24))
        with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
            token = f.read().strip()
        self.lock = threading.RLock()
        self.conns = {}                           # client id -> Handler
        self.rt = FakeRuntime(self)
        self.proto = bp.Protocol(self.rt, token)
        self.next_preview = {}
        threading.Thread(target=self._ticker, daemon=True).start()

    def send(self, pairs):
        for client, msg in pairs:
            h = self.conns.get(client)
            if h is not None:
                h.send_text(json.dumps(msg))

    def drop(self, client):
        h = self.conns.pop(client, None)
        if h is not None:
            h.close_socket()

    def _ticker(self):
        last, frame = time.time(), 0
        while True:
            time.sleep(1 / 60.0)
            frame += 1
            now = time.time()
            fps = 1.0 / max(1e-6, now - last)
            last = now
            with self.lock:
                if frame % 15 == 0:
                    subs = [c for c, on in self.proto.subscribers('status') if on]
                    if subs:
                        msg = {'type': 'status', 'status': self.rt.status(min(60.0, fps))}
                        self.send([(c, msg) for c in subs])
                for c, v in self.proto.subscribers('preview'):
                    if now >= self.next_preview.get(c, 0):
                        self.next_preview[c] = now + 1.0 / v['fps']
                        h = self.conns.get(c)
                        if h is not None:
                            h.send_binary(self.rt.preview(v['width']))


class Handler(socketserver.BaseRequestHandler):
    def setup(self):
        self.sock = self.request
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.wlock = threading.Lock()
        host, port = self.client_address[:2]
        self.client = '%s:%d' % (host, port)
        self.buf = b''
        self.alive = True

    # -------------------------------------------------------------- frames
    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError('closed')
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _frame(self, opcode, payload):
        n = len(payload)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([n])
        elif n < 65536:
            head += bytes([126]) + struct.pack('>H', n)
        else:
            head += bytes([127]) + struct.pack('>Q', n)
        with self.wlock:
            if self.alive:
                try:
                    self.sock.sendall(head + payload)
                except OSError:
                    self.alive = False

    def send_text(self, text):
        self._frame(0x1, text.encode('utf-8'))

    def send_binary(self, data):
        self._frame(0x2, data)

    def close_socket(self):
        self._frame(0x8, struct.pack('>H', 1008))
        self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    # ------------------------------------------------------------ session
    def handle(self):
        head = b''
        try:
            while b'\r\n\r\n' not in head:
                chunk = self.sock.recv(4096)
                if not chunk:
                    return
                head += chunk
                if len(head) > 16384:
                    return
        except OSError:
            return
        head, self.buf = head.split(b'\r\n\r\n', 1)
        lines = head.decode('latin-1').split('\r\n')
        path = lines[0].split(' ')[1] if len(lines[0].split(' ')) > 1 else '/'
        headers = dict((l.split(':', 1)[0].strip().lower(), l.split(':', 1)[1].strip())
                       for l in lines[1:] if ':' in l)
        if headers.get('upgrade', '').lower() != 'websocket':
            body = b'deckglow' if path == '/health' else b'not found'
            code = '200 OK' if path == '/health' else '404 Not Found'
            self.sock.sendall(('HTTP/1.1 %s\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n'
                               'Connection: close\r\n\r\n' % (code, len(body))).encode() + body)
            return
        accept = base64.b64encode(hashlib.sha1(headers.get('sec-websocket-key', '').encode() + GUID).digest())
        self.sock.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                          b'Connection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
        srv = self.server
        with srv.lock:
            if not srv.proto.open(self.client):
                self.close_socket()
                return
            srv.conns[self.client] = self
        print('mock_bridge: %s connected' % self.client)
        try:
            message, kind = b'', None
            while self.alive:
                b1, b2 = self._read(2)
                fin, opcode, n = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
                if n == 126:
                    n = struct.unpack('>H', self._read(2))[0]
                elif n == 127:
                    n = struct.unpack('>Q', self._read(8))[0]
                if n > bp.MAX_MESSAGE * 4:
                    break
                mask = self._read(4) if b2 & 0x80 else b'\x00\x00\x00\x00'
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(self._read(n)))
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._frame(0xA, data)
                    continue
                if opcode == 0xA:
                    continue
                if opcode in (0x1, 0x2):
                    kind, message = opcode, b''
                message += data
                if not fin:
                    continue
                if kind == 0x1:
                    with srv.lock:
                        out = srv.proto.receive(self.client, message.decode('utf-8', 'replace'))
                        srv.send(out)
                message, kind = b'', None
        except (ConnectionError, OSError):
            pass
        finally:
            with srv.lock:
                srv.proto.close(self.client)
                srv.conns.pop(self.client, None)
                srv.next_preview.pop(self.client, None)
            print('mock_bridge: %s disconnected' % self.client)


def main(argv):
    port = 9980
    if '--port' in argv:
        port = int(argv[argv.index('--port') + 1])
    # Windows lets this bind 127.0.0.1:<port> even while TouchDesigner's bridge holds
    # 0.0.0.0:<port>; loopback clients then reach whichever is more specific, silently
    # testing the mock instead of the runtime. So refuse when anything already answers.
    try:
        socket.create_connection(('127.0.0.1', port), timeout=0.5).close()
        print('mock_bridge: something already listens on port %d - is the TouchDesigner bridge running? '
              'Use --port for another one.' % port)
        return 1
    except OSError:
        pass
    try:
        srv = Server(port)
    except OSError as e:
        print('mock_bridge: cannot use port %d (%s); use --port for another one.' % (port, e.strerror or e))
        return 1
    print('mock_bridge: ws://127.0.0.1:%d/  (token from %s)' % (port, TOKEN_FILE))
    print('mock_bridge: %d modules, %d approved' % (
        len(srv.rt.modules), sum(1 for m in srv.rt.modules.values() if m['approved'] == 'yes')))
    sys.stdout.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
