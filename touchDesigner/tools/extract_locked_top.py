"""Converts a locked TOP's .data (from toeexpand) into a PNG.

Runs outside TouchDesigner, with any Python 3:

    python -I extract_locked_top.py <node.data> <out.png>

A locked TOP stores its frozen image as <node>.data in an expanded .toe: a
newline-separated header (width and height are fields 2 and 3) ending in '*',
then 8-bit RGBA rows bottom-up. Used once to recover
modules/kinetic_stripes/assets/stripe_lookup.png from level1 in
ReactiveVisualsTouchDesignerProtoOsc.8.toe.
"""
import struct
import sys
import zlib

src, dst = sys.argv[1], sys.argv[2]
raw = open(src, 'rb').read()

# header: newline-separated fields ending in '*', then pixel bytes
star = raw.index(b'*')
fields = raw[:star].split(b'\n')
print('header fields:', [f.decode() for f in fields if f])
w, h = int(fields[1]), int(fields[2])
px = raw[star + 1:]
bpp = len(px) // (w * h)
print('size %dx%d, %d bytes/pixel, %d spare bytes' % (w, h, bpp, len(px) - w * h * bpp))
assert bpp == 4

grey = all(px[i] == px[i + 1] == px[i + 2] for i in range(0, w * h * 4, 4))
alpha = set(px[3:w * h * 4:4])
print('r=g=b everywhere:', grey, '| alpha values:', sorted(alpha)[:5])
vals = px[0:w * h * 4:4]
print('min/max/mean:', min(vals), max(vals), sum(vals) / len(vals))

# TouchDesigner stores rows bottom-up; PNG is top-down
rows = [px[r * w * 4:(r + 1) * w * 4] for r in range(h)][::-1]
body = b''.join(b'\x00' + r for r in rows)


def chunk(tag, data):
    c = struct.pack('>I', len(data)) + tag + data
    return c + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)


png = (b'\x89PNG\r\n\x1a\n'
       + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
       + chunk(b'IDAT', zlib.compress(body, 9))
       + chunk(b'IEND', b''))
open(dst, 'wb').write(png)
print('wrote', dst, len(png), 'bytes')
