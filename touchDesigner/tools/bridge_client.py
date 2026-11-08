"""Reference client for deckglow.control/1 (docs/FRONTEND_MESSAGE_CONTRACT.md).

Standard library only - runs with TouchDesigner's bundled Python or any
Python 3, outside TouchDesigner, while the runtime is running:

    python -I touchDesigner/tools/bridge_client.py state
    python -I touchDesigner/tools/bridge_client.py send '{"type": "setSlotEnabled", "slot": "hit_fx", "enabled": false}'
    python -I touchDesigner/tools/bridge_client.py preview out.jpg
    python -I touchDesigner/tools/bridge_client.py demo

`demo` walks through the switches the desktop app will offer, checks each
change appears in the broadcast state, saves a preview JPEG, and restores the
show it started from. The token is read from touchDesigner/bridge_token.txt.
"""

import base64
import hashlib
import json
import os
import socket
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.normpath(os.path.join(HERE, '..', 'bridge_token.txt'))
GUID = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


class Client(object):
    """A minimal RFC 6455 WebSocket client."""

    def __init__(self, host='127.0.0.1', port=9980, timeout=5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16))
        self.sock.sendall(b'GET / HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n'
                          b'Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n'
                          b'Sec-WebSocket-Version: 13\r\n\r\n' % (host.encode(), port, key))
        head = b''
        while b'\r\n\r\n' not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError('server closed during handshake')
            head += chunk
        head, self.buf = head.split(b'\r\n\r\n', 1)
        lines = head.decode('latin-1').split('\r\n')
        if ' 101 ' not in lines[0] + ' ':
            raise ConnectionError('handshake refused: %s' % lines[0])
        want = base64.b64encode(hashlib.sha1(key + GUID).digest()).decode()
        got = [l.split(':', 1)[1].strip() for l in lines if l.lower().startswith('sec-websocket-accept:')]
        if got != [want]:
            raise ConnectionError('bad Sec-WebSocket-Accept')
        self.next_id = 0

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError('connection closed')
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send_frame(self, opcode, payload):
        mask = os.urandom(4)
        n = len(payload)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack('>H', n)
        else:
            head += bytes([0x80 | 127]) + struct.pack('>Q', n)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def recv(self):
        """Next message: ('text', dict) or ('binary', bytes)."""
        message, kind = b'', None
        while True:
            b1, b2 = self._read(2)
            fin, opcode, n = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack('>H', self._read(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x9:                      # ping
                self._send_frame(0xA, data)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x8:
                raise ConnectionError('server closed the connection')
            if opcode in (0x1, 0x2):
                kind = 'text' if opcode == 0x1 else 'binary'
            message += data
            if fin:
                return ('text', json.loads(message.decode('utf-8'))) if kind == 'text' else ('binary', message)

    def send(self, msg):
        self.next_id += 1
        msg = dict(msg, id=msg.get('id', self.next_id))
        self._send_frame(0x1, json.dumps(msg).encode('utf-8'))
        return msg['id']

    def request(self, msg, timeout=10.0):
        """Send and wait for the reply with the same id. Returns (reply, other messages)."""
        mid = self.send(msg)
        others, end = [], time.time() + timeout
        while time.time() < end:
            kind, m = self.recv()
            if kind == 'text' and m.get('id') == mid:          # broadcasts carry no id
                return m, others
            others.append((kind, m))
        raise TimeoutError('no reply to %s' % msg.get('type'))

    def close(self):
        try:
            self._send_frame(0x8, b'')
        finally:
            self.sock.close()


def connect(port=9980):
    with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
        token = f.read().strip()
    c = Client(port=port)
    reply, _ = c.request({'type': 'hello', 'token': token, 'client': 'bridge_client.py',
                          'protocol': 'deckglow.control/1'})
    if reply.get('type') != 'welcome':
        raise RuntimeError('hello refused: %s' % reply)
    return c, reply


def demo(c, start_state):
    """Exercise the app's switches; every step must ack and show in state."""
    results = []

    def step(label, msg, check=None):
        reply, others = c.request(msg)
        state = next((m['state'] for k, m in reversed(others) if k == 'text' and m.get('type') == 'state'), None)
        if state is None and reply.get('type') == 'ack':
            state = c.request({'type': 'getState'})[0]['state']
        ok = reply.get('type') == 'ack' and (check is None or (state is not None and check(state)))
        results.append(ok)
        print('  %-4s %-38s %s' % ('ok' if ok else 'FAIL', label,
                                   '' if ok else json.dumps(reply)[:150]))
        return state

    slots = start_state.get('slots', {})
    print('slots:', ', '.join('%s=%s(%s)' % (s, v.get('module'), 'on' if v.get('enabled') else 'off')
                              for s, v in slots.items()))
    step('orbs off', {'type': 'setSlotEnabled', 'slot': 'hit_fx', 'enabled': False},
         lambda s: s['slots']['hit_fx']['enabled'] is False)
    step('stripes off', {'type': 'setSlotEnabled', 'slot': 'base_scene', 'enabled': False},
         lambda s: s['slots']['base_scene']['enabled'] is False)
    step('background deep purple', {'type': 'setBackground', 'color': [0.25, 0.0, 0.35]},
         lambda s: s['background'] == [0.25, 0.0, 0.35])
    time.sleep(0.3)
    preview(c, os.path.join(HERE, '..', 'bridge_preview_background.jpg'))
    step('stripes on', {'type': 'setSlotEnabled', 'slot': 'base_scene', 'enabled': True},
         lambda s: s['slots']['base_scene']['enabled'] is True)
    step('orbs on', {'type': 'setSlotEnabled', 'slot': 'hit_fx', 'enabled': True},
         lambda s: s['slots']['hit_fx']['enabled'] is True)
    step('background back to palette', {'type': 'setBackground', 'color': None},
         lambda s: s['background'] is None)
    step('palette ember', {'type': 'setPalette', 'name': 'ember'},
         lambda s: s['palette']['name'] == 'ember')
    step('name -> DEMO', {'type': 'setBrand', 'displayName': 'DEMO'},
         lambda s: s['brand']['displayName'] == 'DEMO')
    step('master 0.5', {'type': 'setPerformer', 'name': 'masterIntensity', 'value': 0.5},
         lambda s: s['performer']['masterIntensity'] == 0.5)
    step('max brightness 0.8', {'type': 'setOutput', 'maxBrightness': 0.8},
         lambda s: s['output']['maxBrightness'] == 0.8)
    step('demo mode 128 BPM', {'type': 'setEngine', 'mode': 'demo', 'bpm': 128},
         lambda s: s['engine'] == {'mode': 'demo', 'bpm': 128.0})
    if slots.get('hit_fx', {}).get('module') == 'com.deckglow.orb_burst':
        step('orbs: 8 per hit', {'type': 'setControl', 'slot': 'hit_fx', 'parameter': 'Spawncount', 'value': 8},
             lambda s: s['slots']['hit_fx']['controls'].get('Spawncount') == 8)
        step('orbs: add blend', {'type': 'setControl', 'slot': 'hit_fx', 'parameter': 'Blendmode', 'value': 'add'},
             lambda s: s['slots']['hit_fx']['controls'].get('Blendmode') == 'add')
    time.sleep(0.5)
    preview(c, os.path.join(HERE, '..', 'bridge_preview_full.jpg'))
    # refusals the app relies on
    for label, msg, code in (
            ('refuse unapproved module', {'type': 'setSlotModule', 'slot': 'base_scene', 'module': 'com.deckglow.stub'}, 'not_approved'),
            ('refuse wrong slot', {'type': 'setSlotModule', 'slot': 'hit_fx', 'module': 'com.deckglow.kinetic_stripes'}, 'wrong_slot'),
            ('refuse strobe without confirm', {'type': 'setOutput', 'flashLimit': False}, 'confirm_required')):
        reply, _ = c.request(msg)
        ok = reply.get('type') == 'error' and reply.get('code') == code
        results.append(ok)
        print('  %-4s %-38s %s' % ('ok' if ok else 'FAIL', label, '' if ok else json.dumps(reply)[:150]))
    # status
    c.request({'type': 'subscribe', 'status': True})
    status, end = None, time.time() + 3
    while status is None and time.time() < end:
        kind, m = c.recv()
        if kind == 'text' and m.get('type') == 'status':
            status = m['status']
    c.request({'type': 'subscribe', 'status': False})
    ok = bool(status and status.get('lanes') and status.get('slots'))
    results.append(ok)
    print('  %-4s %-38s %s' % ('ok' if ok else 'FAIL', 'status stream',
                               'fps %s, %d lanes, limiter %s' % (status.get('fps'), len(status.get('lanes', {})),
                                                                 status.get('limiter')) if status else 'none'))
    # restore
    reply, _ = c.request({'type': 'applyShow', 'show': start_state})
    ok = reply.get('type') == 'ack' and not reply.get('problems')
    results.append(ok)
    print('  %-4s %-38s %s' % ('ok' if ok else 'FAIL', 'restore the starting show',
                               '' if ok else json.dumps(reply.get('problems') or reply)[:200]))
    print('%d of %d steps passed' % (sum(results), len(results)))
    return all(results)


def preview(c, path, width=480):
    c.request({'type': 'subscribe', 'preview': {'fps': 5, 'width': width}})
    data, end = None, time.time() + 5
    while data is None and time.time() < end:
        kind, m = c.recv()
        if kind == 'binary':
            data = m
    c.request({'type': 'subscribe', 'preview': False})
    if data:
        with open(path, 'wb') as f:
            f.write(data)
        print('  preview %s (%d bytes)' % (os.path.normpath(path), len(data)))
    else:
        print('  FAIL no preview frame')
    return data


def main(argv):
    cmd = argv[1] if len(argv) > 1 else 'state'
    c, welcome = connect()
    try:
        if cmd == 'state':
            print(json.dumps(welcome['state'], indent=2))
        elif cmd == 'send':
            reply, others = c.request(json.loads(argv[2]))
            print(json.dumps(reply, indent=2))
        elif cmd == 'preview':
            preview(c, argv[2] if len(argv) > 2 else 'preview.jpg')
        elif cmd == 'demo':
            return 0 if demo(c, welcome['state']) else 1
        else:
            print(__doc__)
            return 2
    finally:
        c.close()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
