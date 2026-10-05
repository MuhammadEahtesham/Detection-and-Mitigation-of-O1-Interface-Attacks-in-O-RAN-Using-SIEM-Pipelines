# Benign Baseline Capture — O1 Interface (NETCONF over TLS)

Project: O-RAN Network Intrusion Detection Pipeline (Suricata + Wazuh + anomaly detection)
Purpose: Produce a capture of **normal** O1 management traffic, used to train the anomaly detection models (z-score baseline first, then Isolation Forest and One-Class SVM). Unsupervised anomaly detection learns what normal traffic looks like and flags deviations, so it requires a dedicated benign dataset separate from the attack captures.

Prerequisite: the O-RAN SC OAM stack is running and the controller holds a live NETCONF/TLS session to the O-DU. See `README-oran-stack-startup.md`.

---

## Why a new capture was needed

The existing TLS attack capture (`tls_flood_2.pcap`, 42 min 45 s) contains about 40 minutes of non-attack traffic before the flood. That period was rejected as a baseline:

| Capture segment | Packets per minute | Problem |
|---|---|---|
| `tls_flood_2.pcap`, minutes 0–40 | ~8 | Idle system, not normal operation. Most 1-second windows would be empty. |
| `tls_flood_2.pcap`, minutes 41–42 | 12,833 / 3,197 | The attack itself |

A model trained on near-silence would flag any real management activity as anomalous. The baseline therefore needed to capture the O1 interface **while it was actively being used**.

---

## Design decisions

**Capture point: the O-DU's `dcn` interface.** The Data Communication Network carries O1 management traffic, and it is the same network segment the attack captures were taken on. This keeps the benign and attack data comparable.

**Named interface, not `-i any`.** Capturing with `-i any` produces the Linux cooked-mode v2 (SLL2) link type, which Suricata cannot read and which required conversion earlier in the project. Capturing on `eth0` produces standard Ethernet framing.

**Capture from a helper container.** `nicolaka/netshoot` runs with `--network container:<name>`, sharing the target container's network stack. Nothing is installed into the O-DU or controller, and the capture file is written directly to the host through a volume mount.

**Realistic, irregular traffic.** A request every second on a fixed timer would teach the model that a perfectly regular rhythm is normal, making real traffic look anomalous. The generator uses randomised pauses, occasional bursts, and occasional pings to resemble a real management system.

---

## Step 1 — Identify the capture interface

The O-DU has two network interfaces. The one holding its `dcn` address carries O1 traffic.

```bash
docker run --rm --network container:pynts-o-du-o1 nicolaka/netshoot ip -brief addr
```

Result:

| Interface | Address | Network |
|---|---|---|
| `eth0` | 172.21.0.100/16, 2001:db8:1:50::6/96 | `dcn` — capture here |
| `eth1` | 172.19.0.12/16 | `smo` |

The remaining interfaces (`tunl0`, `gre0`, `sit0`, …) are Docker Desktop tunnel interfaces, all down.

The IPv6 subnet `2001:db8:1:50::/96` matches the IPv6 background flows seen in the ICMP attack capture, confirming the benign data comes from the same network.

---

## Step 2 — Find O-DU data paths that generate real NETCONF requests

An idle NETCONF session only exchanges a keepalive every 120 seconds. To produce realistic activity, the controller is asked to read data from the O-DU through its mount point. Each RESTCONF read is translated by the controller into a NETCONF `<get>` sent to the O-DU over TLS.

```bash
alias ctlcurl='docker run --rm -i --network container:controller nicolaka/netshoot curl'
BASE="http://localhost:8181/rests/data/network-topology:network-topology/topology=topology-netconf/node=pynts-o-du-o1/yang-ext:mount"

for P in \
  "ietf-interfaces:interfaces" \
  "_3gpp-common-managed-element:ManagedElement" \
  "ietf-netconf-monitoring:netconf-state" \
  "ietf-hardware:hardware" \
  "ietf-yang-library:yang-library"; do
  echo -n "$P -> "
  ctlcurl -s -o /dev/null -w "HTTP %{http_code} in %{time_total}s\n" \
    -u 'admin:<ADMIN_PASSWORD>' "$BASE/$P"
done
```

Results:

| Path | Result | Used |
|---|---|---|
| `ietf-interfaces:interfaces` | 409 `data-missing` — the O-DU has no data under this container | No |
| `_3gpp-common-managed-element:ManagedElement` | 400 — a YANG list, needs a key in the path | No |
| `ietf-netconf-monitoring:netconf-state` | 200 | Yes |
| `ietf-hardware:hardware` | 200 | Yes |
| `ietf-yang-library:yang-library` | 200 | Yes |

What the three selected paths contain:

- **`ietf-netconf-monitoring:netconf-state`** — the O-DU's report on its own NETCONF server: active sessions, statistics counters, capabilities, available schemas. Counters change over time, so responses vary.
- **`ietf-hardware:hardware`** — physical inventory (components, serial numbers, firmware, state). Small response.
- **`ietf-yang-library:yang-library`** — the full list of YANG modules the O-DU implements. Large response.

These are standard IETF modules every NETCONF device implements, and together they produce a realistic spread of response sizes, which matters for the packet-size features used in anomaly detection.

---

## Step 3 — Create the traffic generator

```bash
mkdir -p ~/Desktop/TU_Ilmenau/Seminar/captures

cat > ~/Desktop/TU_Ilmenau/Seminar/captures/benign_traffic.sh << 'EOF'
#!/bin/bash
BASE='http://localhost:8181/rests/data/network-topology:network-topology/topology=topology-netconf/node=pynts-o-du-o1/yang-ext:mount'
PATHS=("ietf-netconf-monitoring:netconf-state" "ietf-hardware:hardware" "ietf-yang-library:yang-library")
DURATION=${DURATION:-1200}
END=$((SECONDS + DURATION))
n=0

read_one() {
  local P=${PATHS[$((RANDOM % ${#PATHS[@]}))]}
  local code=$(curl -s -o /dev/null -w "%{http_code}" -u "$AUTH" "$BASE/$P")
  n=$((n + 1))
  echo "$(date +%T) #$n $P -> $code"
}

while [ $SECONDS -lt $END ]; do
  read_one

  # Occasionally an operator browses several views in quick succession
  if [ $((RANDOM % 10)) -eq 0 ]; then
    for i in $(seq $((RANDOM % 3 + 2))); do read_one; sleep 0.3; done
  fi

  # Occasional reachability check, as health monitoring would do
  if [ $((RANDOM % 20)) -eq 0 ]; then
    ping -c $((RANDOM % 3 + 1)) 172.21.0.100 > /dev/null
    echo "$(date +%T) ping"
  fi

  # Irregular pause between 0.5 and 6 seconds
  sleep $(awk -v r=$RANDOM 'BEGIN{printf "%.2f", 0.5 + (r / 32767) * 5.5}')
done

echo "done: $n requests in $DURATION seconds"
EOF
```

Behaviour per iteration:

| Behaviour | Probability | Purpose |
|---|---|---|
| One read of a randomly chosen path | always | Baseline polling |
| Burst of 2–4 extra reads, 0.3 s apart | 1 in 10 | Operator browsing several views |
| 1–3 ICMP echo requests to the O-DU | 1 in 20 | Health monitoring |
| Pause of 0.5–6 s | always | Irregular timing |

The password is passed as an environment variable (`AUTH`) rather than written into the script.

---

## Step 4 — Start the capture (Terminal 1)

```bash
docker run --rm -it --name benign-capture \
  --network container:pynts-o-du-o1 \
  -v ~/Desktop/TU_Ilmenau/Seminar/captures:/captures \
  nicolaka/netshoot tcpdump -i eth0 -w /captures/benign_baseline.pcap
```

Started before the generator, so the capture includes the start of the activity.

---

## Step 5 — Run the traffic generator (Terminal 2)

```bash
docker run --rm -it --name benign-traffic \
  --network container:controller \
  -e AUTH='admin:<ADMIN_PASSWORD>' \
  -e DURATION=1200 \
  -v ~/Desktop/TU_Ilmenau/Seminar/captures:/captures \
  nicolaka/netshoot bash /captures/benign_traffic.sh
```

Runs inside the controller's network namespace, so every request is a genuine RESTCONF call that the controller turns into NETCONF over TLS to the O-DU. Duration: 20 minutes.

---

## Step 6 — Stop the capture

After the generator printed `done`, the capture in Terminal 1 was stopped with **Ctrl+C**.

Ctrl+C (SIGINT) lets tcpdump flush its buffer and close the file correctly. `kill -9` skips the flush, which is what produced an empty 24-byte pcap earlier in the project.

---

## Step 7 — Verify the raw capture

```bash
docker cp ~/Desktop/TU_Ilmenau/Seminar/captures/benign_baseline.pcap single-node-wazuh.manager-1:/tmp/
docker exec single-node-wazuh.manager-1 capinfos -c -a -e -u /tmp/benign_baseline.pcap
```

Result:

| Property | Value |
|---|---|
| Packets | ~39,000 |
| File size | 20.4 MB |
| Duration | 2,472.8 s (~41 min) |
| Start | 2026-09-22 16:59:07.86 |
| End | 2026-09-22 17:40:20.66 |

The capture ran about 21 minutes longer than the generator, so it contains idle periods before and after the activity.

---

## Step 8 — Inspect the per-minute timeline

```bash
docker exec single-node-wazuh.manager-1 python3 /tmp/timeline.py /tmp/benign_baseline.pcap
```

`timeline.py` counts packets per minute using scapy:

```python
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
```

Result:

| Minutes | Packets per minute | State |
|---|---|---|
| 0–8 | ~100 | Background only, before the generator |
| 9 | 1,332 | Generator starts partway through |
| 10–28 | 968 – 2,862 | Generator running |
| 29 | 823 | Generator ends partway through |
| 30–41 | ~100 | Background only, after the generator |

Observations:

- **The active period varies naturally** (968 to 2,862 packets per minute), a result of the randomised pauses and bursts.
- **The idle background is ~100 packets per minute** — TLS keepalives, VES retries, and IPv6 neighbour traffic from the live stack. This is over ten times the ~8 per minute idle rate in the old TLS capture, but still too sparse to serve as the baseline on its own.

---

## Step 9 — Trim to the fully active window

Minutes 9 and 29 are only partly active, so the baseline uses minutes 10 through 28: 19 full minutes, about 1,140 one-second windows.

The capture started at 16:59:07.86, so minute 10 begins at 17:09:07.86 and minute 28 ends at 17:28:07.86.

```bash
docker exec single-node-wazuh.manager-1 editcap \
  -A "2026-09-22 17:09:08" -B "2026-09-22 17:28:07" \
  /tmp/benign_baseline.pcap /tmp/benign_active.pcap
```

`capinfos` and `editcap` run in the same container, so both interpret times in the same timezone.

Verify:

```bash
docker exec single-node-wazuh.manager-1 capinfos -c -a -e -u -E /tmp/benign_active.pcap
docker exec single-node-wazuh.manager-1 python3 /tmp/timeline.py /tmp/benign_active.pcap
```

Expected: about 19 minutes, Ethernet encapsulation, and no idle minutes at either end.

Copy back to the host:

```bash
docker cp single-node-wazuh.manager-1:/tmp/benign_active.pcap ~/Desktop/TU_Ilmenau/Seminar/captures/
```

**Methodology note:** Trimming defines the baseline as "the O1 interface under normal management activity." Keeping the idle minutes would mix two different normal states (active and idle), widening the standard deviations the z-score method relies on. For volumetric floods, which sit orders of magnitude above either state, detection works either way; trimming gives the cleaner result.

---

## Step 10 — Confirm the TLS content

Wireshark only recognises TLS automatically on well-known ports such as 443, so port 6513 must be decoded explicitly with `-d tcp.port==6513,tls`.

Protocol breakdown:

```bash
docker exec single-node-wazuh.manager-1 tshark -r /tmp/benign_active.pcap \
  -d tcp.port==6513,tls -q -z io,phs
```

Total TLS packets:

```bash
docker exec single-node-wazuh.manager-1 sh -c \
  'tshark -r /tmp/benign_active.pcap -d tcp.port==6513,tls -Y tls | wc -l'
```

New TLS sessions (Client Hello):

```bash
docker exec single-node-wazuh.manager-1 sh -c \
  'tshark -r /tmp/benign_active.pcap -d tcp.port==6513,tls -Y "tls.handshake.type==1" | wc -l'
```

**Expected characteristic:** thousands of TLS packets but very few Client Hellos. The controller keeps one long-lived TLS session to the O-DU and sends every request through it, so almost all TLS traffic is encrypted application data.

This is the key contrast with the attack:

| | Benign baseline | TLS flood attack |
|---|---|---|
| TLS sessions | One, long-lived | 2,543 separate flows |
| Dominant TLS content | Application data | Handshakes |
| New flows per second | Near zero | High |

Features such as new flows per second and handshake count should therefore separate the two sharply. It also means signature rule sid:1000002, which matches TLS handshake bytes (`|16 03|`), should stay quiet on this capture — a useful false-positive test.

---

## Resulting files

All in `~/Desktop/TU_Ilmenau/Seminar/captures/`:

| File | Content | Use |
|---|---|---|
| `benign_baseline.pcap` | Full 41-minute capture, active and idle | Archive; idle minutes can serve as an "idle normal" test set |
| `benign_active.pcap` | Minutes 10–28, active only | **Training baseline** for anomaly detection |
| `benign_traffic.sh` | Traffic generator | Reproducibility |

---

## Protocol content of the baseline

| Protocol | Source | Present |
|---|---|---|
| NETCONF over TLS (TCP 6513) | Controller ↔ O-DU management reads | Yes, dominant |
| ICMP | Generator's occasional pings | Yes, sparse |
| HTTP | O-DU's VES event posts to the collector | Yes, sparse |
| IPv6 neighbour/multicast | Background network activity | Yes, sparse |
| UDP | — | Not deliberately generated |

**Limitation:** the baseline contains no deliberately generated UDP traffic. This reflects how the O1 interface works — NETCONF management does not use UDP — so it is a property of the environment rather than a gap in the capture. It should nonetheless be stated when reporting results on the UDP flood.
