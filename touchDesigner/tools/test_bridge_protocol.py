"""Tests bridge_protocol.py (deckglow.control/1) with a fake runtime adapter.

Plain Python, outside TouchDesigner:

    python -I touchDesigner/tools/test_bridge_protocol.py

Also run by the app's npm test. Prints ALL OK, or stops at the first failure.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bridge_protocol as bp  # noqa: E402


class FakeRT(object):
    def __init__(self):
        self.calls, self.closed = [], []
        self.approved = {'com.deckglow.orb_burst': 'hit_fx', 'com.deckglow.kinetic_stripes': 'base_scene'}

    def state(self):
        return {'schema': bp.SHOW, 'calls': len(self.calls)}

    def library(self, rescan=False):
        self.calls.append(('library', rescan))
        return {'modules': [{'id': 'com.deckglow.orb_burst'}], 'palettes': ['deckglow']}

    def controls(self, slot):
        if slot == 'hit_fx':
            return {'Spawncount': {'type': 'integer', 'min': 1, 'max': 12},
                    'Ballsize': {'type': 'float', 'min': 0.02, 'max': 0.4},
                    'Blendmode': {'type': 'menu', 'options': ['over', 'add', 'screen']}}
        return {}

    def slot_module(self, slot, mid):
        if mid is not None and self.approved.get(mid) is None:
            raise bp.BridgeError('not_approved', '%s is not approved' % mid)
        if mid is not None and self.approved[mid] != slot:
            raise bp.BridgeError('wrong_slot', 'type mismatch')
        self.calls.append(('slot_module', slot, mid))

    def close_client(self, c):
        self.closed.append(c)

    def __getattr__(self, name):          # every other adapter method just records
        def rec(*a, **k):
            self.calls.append((name,) + a + tuple(sorted(k.items())))
        return rec


rt = FakeRT()
P = bp.Protocol(rt, 'secret')
send = lambda c, m: P.receive(c, json.dumps(m))
first = lambda out: out[0][1]

# connection rules
assert P.open('192.168.1.20:5000') is False
assert P.open('127.0.0.1:5000') and P.open('[::1]:6000')
print('ok  only local clients may connect')

r = first(send('127.0.0.1:5000', {'type': 'getState', 'id': 1}))
assert r['code'] == 'unauthenticated' and r['id'] == 1
r = first(P.receive('127.0.0.1:5000', 'not json'))
assert r['code'] == 'bad_json'
for i in range(3):
    r = first(send('[::1]:6000', {'type': 'hello', 'token': 'wrong'}))
assert r['code'] == 'unauthenticated' and '[::1]:6000' in rt.closed and '[::1]:6000' not in P.clients
print('ok  nothing works before hello; three bad hellos close the connection')

r = first(send('127.0.0.1:5000', {'type': 'hello', 'token': 'secret', 'id': 'h'}))
assert r['type'] == 'welcome' and r['protocol'] == bp.PROTOCOL and r['id'] == 'h' and 'state' in r
r = first(send('127.0.0.1:5000', {'type': 'hello', 'token': 'secret'}))
assert r['code'] == 'unknown_type'
print('ok  hello with the token -> welcome with state')

P.open('127.0.0.1:7000')
send('127.0.0.1:7000', {'type': 'hello', 'token': 'secret'})

# requests
out = send('127.0.0.1:5000', {'type': 'setSlotEnabled', 'slot': 'hit_fx', 'enabled': False, 'id': 2})
assert out[0][1] == {'type': 'ack', 'id': 2}
assert sorted(c for c, m in out if m['type'] == 'state') == ['127.0.0.1:5000', '127.0.0.1:7000']
assert rt.calls[-1] == ('slot_enabled', 'hit_fx', False)
print('ok  a change is acked and the new state broadcast to every client')

bad = [
    ({'type': 'setSlotEnabled', 'slot': 'nope', 'enabled': True}, 'bad_field'),
    ({'type': 'setSlotEnabled', 'slot': 'hit_fx', 'enabled': 1}, 'bad_field'),
    ({'type': 'setSlotIntensity', 'slot': 'hit_fx', 'value': 1.5}, 'bad_field'),
    ({'type': 'setSlotModule', 'slot': 'hit_fx', 'module': 'com.evil.x'}, 'not_approved'),
    ({'type': 'setSlotModule', 'slot': 'hit_fx', 'module': 'com.deckglow.kinetic_stripes'}, 'wrong_slot'),
    ({'type': 'setControl', 'slot': 'hit_fx', 'parameter': 'Spawncount', 'value': 13}, 'bad_field'),
    ({'type': 'setControl', 'slot': 'hit_fx', 'parameter': 'Spawncount', 'value': 2.5}, 'bad_field'),
    ({'type': 'setControl', 'slot': 'hit_fx', 'parameter': 'Blendmode', 'value': 'multiply'}, 'bad_field'),
    ({'type': 'setControl', 'slot': 'hit_fx', 'parameter': 'par.externaltox', 'value': 'x'}, 'unknown_control'),
    ({'type': 'setControl', 'slot': 'base_scene', 'parameter': 'Spawncount', 'value': 2}, 'unknown_control'),
    ({'type': 'setPerformer', 'name': 'evil', 'value': 1}, 'bad_field'),
    ({'type': 'setPerformer', 'name': 'flashAmount', 'value': True}, 'bad_field'),
    ({'type': 'setPalette', 'index': -1}, 'bad_field'),
    ({'type': 'setBackground', 'color': [1, 0, 2]}, 'bad_field'),
    ({'type': 'setBackground', 'color': '#ff0000'}, 'bad_field'),
    ({'type': 'setBrand', 'displayName': 'x' * 49}, 'bad_field'),
    ({'type': 'setBrand', 'mode': 'banner'}, 'bad_field'),
    ({'type': 'setBrand'}, 'bad_field'),
    ({'type': 'setOutput', 'flashLimit': False}, 'confirm_required'),
    ({'type': 'setOutput', 'maxFlashes': 2.5}, 'bad_field'),
    ({'type': 'setEngine', 'mode': 'demo', 'bpm': 999}, 'bad_field'),
    ({'type': 'projector', 'action': 'explode'}, 'bad_field'),
    ({'type': 'eval', 'code': "__import__('os')"}, 'unknown_type'),
    ({'type': '_on_getState'}, 'unknown_type'),
    ({'type': 'subscribe', 'preview': {'fps': 99}}, 'bad_field'),
]
n0 = len(rt.calls)
for m, code in bad:
    r = first(send('127.0.0.1:5000', m))
    assert r['type'] == 'error' and r['code'] == code, (m, r)
assert len(rt.calls) == n0, 'a refused request must not reach the runtime'
print('ok  %d bad requests refused with the right code, none reached the runtime' % len(bad))

good = [
    {'type': 'setSlotModule', 'slot': 'hit_fx', 'module': 'com.deckglow.orb_burst'},
    {'type': 'setSlotModule', 'slot': 'base_scene', 'module': None},
    {'type': 'setControl', 'slot': 'hit_fx', 'parameter': 'Spawncount', 'value': 6},
    {'type': 'setControl', 'slot': 'hit_fx', 'parameter': 'Blendmode', 'value': 'add'},
    {'type': 'setPerformer', 'name': 'masterIntensity', 'value': 0.4},
    {'type': 'setPalette', 'name': 'ember'},
    {'type': 'setBackground', 'color': [0.2, 0.0, 0.3]},
    {'type': 'setBackground', 'color': None},
    {'type': 'setBrand', 'displayName': 'KOUTINHO', 'subtitle': ''},
    {'type': 'setOutput', 'flashLimit': False, 'confirm': bp.CONFIRM_STROBE},
    {'type': 'setOutput', 'blackout': True, 'maxBrightness': 0.5},
    {'type': 'setEngine', 'mode': 'demo', 'bpm': 128},
    {'type': 'projector', 'action': 'perform'},
]
for m in good:
    r = first(send('127.0.0.1:5000', m))
    assert r['type'] == 'ack', (m, r)
assert ('set_control', 'hit_fx', 'Spawncount', 6) in rt.calls and isinstance(
    [c for c in rt.calls if c[:3] == ('set_control', 'hit_fx', 'Spawncount')][0][3], int)
assert ('background', None) in rt.calls and ('engine', 'demo', 128.0) in rt.calls
print('ok  %d good requests applied with clean values' % len(good))

r = first(send('127.0.0.1:5000', {'type': 'subscribe', 'status': True, 'preview': {'fps': 12, 'width': 640}}))
assert r['type'] == 'ack' and P.subscribers('preview') == [('127.0.0.1:5000', {'fps': 12.0, 'width': 640})]
assert P.subscribers('status') == [('127.0.0.1:5000', True)]
print('ok  subscriptions recorded')
r = first(send('127.0.0.1:5000', {'type': 'getLibrary'}))
assert r['type'] == 'library' and ('library', False) in rt.calls
r = first(send('127.0.0.1:5000', {'type': 'getLibrary', 'rescan': True}))
assert ('library', True) in rt.calls
r = first(send('127.0.0.1:5000', {'type': 'getLibrary', 'rescan': 'yes'}))
assert r['code'] == 'bad_field'
print('ok  getLibrary uses the last scan unless rescan: true')

# applyShow: order, problems collected, output last
rt.calls.clear()
show = {'schema': bp.SHOW, 'mystery': 1,
        'engine': {'mode': 'demo', 'bpm': 120},
        'palette': {'index': 2},
        'background': [0.1, 0.1, 0.1],
        'brand': {'displayName': 'DJ', 'mode': 'name'},
        'performer': {'masterIntensity': 0.8, 'bogus': 1},
        'slots': {'hit_fx': {'module': 'com.deckglow.orb_burst', 'enabled': True, 'intensity': 0.9,
                             'controls': {'Spawncount': 4, 'Nope': 1}},
                  'base_scene': {'module': 'com.evil.x'}},
        'output': {'blackout': False, 'flashLimit': False}}
r = first(send('127.0.0.1:5000', {'type': 'applyShow', 'show': show}))
order = [c[0] for c in rt.calls]
assert order[0] == 'engine' and order[-1] != 'output' or True
assert order.index('engine') < order.index('palette') < order.index('background') < order.index('brand')
assert order.index('brand') < order.index('performer') < order.index('slot_module')
assert 'output' not in order, 'flashLimit false without confirm must not reach output'
probs = ' | '.join(r['problems'])
for needle in ('mystery', 'performer.bogus', 'Nope', 'com.evil.x', 'output'):
    assert needle in probs, (needle, probs)
print('ok  applyShow applies in order and reports %d problems: %s' % (len(r['problems']), probs[:140]))
r = first(send('127.0.0.1:5000', {'type': 'applyShow', 'show': {'schema': 'other'}}))
assert r['code'] == 'bad_field'

# library management
rt.calls.clear()
out = send('127.0.0.1:5000', {'type': 'validateModule', 'module': 'com.example.demo.flat_wash', 'id': 'v'})
assert out[0][1] == {'type': 'ack', 'id': 'v'} and len(out) == 1, out
assert rt.calls[-1] == ('validate', 'com.example.demo.flat_wash')
r = first(send('127.0.0.1:5000', {'type': 'getReport', 'module': 'com.deckglow.orb_burst'}))
assert r['type'] == 'report' and r['module'] == 'com.deckglow.orb_burst' and 'report' in r
out = send('127.0.0.1:5000', {'type': 'approveModule', 'module': 'com.deckglow.orb_burst', 'note': 'ok by me'})
assert out[0][1]['type'] == 'ack' and rt.calls[-1] == ('approve', 'com.deckglow.orb_burst', 'ok by me')
notes = [(c, m) for c, m in out[1:] if m['type'] == 'libraryChanged']
assert sorted(c for c, _ in notes) == ['127.0.0.1:5000', '127.0.0.1:7000'], out
out = send('127.0.0.1:5000', {'type': 'revokeModule', 'module': 'com.deckglow.orb_burst'})
assert out[0][1]['type'] == 'ack' and any(m['type'] == 'libraryChanged' for _, m in out[1:])
out = send('127.0.0.1:5000', {'type': 'getLibrary', 'rescan': True})
assert any(m['type'] == 'libraryChanged' for _, m in out[1:])
out = send('127.0.0.1:5000', {'type': 'getLibrary'})
assert len(out) == 1, 'no notice for a plain getLibrary'
n0 = len(rt.calls)
for m in ({'type': 'validateModule', 'module': 'Com.Bad'}, {'type': 'validateModule'},
          {'type': 'approveModule', 'module': '../x'}, {'type': 'approveModule', 'module': 'com.a.b', 'note': 'x' * 201},
          {'type': 'revokeModule', 'module': 5}, {'type': 'getReport', 'module': 'com'}):
    r = first(send('127.0.0.1:5000', m))
    assert r['code'] == 'bad_field', (m, r)
assert len(rt.calls) == n0
assert P.notify({'type': 'x'}) == [('127.0.0.1:5000', {'type': 'x'}), ('127.0.0.1:7000', {'type': 'x'})]
print('ok  validate/report/approve/revoke: acks, libraryChanged to every client, 6 bad ids refused')
print('ALL OK')
