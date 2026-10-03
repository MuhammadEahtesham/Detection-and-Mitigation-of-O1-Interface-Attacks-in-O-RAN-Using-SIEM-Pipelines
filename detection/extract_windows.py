import sys, csv, statistics
from collections import defaultdict
from scapy.all import PcapReader, IP, IPv6, TCP, UDP, ICMP, conf
conf.verb = 0

pcap, outfile, label = sys.argv[1], sys.argv[2], sys.argv[3]
WINDOW = 1.0

def new_bin():
    return {"sizes": [], "src": set(), "dst": set(), "dports": set(),
            "tcp": 0, "udp": 0, "icmp": 0, "syn": 0, "tls_hs": 0}

bins = defaultdict(new_bin)
t0 = None
seen = 0

with PcapReader(pcap) as pr:
    for p in pr:
        seen += 1
        t = float(p.time)
        if t0 is None:
            t0 = t
        b = bins[int((t - t0) // WINDOW)]
        b["sizes"].append(len(p))

        if p.haslayer(IP):
            b["src"].add(p[IP].src); b["dst"].add(p[IP].dst)
        elif p.haslayer(IPv6):
            b["src"].add(p[IPv6].src); b["dst"].add(p[IPv6].dst)

        if p.haslayer(TCP):
            b["tcp"] += 1
            b["dports"].add(int(p[TCP].dport))
            flags = int(p[TCP].flags)
            if flags & 0x02 and not flags & 0x10:
                b["syn"] += 1
            payload = bytes(p[TCP].payload)
            if payload[:2] == b'\x16\x03':
                b["tls_hs"] += 1
        elif p.haslayer(UDP):
            b["udp"] += 1
            b["dports"].add(int(p[UDP].dport))
        elif p.haslayer(ICMP):
            b["icmp"] += 1

        if seen % 200000 == 0:
            print("read", seen, flush=True)

rows = []
for idx in range(0, max(bins) + 1):
    b = bins.get(idx, new_bin())
    s = b["sizes"]
    n = len(s)
    rows.append({
        "window": idx,
        "pkts": n,
        "bytes": sum(s),
        "mean_size": round(statistics.mean(s), 2) if n else 0,
        "std_size": round(statistics.pstdev(s), 2) if n > 1 else 0,
        "min_size": min(s) if n else 0,
        "max_size": max(s) if n else 0,
        "unique_src": len(b["src"]),
        "unique_dst": len(b["dst"]),
        "unique_dports": len(b["dports"]),
        "tcp_frac": round(b["tcp"] / n, 4) if n else 0,
        "udp_frac": round(b["udp"] / n, 4) if n else 0,
        "icmp_frac": round(b["icmp"] / n, 4) if n else 0,
        "syn_count": b["syn"],
        "tls_handshake": b["tls_hs"],
        "label": label,
    })

with open(outfile, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

print(f"DONE: {seen} packets -> {len(rows)} windows -> {outfile}")
