#!/usr/bin/env python3
"""diag_payload.py SRC.metal OUT_PREFIX: write OUT_PREFIX.orig.metal / .repl.metal for a Lichii mesh program (native
[[mesh]] form or emulated compute form) in which output line 5..7 (the varying at location 2) carries a picture of
the task payload instead of its real value: red = element count of the task (low byte), green = hash of the task's
base index, blue = hash of this element's payload word. Draw both forms with a fragment override that shows that
varying and the depth test open, and the two pictures must agree wherever the payloads do."""
import re, sys
src = open(sys.argv[1]).read()
m = re.search(r'<< 5u\) \+ gl_SubgroupInvocationID;\n\s*uint (_\d+) = _\d+ >> 1u;', src)
assert m, 'element index not found'
elem = m[1]
H = '2654435761u'
vals = {
    640: 'as_type<uint>(float(task_payload[5u] & 255u) * 0.0039215688593685627)',
    768: f'as_type<uint>(float(min({elem}, 255u)) * 0.0039215688593685627)',
    896: f'as_type<uint>(float((task_payload[4u] * {H}) >> 24u) * 0.0039215688593685627)',
}
out, n = src, 0
for off, v in vals.items():
    out, k = re.subn(r'(isbe_attributes\[min\(\(\(_\d+ \+ %du\) >> 2u\), \d+u\)\] = )[^;]+;' % off, lambda mm: mm[1] + v + ';', out)
    n += k
assert n >= 3, n
open(sys.argv[2] + '.orig.metal', 'w').write(src)
open(sys.argv[2] + '.repl.metal', 'w').write(out)
print(sys.argv[2], 'element', elem, 'stores replaced', n)
