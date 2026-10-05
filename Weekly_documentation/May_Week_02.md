-- Connect CU with SMO
-- Literature Review
-- Attack on O1 interface

# O-CU (Central Unit) Setup and SMO Connection Guide

This document covers the complete process of setting up a simulated O-CU and connecting it to the SMO stack in the O-RAN NTS simulation environment on Apple Silicon Mac (ARM64).

---

## Table of Contents

1. [Architecture](#architecture)
2. [Goal](#goal)
3. [Approach Options](#approach-options)
4. [Final Working Setup](#final-working-setup)
5. [Problems and Troubleshooting](#problems-and-troubleshooting)
6. [Commands Reference](#commands-reference)
7. [Current Status](#current-status)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     SMO Stack                           │
│   controller (ODL :8181)  +  ves-collector (:8080)      │
└──────────────────────┬──────────────────────────────────┘
                       │ VES HTTP (pnfRegistration, FileReady)
                       ↑
┌──────────────────────┴──────────────────────────────────┐
│                 pynts-o-cu (O-CU sim)                   │
│         VES → SMO ✅    NETCONF TLS port 6513 ✅        │
│                   IP: 172.21.0.8                        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│               pynts-o-du-o1 (O-DU)                      │
│         VES → SMO ✅    Sessions active ✅              │
└──────────┬──────────────────────────┬───────────────────┘
           │ NETCONF TLS (port 4335)  │ NETCONF TLS (port 4335)
           ↓                          ↓
┌──────────────────┐      ┌──────────────────────────────┐
│ pynts-o-ru-      │      │ pynts-o-ru-hierarchical      │
│ hybrid ✅        │      │ ✅                            │
└──────────────────┘      └──────────────────────────────┘
```

### O-CU Ports

| Port | Protocol | Purpose |
|---|---|---|
| 6513 | NETCONF TLS | NETCONF server (listen) |
| 4336 | NETCONF CallHome | CallHome to O-DU |
| 8080 | HTTP REST | PyNTS internal API |
| 22 | SSH | Secure shell |
| 21 | FTP | File transfer |

---

## Goal

Connect a simulated O-CU to the SMO over the O1 interface so that:

- O-CU sends `pnfRegistration` VES events to SMO ✅
- O-CU sends periodic performance management events to SMO ✅
- O-CU is visible to the SMO controller (ODL) via NETCONF

---

## Approach Options

Three approaches were investigated:

### Option 1 — OAI (OpenAirInterface) O-CU
A real software implementation of O-CU supporting RRC, PDCP, F1, E1 and O1 interfaces. Requires USRP radio hardware, complex 5G configuration, and source compilation. Too complex for this simulation setup.

### Option 2 — NTS O-CU Image (nexus3.o-ran-sc.org)
A dedicated NTS-based O-CU simulator from the O-RAN SC registry. Attempted but the image `nts-ng-o-ran-cu-cp` and `nts-ng-o-ran-cu-up` do not exist on the registry.

Available NTS images on the registry:
```
o-ran-sc/nts-ng-base
o-ran-sc/nts-ng-blank
o-ran-sc/nts-ng-o-ran-du        ← exists (used for O-DU)
o-ran-sc/nts-ng-o-ran-fh
o-ran-sc/nts-ng-o-ran-ru-fh
o-ran-sc/nts-ng-x-ran
o-ran-sc/o-du-l2-cu-stub        ← exists (tried, failed on ARM64)
```

### Option 3 — pynts O-DU Image as O-CU (Final Solution ✅)
Reuse the existing `pynts-o-du-o1:latest` image with the O-DU data volume mounted, configured with a different callhome port to simulate an O-CU. This approach works because the pynts image already has all required services (NETCONF, VES, SSH, FTP) and the data volume provides the correct YANG models.

---

## Final Working Setup

### Step 1: Ensure pynts images are built

```bash
cd ~/Desktop/TU_Ilmenau/Seminar/o1-ofhmp-interfaces

docker build -t pynts-base:latest -f base/Dockerfile .
docker build -t pynts-o-du-o1:latest -f o-du-o1/Dockerfile .
docker build -t pynts-o-ru-mplane:latest -f o-ru-mplane/Dockerfile .
```

### Step 2: Run O-CU container with O-DU data volume

The key is mounting the O-DU data directory as the `/data` volume — this provides the YANG models needed by netopeer2:

```bash
docker run -d \
  --name pynts-o-cu \
  --network dcn \
  -e SDNR_RESTCONF_URL=http://controller:8181 \
  -e SDNR_USERNAME=admin \
  -e SDNR_PASSWORD=Kp8bJ4SXszM0WXlhak3eHlcse2gAw84vaoGGmJvUy2U \
  -e VES_URL=http://ves-collector:8080/eventListener/v7 \
  -e VES_USERNAME=sample1 \
  -e VES_PASSWORD=sample1 \
  -e NETCONF_USERNAME=netconf \
  -e NETCONF_PASSWORD=netconf! \
  -e O_DU_CALLHOME_PORT=4336 \
  -v ~/Desktop/TU_Ilmenau/Seminar/oam/solution/network/o-du-o1/data:/data \
  pynts-o-du-o1:latest
```

### Step 3: Apply config.py patch (required every restart)

```bash
docker cp /tmp/config.py pynts-o-cu:/app/core/config.py
docker restart pynts-o-cu
```

If `/tmp/config.py` is not available (Docker Desktop restarted):

```bash
docker cp pynts-o-cu:/app/core/config.py /tmp/config.py
sed -i '' "s/if iface == 'lo':/if iface in ['lo', 'tunl0', 'gre0', 'gretap0', 'erspan0', 'ip_vti0', 'ip6_vti0', 'sit0', 'ip6tnl0', 'ip6gre0']:/" /tmp/config.py
docker cp /tmp/config.py pynts-o-cu:/app/core/config.py
docker restart pynts-o-cu
```

### Step 4: Verify O-CU is running

```bash
sleep 30
docker ps | grep pynts-o-cu
docker exec pynts-o-cu ss -tlnp
docker exec pynts-o-cu cat /var/log/pynts.log | grep "pnfRegistration\|succeeded" | tail -5
```

### Step 5: Verify VES events reaching SMO

```bash
docker logs ves-collector --since 1m | grep "pnfRegistration\|276782"
```

### Step 6: Capture O-CU → SMO traffic with tcpdump

```bash
docker exec pynts-o-cu tcpdump -i any port 8080 -v -c 15 2>/dev/null
```

---

## Problems and Troubleshooting

---

### Problem 1 — NTS O-CU Image Not Found

**Error:**
```
Error response from daemon: failed to resolve reference
"nexus3.o-ran-sc.org:10004/o-ran-sc/nts-ng-o-ran-cu-cp:latest": not found
```

**Root Cause:** The O-CU specific NTS images (`nts-ng-o-ran-cu-cp`, `nts-ng-o-ran-cu-up`) do not exist on the O-RAN SC Nexus registry. Only O-DU and O-RU images are available.

**Fix:** Use `o-du-l2-cu-stub` or repurpose the pynts O-DU image.

---

### Problem 2 — o-du-l2-cu-stub Exits Immediately (Exit Code 0)

**Error:**
```
3566e4ac0562  o-du-l2-cu-stub:12.0.1  "/bin/bash"  Exited (0) 51 seconds ago
```

**Root Cause:** The container entrypoint is `/bin/bash` with no command to keep it running. It starts, does nothing, and exits cleanly.

**Fix:** Override the entrypoint to keep the container alive:
```bash
docker run -d ... o-du-l2-cu-stub:12.0.1 /bin/bash -c "tail -f /dev/null"
```

---

### Problem 3 — o-du-l2-cu-stub Missing Tools (ifconfig, nslookup)

**Error:**
```
/opt/o-du-l2/cu-docker-entrypoint.sh: line 1: ifconfig: command not found
/opt/o-du-l2/cu-docker-entrypoint.sh: line 5: nslookup: command not found
CU not able to fetch DU Service IP address
CU Stopped......!
```

**Root Cause:** The CU entrypoint script requires `ifconfig` (net-tools) and `nslookup` (dnsutils) which are not installed in the base image. Also the `DU_ADDRESS` environment variable was not set.

**Fix:** Install missing tools and provide DU_ADDRESS:
```bash
docker run -d \
  -e DU_ADDRESS=pynts-o-du-o1 \
  ... \
  o-du-l2-cu-stub:12.0.1 \
  /bin/bash -c "apt-get install -y net-tools dnsutils && /opt/o-du-l2/cu-docker-entrypoint.sh"
```

---

### Problem 4 — o-du-l2-cu-stub Source Code Not Found

**Error:**
```
sed: can't read l2/src/cu_stub/cu_stub.h: No such file or directory
cd: /root/l2/build/odu/: No such file or directory
make: *** No rule to make target 'clean_cu'. Stop.
```

**Root Cause:** The CU stub entrypoint script tries to **compile from source** at runtime. The source files and build directory `/root/l2` do not exist in the image — they were expected to be mounted or pre-built.

**Fix:** This image requires source code compilation which is not feasible in this Docker-only setup. Abandoned in favour of pynts approach.

---

### Problem 5 — NTS O-RAN DU Image Segfault on ARM64 (Exit Code 139)

**Error:**
```
5c805dd3a442  nts-ng-o-ran-du:1.8.1  Exited (139) 9 seconds ago
```

**Root Cause:** Exit code 139 = segmentation fault. The NTS O-RAN DU binary is compiled for AMD64. Even with `--platform linux/amd64` and Rosetta 2, the binary crashes due to incomplete emulation of certain CPU instructions on Apple Silicon M1/M2.

**Fix:** Cannot be fixed on Mac ARM64. Use pynts images instead which are built from Python source and run on any platform.

---

### Problem 6 — pynts O-CU Crashes with SysrepoCallbackFailedError

**Error:**
```
sysrepo.errors.SysrepoCallbackFailedError: sr_session_start failed: User callback failed
```

**Root Cause:** Running pynts O-DU image with `-e NETWORK_FUNCTION_TYPE=o-cu` caused a crash because the pynts application tried to load O-CU specific YANG models that don't exist in the container. The sysrepo datastore callback failed when trying to initialize the wrong network function type.

**Fix:** Remove the `NETWORK_FUNCTION_TYPE=o-cu` environment variable and instead mount the O-DU data volume which contains the correct YANG models:
```bash
-v ~/Desktop/TU_Ilmenau/Seminar/oam/solution/network/o-du-o1/data:/data
```

---

### Problem 7 — netopeer2 Cannot Find ietf-yang-schema-mount.xml

**Error:**
```
[ERR]: LY: Failed to open file "/data/ietf-yang-schema-mount.xml" (No such file or directory)
```

**Root Cause:** The `/data` directory did not exist in the O-CU container because the data volume was not mounted. The netopeer2 server starts with `-x /data/ietf-yang-schema-mount.xml` hardcoded in the supervisord config.

**Fix:** Mount the O-DU data volume when creating the container:
```bash
-v ~/Desktop/TU_Ilmenau/Seminar/oam/solution/network/o-du-o1/data:/data
```

This provides the XML file that netopeer2 needs to initialize.

---

### Problem 8 — curl Cannot Connect to Controller from Mac Terminal

**Error:**
```
curl: (7) Failed to connect to localhost port 8181 after 0 ms: Couldn't connect to server
curl: (6) Could not resolve host: controller
```

**Root Cause:** The ODL controller listens on port 8181 inside the Docker network. From the Mac terminal, `localhost:8181` is not mapped (no port binding in compose file) and `controller` hostname only resolves inside Docker containers.

**Fix:** Run curl or Python requests from inside a container that is on the same Docker network:
```bash
docker exec pynts-o-cu python3 -c "
import urllib.request, json, base64
# ... make requests to http://controller:8181/...
"
```

---

### Problem 9 — SMO Controller Returns HTTP 500 for NETCONF Device Registration

**Error:**
```
HTTP Error: 500
Error body: {"errors": {"error": [{"error-tag": "operation-failed",
"error-message": "Transaction(PUT) not committed correctly"}]}}
```

**Root Cause:** The ODL NETCONF topology API returns 500 when trying to register the O-CU as a NETCONF device. This happens because:
- Port 6513 uses TLS but the controller does not have the O-CU's TLS certificate pre-registered
- The pynts O-CU application crashed on startup and did not auto-register its certificate with the controller (unlike the O-RU which handles this via its mplane extension)

**Workaround:** The O-CU successfully connects to the SMO via the VES plane (HTTP 202 for pnfRegistration). The VES O1 telemetry plane is fully working even without the NETCONF configuration plane connection.

---

### Problem 10 — DHCP Crash on Restart

**Error:**
```
OSError: [Errno 100] Network is down
```

**Root Cause:** The config.py patch is lost every time the container restarts. The unpatched config.py tries to send DHCP packets on tunnel interfaces that are down on Mac Docker.

**Fix:** Re-apply the config.py patch after every restart:
```bash
docker cp /tmp/config.py pynts-o-cu:/app/core/config.py
docker restart pynts-o-cu
```

---

## Commands Reference

### 1. Start O-CU

```bash
docker run -d \
  --name pynts-o-cu \
  --network dcn \
  -e SDNR_RESTCONF_URL=http://controller:8181 \
  -e SDNR_USERNAME=admin \
  -e SDNR_PASSWORD=Kp8bJ4SXszM0WXlhak3eHlcse2gAw84vaoGGmJvUy2U \
  -e VES_URL=http://ves-collector:8080/eventListener/v7 \
  -e VES_USERNAME=sample1 \
  -e VES_PASSWORD=sample1 \
  -e NETCONF_USERNAME=netconf \
  -e NETCONF_PASSWORD=netconf! \
  -e O_DU_CALLHOME_PORT=4336 \
  -v ~/Desktop/TU_Ilmenau/Seminar/oam/solution/network/o-du-o1/data:/data \
  pynts-o-du-o1:latest
```

### 2. Apply config patch

```bash
docker cp /tmp/config.py pynts-o-cu:/app/core/config.py
docker restart pynts-o-cu
```

### 3. Verify O-CU running

```bash
docker ps | grep pynts-o-cu
docker exec pynts-o-cu ss -tlnp
docker exec pynts-o-cu cat /var/log/pynts.log | tail -20
```

### 4. Verify VES events

```bash
docker exec pynts-o-cu cat /var/log/pynts.log | grep "pnfRegistration\|FileReady" | tail -5
docker logs ves-collector --since 1m | grep "276782"
```

### 5. Capture O-CU traffic

```bash
# O-CU → SMO VES traffic
docker exec pynts-o-cu tcpdump -i any port 8080 -v -c 15 2>/dev/null

# Save to pcap
docker exec pynts-o-cu tcpdump -i any port 8080 -w /tmp/ocu_smo.pcap -c 30 2>/dev/null
docker cp pynts-o-cu:/tmp/ocu_smo.pcap ~/Desktop/ocu_smo.pcap
open ~/Desktop/ocu_smo.pcap
```

### 6. Send manual VES event from O-CU

```bash
docker exec pynts-o-cu python3 -c "
import urllib.request, json
event = {
  'event': {
    'commonEventHeader': {
      'domain': 'pnfRegistration',
      'eventId': 'cu-001',
      'eventName': 'pnfRegistration_O-CU',
      'sourceName': 'pynts-o-cu',
      'version': '4.1',
      'vesEventListenerVersion': '7.2.1',
      'reportingEntityName': 'pynts-o-cu',
      'sequence': 0,
      'priority': 'Normal',
      'startEpochMicrosec': 0,
      'lastEpochMicrosec': 0
    },
    'pnfRegistrationFields': {
      'pnfRegistrationFieldsVersion': '2.1',
      'serialNumber': 'O-CU-0001',
      'vendorName': 'O-RAN-SC'
    }
  }
}
data = json.dumps(event).encode()
req = urllib.request.Request(
  'http://ves-collector:8080/eventListener/v7',
  data=data,
  headers={'Content-Type': 'application/json'},
  method='POST'
)
print('O-CU -> SMO Status:', urllib.request.urlopen(req).status)
"
```

### 7. Stop O-CU

```bash
docker rm -f pynts-o-cu
```

---

## 8. Current Status

| Feature | Status | Notes |
|---|---|---|
| O-CU container running | ✅ | pynts-o-du-o1 image with O-DU data volume |
| O-CU → SMO VES pnfRegistration | ✅ | HTTP 202, every restart |
| O-CU → SMO FileReady events | ✅ | Every 60 seconds |
| O-CU NETCONF server (port 6513) | ✅ | netopeer2 running |
| O-CU CallHome (port 4336) | ✅ | Listening |
| O-CU → ODL controller NETCONF | ❌ | HTTP 500, TLS cert not pre-registered |
| O-DU ↔ O-RU sessions | ✅ | Both hybrid and hierarchical active |
| O-DU → SMO VES events | ✅ | FileReady every 60 seconds |

### VES Event Flow Confirmed

```
pynts-o-cu
  ↓ POST /eventListener/v7   HTTP 202 ✅
  domain: pnfRegistration
  domain: stndDefined_PyNTS_FileReady (every 60s)
ves-collector:8080
  ↓ Kafka publish
  topic: unauthenticated.VES_PNFREG_OUTPUT
SMO
```

---

