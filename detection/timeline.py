import sys
from collections import Counter
from scapy.all import PcapReader, conf
conf.verb = 0

c = Counter()
t0 = None
with PcapReader(sys.argv[1]) as pr:
    for p in pr:
        t = float(p.time)
        if t0 is None:
            t0 = t
        c[int((t - t0) // 60)] += 1

for m in sorted(c):
    print(f"min {m:3d}: {c[m]:8d} packets")
