<div align="center">

# 🛡️ O-RAN O1 Interface Intrusion Detection

### Detecting DDoS attacks on the management channel of Open RAN 5G networks

![Status](https://img.shields.io/badge/status-research%20complete-success)
![Suricata](https://img.shields.io/badge/IDS-Suricata-red)
![Wazuh](https://img.shields.io/badge/SIEM-Wazuh%204.7.3-blue)
![Python](https://img.shields.io/badge/Python-3.x-yellow)
![Docker](https://img.shields.io/badge/Docker-containerised-2496ED)
![License](https://img.shields.io/badge/license-MIT-green)


</div>

---

## 📖 What is this project?

Modern 5G networks are moving to **Open RAN (O-RAN)** — an open, multi-vendor design that replaces closed, single-vendor equipment. O-RAN has a special control channel called the **O1 interface**: think of it as the *remote control* that configures and monitors the entire radio network from one place.

That remote control is a tempting target. If an attacker floods it with junk traffic — a **DDoS attack (Distributed Denial of Service)** — the operator can lose the ability to manage the whole network at once. No data is stolen; the system is simply overwhelmed until it stops responding.

**This project answers one question:** *Can we reliably detect such an attack on the O1 interface?*

The answer is yes — using a two-layer detection system built from open-source security tools.

---

## 🧩 Key terms

| Term | What it means here |
|---|---|
| **O-RAN** | Open Radio Access Network — an open standard for building 5G networks |
| **O1 interface** | The management channel between the control centre (SMO) and network equipment (O-DU) |
| **SMO** | Service Management & Orchestration — the "brain" that manages the network |
| **O-DU** | O-RAN Distributed Unit — a piece of network equipment being managed |
| **DDoS / DoS** | An attack that floods a target with traffic until it can't respond |
| **NETCONF/TLS** | The secure protocol O1 uses to send management commands (on port 6513) |
| **Suricata** | An open-source engine that inspects network traffic for attacks |
| **Wazuh** | An open-source SIEM — a dashboard that collects and displays security alerts |
| **Anomaly detection** | Learning what "normal" looks like, then flagging anything unusual |

---

## 🎯 What was built

A **two-layer detection pipeline**:

**Layer 1 — Signature detection (catches known attacks)**
Custom Suricata rules spot the exact fingerprint of each attack and raise an alert in the Wazuh dashboard.

**Layer 2 — Anomaly detection (catches hidden attacks)**
A statistical model learns what normal O1 traffic looks like, then flags traffic that deviates — useful for attacks that disguise themselves inside legitimate encrypted traffic.

---

## 🏗️ How it works

```
   🔴 Attacker
       │  floods with DDoS traffic
       ▼
   O1 interface  (NETCONF over TLS, port 6513)
   ┌─────────────┐          ┌─────────────┐
   │     SMO     │◄────────►│    O-DU     │
   │ (controller)│          │  (network   │
   │             │          │  equipment) │
   └─────────────┘          └──────┬──────┘
                                   │ traffic captured
                                   ▼
                          ┌──────────────────┐
                          │     Suricata     │  ← inspects traffic
                          │   (inside Wazuh) │
                          └────────┬─────────┘
                                   │ alerts
                                   ▼
                    Wazuh Indexer → Wazuh Dashboard  📊
                                   ▲
                      Anomaly detection (z-score model)
```

---

## 📊 Results

Three attacks were simulated and detected:

| Attack | Caught by signatures? | Caught by anomaly model? |
|:---|:---:|:---:|
| 🔐 TLS handshake flood | ✅ Yes | ✅ ~71% of attack windows |
| 📡 UDP flood | ✅ Yes | — (UDP never appears on O1) |
| 📶 ICMP flood | ✅ Yes | ✅ 100% of attack windows |

**Proof the attack worked:** during the TLS flood, the server received **~6,500 connection attempts** but could answer only **~950** — about **85% of connections were dropped**. That gap *is* the denial of service.

**False alarms:** ~6.6% on normal traffic (a deliberately simple baseline model — tunable, and improvable with the machine-learning models listed in Future Work).

---

## 📁 Repository structure

```
📂 rules/                  Custom Suricata detection rules
📂 attacks/                Attack scripts + attacker Dockerfile
📂 detection/              Feature extraction + anomaly detection (Python)
📂 scripts/                Benign traffic generator
📂 screenshots/            Wazuh dashboard results
📂 Weekly_documentation/   Project logs and methodology
```

> ℹ️ Packet captures (`.pcap`) and the upstream O-RAN platform are **not** included — captures are large and can be regenerated; the O-RAN stack is cloned separately (see Setup).

---

## 🚀 Getting started

> **Note:** This is a research testbed, not a plug-and-play tool. These steps outline how the environment is assembled.

**1. Prerequisites**
- Docker & Docker Compose
- Python 3 with `scapy` (`pip install scapy`)
- Suricata and Wireshark tools

**2. Clone the upstream platforms** (not bundled here)
```bash
# O-RAN SC OAM stack (the SMO + simulated network functions)
git clone "https://gerrit.o-ran-sc.org/r/oam"
# Wazuh single-node SIEM
git clone "https://github.com/wazuh/wazuh-docker"
```

**3. Load the detection rules**
Copy `rules/oran-custom.rules` into Suricata's rules directory and register it in `suricata.yaml`.

**4. Run an attack capture through detection**
```bash
suricata -c /etc/suricata/suricata.yaml -r attacks/<capture>.pcap -l /var/log/suricata/
```

**5. Run the anomaly detection**
```bash
python3 detection/extract_windows.py <capture>.pcap features.csv <label>
python3 detection/z_score_model.py
```

---

## 🔬 Example: the detection rules

```suricata
# UDP flood on the O1 port
alert udp any any -> any 6513 (msg:"O1 Interface UDP Flood - T-SMO";
  threshold: type both, track by_dst, count 100, seconds 1; sid:1000001; rev:1;)

# TLS handshake flood
alert tcp any any -> any 6513 (msg:"ORAN_T-SMO TLS handshake flood detected";
  flow:to_server; content:"|16 03|"; depth:2;
  threshold:type threshold, track by_src, count 100, seconds 5;
  classtype:attempted-dos; sid:1000002; rev:1;)

# ICMP flood
alert icmp $HOME_NET any -> $HOME_NET any (msg:"ORAN T-SMO-03 ICMP flood on O1";
  itype:8; dsize:>1000;
  threshold: type threshold, track by_src, count 100, seconds 1;
  classtype:attempted-dos; sid:1000003; rev:1;)
```

---

## 🔭 Future work

- 🤖 Add machine-learning anomaly models (Isolation Forest, One-Class SVM)
- 📈 Larger benign baseline + cross-validated results with confidence intervals
- 🛑 **Automated mitigation** — move from *detecting* attacks to *blocking* them automatically
- 🌐 Validate on live traffic capture (beyond offline replay)

---

## 🧰 Built with

`O-RAN` · `Suricata` · `Wazuh SIEM` · `NETCONF/TLS` · `Python` · `scapy` · `Docker` · `Wireshark`

---

## 👤 Author

**Muhammad Eahtesham** — M.Sc. Computer Science, TU Ilmenau
Supervisor: *Manasik Hassan* · Chair: *Prof. Dr.-Ing. habil. Andreas Mitschele-Thiel* (RCSE)

<div align="center">

⭐ If you find this project useful, consider starring the repo.

</div>
