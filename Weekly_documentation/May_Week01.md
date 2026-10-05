

## Step 1: Update /etc/hosts
The reverse proxy requires fully qualified domain names (FQDNs) to route traffic in O-RAN SC.

You have already added the following entries to `/etc/hosts`:

```text
<YOUR_IP>  smo.o-ran-sc.org
<YOUR_IP>  gateway.smo.o-ran-sc.org
<YOUR_IP>  identity.smo.o-ran-sc.org
<YOUR_IP>  messages.smo.o-ran-sc.org
<YOUR_IP>  odlux.oam.smo.o-ran-sc.org
<YOUR_IP>  flows.oam.smo.o-ran-sc.org
<YOUR_IP>  ves-collector.dcn.smo.o-ran-sc.org
<YOUR_IP>  controller.dcn.smo.o-ran-sc.org
```

Replace `<YOUR_IP>` with your selected LAN IPv4 address (`192.168.67.3` in this setup).

Example:

```text
192.168.67.3  smo.o-ran-sc.org
```

## Step 2: Start the SMO stack layer by layer
The SMO stack consists of several layers: infrastructure, common services, OAM controllers, and application layers.

Start the layers in this order:

```bash
# Layer 1: Infrastructure (Kafka, MariaDB, Keycloak, Traefik)
docker compose -f infra/docker-compose.yaml up -d

# Layer 2: Common services (message router, identity)
docker compose -f smo/common/docker-compose.yaml up -d

# Layer 3: OAM layer (SDN Controller + ODLUX + VES Collector)
docker compose -f smo/oam/docker-compose.yaml up -d

# Layer 4: Applications (optional: Node-RED flows, Wireshark, Jenkins)
docker compose -f smo/apps/docker-compose.yaml up -d
```

Wait 2-3 minutes for all containers to become healthy.

Verify container status:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```



## Step 3 — Build the PyNTS Simulator Images

The simulated O-DU and O-RU images (`pynts-*`) are **not available on any public registry**. They must be built locally from the `sim/o1-ofhmp-interfaces` repository.

### Problem: Image Pull Access Denied

When trying to start the network layer, this error appeared:

```
pull access denied for pynts-o-du-o1, repository does not exist
or may require 'docker login'
```

**Cause:** `LOCAL_DOCKER_REPO` was empty in `network/.env`, meaning Docker looked for the image locally. Since it wasn't built yet, it tried DockerHub and failed.

```env
# network/.env
LOCAL_DOCKER_REPO=       # empty = must be built locally
PYNTS_VERSION=latest
```

---

###  Clone the PyNTS source repository

The `pynts` images come from a **separate repository** from the OAM repo:

```bash
cd ~/Desktop/TU_Ilmenau/Seminar/
git clone "https://gerrit.o-ran-sc.org/r/sim/o1-ofhmp-interfaces"
cd o1-ofhmp-interfaces
ls
```

Repository structure:
```
base/                           ← base image source
o-du-o1/                        ← O-DU image source
o-ru-mplane/                    ← O-RU image source
docker-compose.yaml
docker-compose-o-du-o1.yaml
docker-compose-o-ru-mplane.yaml
Makefile
README.md
```


### Problem: Missing `pynts-base` Dependency

Building `o-du-o1` or `o-ru-mplane` directly failed with:

```
FROM pynts-base:latest
ERROR: pull access denied, repository does not exist
```

**Cause:** Both `o-du-o1` and `o-ru-mplane` Dockerfiles inherit from `pynts-base`. The base image must be built first.

---

###  Build all images in the correct order

Always build from the **root of the `o1-ofhmp-interfaces` repo**:

```bash
cd ~/Desktop/TU_Ilmenau/Seminar/o1-ofhmp-interfaces

# 1. Build base image FIRST (all others depend on this)
docker build -t pynts-base:latest -f base/Dockerfile .

# 2. Build O-DU image
docker build -t pynts-o-du-o1:latest -f o-du-o1/Dockerfile .

# 3. Build O-RU mplane image
docker build -t pynts-o-ru-mplane:latest -f o-ru-mplane/Dockerfile .
```

### Verify all images are built

```bash
docker images | grep pynts
```

Expected output:
```
pynts-base          latest    ...   1.11GB
pynts-o-du-o1       latest    ...   1.16GB
pynts-o-ru-mplane   latest    ...   1.11GB
```

---

## Step 4 — Start the Simulated Network

### Start the O-DU and O-RU containers

```bash
cd ~/Desktop/TU_Ilmenau/Seminar/oam/solution
docker compose -f network/docker-compose.yaml up -d
```

This starts:
- `pynts-o-du-o1` — simulated O-DU
- `pynts-o-ru-hybrid` — simulated O-RU in hybrid mode
- `pynts-o-ru-hierarchical` — simulated O-RU in hierarchical mode

### Verify all containers are running

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Full expected container list:

| Container | Role |
|---|---|
| pynts-o-du-o1 | Simulated O-DU |
| pynts-o-ru-hybrid | Simulated O-RU (hybrid) |
| pynts-o-ru-hierarchical | Simulated O-RU (hierarchical) |
| controller | SMO SDN Controller (ODL) |
| ves-collector | SMO VES event collector |
| flows | Node-RED flow automation |
| wireshark | Traffic capture |
| tests | Jenkins test runner |
| kafka-bridge | Kafka REST bridge |
| kafka | Message broker |
| identity | Keycloak identity service |
| zookeeper | Kafka coordination |
| gateway | Traefik reverse proxy |
| persistence | MariaDB database |
| identitydb | PostgreSQL for Keycloak |
| topology | Topology service |

---

## Step 5 — Connect O-DU to SMO

###  Restart O-DU to trigger pnfRegistration

The first VES message is often lost due to a known Kafka issue. Restarting the O-DU forces a fresh `pnfRegistration` event:

```bash
docker restart pynts-o-du-o1
```

###  Verify O-DU is connected via RESTCONF

```bash
curl -u admin:Kp8bJ4SXszM0WXlhak3eHlcse2gAw84vaoGGmJvUy2U \
  http://localhost:8181/rests/data/network-topology:network-topology/topology=topology-netconf \
  -H "Accept: application/json" | python3 -m json.tool
```

Look for:
```json
"netconf-node-topology:connection-status": "connected"
```

### Check ODLUX dashboard

Open in browser: `https://odlux.oam.smo.o-ran-sc.org`

Navigate to **"Connect"** in the left sidebar — the O-DU should appear as connected.

---

## Step 6 — Monitor SMO ↔ O-DU Communication

### Watch VES events (O-DU → SMO direction)

```bash
docker logs -f ves-collector
```

Expected events:
- `pnfRegistration` — O-DU registers itself with SMO on startup
- `heartbeat` — periodic keepalive messages
- `fault` — fault notifications

### Watch NETCONF logs (SMO → O-DU direction)

```bash
docker exec -it controller tail -f /opt/opendaylight/data/log/karaf.log
```

Filter for O-DU specific messages:

```bash
docker exec -it controller tail -f /opt/opendaylight/data/log/karaf.log \
  | grep -i "pynts-o-du\|netconf\|mount\|connected"
```

### Capture raw traffic with Wireshark

Access in browser: `http://localhost:3000`

Or capture via tcpdump on host:

```bash
# NETCONF CallHome traffic
sudo tcpdump -i docker0 -w /tmp/smo_odu.pcap port 4335 or port 830

# VES HTTP traffic
sudo tcpdump -i docker0 -w /tmp/ves.pcap port 8443
```

---

## Step 7 — Test Configuration Management (SMO → O-DU)

### Send a configuration change to O-DU via SMO

```bash
curl -u admin:Kp8bJ4SXszM0WXlhak3eHlcse2gAw84vaoGGmJvUy2U \
  -X PUT \
  "http://localhost:8181/rests/data/network-topology:network-topology/topology=topology-netconf/node=pynts-o-du-o1/yang-ext:mount/o-ran-sc-du-hello-world:network-function/du-to-ru-connection=O-RU-1" \
  -H "Content-Type: application/json" \
  -d '{"du-to-ru-connection":[{"name":"O-RU-1","administrative-state":"UNLOCKED"}]}'
```

A successful response (HTTP 200/204) confirms the SMO successfully pushed configuration to the O-DU via the O1 NETCONF interface.

---

## Communication Flow Summary

```
┌─────────────────────────────────────┐
│              SMO Stack              │
│  ┌──────────┐    ┌───────────────┐  │
│  │controller│    │ ves-collector │  │
│  │  (ODL)   │    │  (HTTP/VES)   │  │
│  └────┬─────┘    └───────▲───────┘  │
└───────┼──────────────────┼──────────┘
        │ NETCONF/O1       │ VES/HTTP
        │ (port 4335/830)  │ (port 8443)
        ▼                  │
┌───────────────────────────────────┐
│         pynts-o-du-o1             │
│      (Simulated O-DU)             │
└───────────────────────────────────┘
```

| Direction | Protocol | Port | Content |
|---|---|---|---|
| O-DU → SMO | HTTP/VES | 8443 | pnfRegistration, heartbeat, faults |
| SMO → O-DU | NETCONF SSH | 830 | get-config, edit-config |
| O-DU → SMO | NETCONF CallHome | 4335 | O-DU initiates connection |

---

## Useful Commands Reference

```bash
# Check all container statuses
docker ps --format "table {{.Names}}\t{{.Status}}"

# Check O-DU logs
docker logs -f pynts-o-du-o1

# Check VES collector (incoming events from O-DU)
docker logs -f ves-collector

# Check SMO controller NETCONF sessions
docker exec -it controller tail -f /opt/opendaylight/data/log/karaf.log

# Restart O-DU (triggers fresh pnfRegistration)
docker restart pynts-o-du-o1

# Stop the network only (keep SMO running)
docker compose -f network/docker-compose.yaml down

# Stop everything
docker compose -f network/docker-compose.yaml down
docker compose -f smo/apps/docker-compose.yaml down
docker compose -f smo/oam/docker-compose.yaml down
docker compose -f smo/common/docker-compose.yaml down
docker compose -f infra/docker-compose.yaml down
```

---





## Phase 3 — Problem: O-DU Not Sending Events to VES Collector
 
### Symptom
VES collector logs were stuck at April 26 — no new events appearing even after O-DU containers started.
 
### Diagnosis
 
**Step 1: Checked if O-DU was running:**
```bash
docker ps | grep pynts
```
All three pynts containers were `Up` and running.
 
**Step 2: Checked O-DU internal logs:**
```bash
docker logs pynts-o-du-o1 --tail 50
```
All 4 internal services started successfully:
- `netopeer2-server` ✅
- `pynts` ✅
- `sshd` ✅
- `vsftpd` ✅
**Step 3: Checked the VES URL the O-DU was using:**
```bash
docker inspect pynts-o-du-o1 | grep -A5 "VES_URL"
```
 
Output revealed the problem:
```
VES_URL=https://ves-collector.dcn.192.168.0.104/eventListener/v7
```
 
**Step 4: Checked network connectivity:**
```bash
docker inspect pynts-o-du-o1 | grep -A10 "Networks"
docker inspect ves-collector | grep -A10 "Networks"
```
Both containers were on the same `dcn` network — connectivity was fine.
 
### Root Cause
 
The O-DU was trying to reach VES collector via **HTTPS** on a domain name, but the VES collector runs on **plain HTTP port 8080**. This was confirmed directly from the VES collector startup logs:
 
```
"Application work in noAuth mode on 8080 port."
"Tomcat initialized with port(s): 8080 (http)"
"Initializing ProtocolHandler ["http-nio-8080"]"
```
 
The VES URL in `network/.env` was incorrectly set to use HTTPS and a domain-based URL that resolved outside the Docker network.
 
### Fix
 
Edit `network/.env`:
 
```bash
nano ~/Desktop/TU_Ilmenau/Seminar/oam/solution/network/.env
```
 
Change:
```env
# Wrong - HTTPS with domain name
VES_URL=https://ves-collector.dcn.${HTTP_DOMAIN}/eventListener/v7
```
 
To:
```env
# Correct - HTTP with Docker container name
VES_URL=http://ves-collector:8080/eventListener/v7
```
 
---
 
## Phase 4 — Applying the Fix
 
### Problem: `docker compose up -d` Did Not Recreate Containers
 
After editing the `.env` file, running:
```bash
docker compose -f network/docker-compose.yaml up -d
```
Showed all containers as `Running` instead of `Started` — the new env variable was NOT picked up.
 
**Solution:** Use `--force-recreate` flag to tear down and rebuild containers:
 
```bash
docker compose -f network/docker-compose.yaml up -d --force-recreate
```
 
This time all three containers showed `Started`, confirming the new `VES_URL` was applied.
 
### Verify the new URL was applied
 
```bash
docker exec pynts-o-du-o1 env | grep VES_URL
```
 
Expected output:
```
VES_URL=http://ves-collector:8080/eventListener/v7
```
 
---
 
## Phase 5 — Verifying Network Connectivity
 
### Test connectivity from O-DU to VES Collector
 
```bash
docker exec pynts-o-du-o1 python3 -c "
import urllib.request
try:
    r = urllib.request.urlopen('http://ves-collector:8080/eventListener/v7')
    print('Connected! Status:', r.status)
except Exception as e:
    print('Failed:', e)
"
```
 
**Result:**
```
Failed: HTTP Error 405:
```
 
**Interpretation:** HTTP 405 = "Method Not Allowed" — this is **NOT a failure**. It means:
- The O-DU successfully reached the VES collector ✅
- The server responded (connection works) ✅
- Error 405 only means GET is not allowed — VES only accepts POST requests
- The network path between O-DU and VES collector is fully working ✅
---
 
## Phase 6 — Sending a Test VES Event
 
To manually trigger and verify full end-to-end communication, a `pnfRegistration` event was sent directly from the O-DU container:
 
```bash
docker exec pynts-o-du-o1 python3 -c "
import urllib.request, json
 
event = {
  'event': {
    'commonEventHeader': {
      'domain': 'pnfRegistration',
      'eventId': 'test-001',
      'eventName': 'pnfRegistration_O-DU',
      'sourceName': 'pynts-o-du-o1',
      'version': '4.1',
      'vesEventListenerVersion': '7.2.1',
      'reportingEntityName': 'pynts-o-du-o1',
      'sequence': 0,
      'priority': 'Normal',
      'startEpochMicrosec': 0,
      'lastEpochMicrosec': 0
    },
    'pnfRegistrationFields': {
      'pnfRegistrationFieldsVersion': '2.1',
      'serialNumber': 'O-DU-1122',
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
try:
  r = urllib.request.urlopen(req)
  print('SUCCESS! Status:', r.status)
except Exception as e:
  print('Response:', e)
"
```
 
**Result:**
```
SUCCESS! Status: 202
```
 
HTTP 202 = Accepted. The VES collector received and accepted the pnfRegistration event from the O-DU.
 
---
 
## Phase 7 — Confirmed End-to-End Communication
 
### VES Collector Log After Receiving Event
 
```
[2026-04-29 14:58:11] pnfRegistration == event.commonEventHeader.domain
[2026-04-29 14:58:11] Sending a batch of 1 items for topic unauthenticated.VES_PNFREG_OUTPUT to kafka
[2026-04-29 14:58:12] Sent a batch of 1 items for topic unauthenticated.VES_PNFREG_OUTPUT to kafka
[2026-04-29 14:58:12] Successfully send event to MR
```
 
### Complete Communication Chain Verified
 
```
┌─────────────────────────────────────────────┐
│              pynts-o-du-o1                  │
│         (Simulated O-DU)                    │
└──────────────┬──────────────────────────────┘
               │
               │ HTTP POST /eventListener/v7
               │ domain: pnfRegistration
               │ Status: 202 Accepted
               ▼
┌─────────────────────────────────────────────┐
│           ves-collector:8080                │
│      (SMO VES Event Collector)              │
└──────────────┬──────────────────────────────┘
               │
               │ Kafka publish
               │ topic: unauthenticated.VES_PNFREG_OUTPUT
               ▼
┌─────────────────────────────────────────────┐
│              kafka:9092                     │
│         (Message Broker)                    │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│           SMO Controller (ODL)              │
│      (OpenDaylight SDN Controller)          │
└─────────────────────────────────────────────┘
```
 
# Wireshark Setup Guide — Capturing O-DU ↔ SMO Communication

This document covers the complete process of setting up the containerized Wireshark instance to capture and display live traffic between the simulated O-DU (`pynts-o-du-o1`) and the SMO (`ves-collector`) over the O1 interface.

---

## Architecture Overview

The Wireshark container is part of the OAM `smo/apps` stack. It runs a full desktop GUI streamed via WebRTC/WebSocket to the browser using the **Selkies** framework.

```
Browser (localhost:3000)
        ↕ WebSocket stream
Wireshark Container
        ↕ captures traffic on eth1
dcn Docker Network (172.21.0.0/16)
        ↕
O-DU (172.21.0.5) ←→ VES Collector (172.21.0.3)
```

---

## Phase 1 — Fixing the Docker Compose File

### Problem 1: `network_mode: host` with commented ports

The original `smo/apps/docker-compose.yaml` had Wireshark configured with `network_mode: host` and all ports commented out:

```yaml
# Original (broken on Mac)
wireshark:
  network_mode: host
  # ports:
  #   - 3000:3000
```

**Why this fails on Mac:** Docker Desktop on Mac runs containers inside a Linux VM. `network_mode: host` gives the container access to the VM's network, not the Mac's network. Ports are not accessible from the Mac browser.

### Problem 2: `ports` and `network_mode: host` cannot coexist

When trying to uncomment ports while keeping `network_mode: host`, Docker Compose throws:
```
yaml: line 66: did not find expected key
```

`network_mode: host` and `ports` are **mutually exclusive** in Docker Compose.

### Problem 3: YAML indentation errors

Incorrect indentation of `networks` block caused:
```
yaml: line 66: did not find expected key
```

YAML requires consistent 2-space indentation for each level.

### Problem 4: `dcn` network undefined in apps compose file

Adding `dcn` to wireshark networks caused:
```
service "wireshark" refers to undefined network dcn: invalid compose project
```

The `dcn` network is only defined in `infra/docker-compose.yaml`, not in `smo/apps/docker-compose.yaml`.

---

### Fix — Correct Wireshark Service Configuration

Edit `smo/apps/docker-compose.yaml` and replace the wireshark service with:

```yaml
  wireshark:
    image: "${WIRESHARK_IMAGE}"
    container_name: wireshark
    cap_add:
      - NET_ADMIN
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Etc/UTC
    volumes:
      - ./wireshark:/config
    ports:
      - "3000:3000"
      - "3001:3001"
      - "8082:8082"
    networks:
      dmz:
    restart: unless-stopped
```

Key changes:
- Removed `network_mode: host`
- Added explicit `ports` mapping
- Only added `dmz` network (not `dcn` — that's added manually later)

---

### Recreate the Wireshark container

```bash
docker stop wireshark && docker rm wireshark
docker compose -f smo/apps/docker-compose.yaml up -d wireshark
```

Verify it started:
```bash
docker ps | grep wireshark
```

---

## Phase 2 — Accessing Wireshark in Browser

The Wireshark container runs on port **3000** (Selkies web interface):

```
http://localhost:3000
```

Open this URL in your browser. You will see a full Linux desktop with Wireshark running inside it.

**Wireshark web interface ports:**
| Port | Purpose |
|---|---|
| 3000 | Main browser GUI (Selkies desktop stream) |
| 3001 | Second screen |
| 8082 | WebSocket data channel |

---

## Phase 3 — Connecting Wireshark to the O-DU Network

### Problem: Wireshark only on `dmz` network, O-DU traffic on `dcn` network

By default Wireshark was only connected to `dmz`. The O-DU and VES collector communicate on the `dcn` network (`172.21.0.0/16`). Wireshark could not see this traffic.

**Network layout:**

| Container | Network | IP |
|---|---|---|
| pynts-o-du-o1 | dcn | 172.21.0.5 |
| ves-collector | dcn | 172.21.0.3 |
| wireshark | dmz only | 172.20.0.8 |

### Fix — Connect Wireshark to the dcn network

```bash
docker network connect dcn wireshark
```

Verify it joined:
```bash
docker exec wireshark ip addr show | grep "inet "
```

Expected output showing both interfaces:
```
inet 172.20.0.8/16  ...  eth0   ← dmz network
inet 172.21.0.8/16  ...  eth1   ← dcn network (O-DU traffic)
```

---

## Phase 4 — Identifying the Correct Capture Interface

### Check routing table inside Wireshark container

```bash
docker exec wireshark ip route
```

Output:
```
default via 172.21.0.1 dev eth1
172.20.0.0/16 dev eth0 scope link src 172.20.0.8
172.21.0.0/16 dev eth1 scope link src 172.21.0.8
```

### Conclusion

| Interface | Network | IP Range | Contains O-DU Traffic |
|---|---|---|---|
| eth0 | dmz | 172.20.0.0/16 | ❌ No |
| eth1 | dcn | 172.21.0.0/16 | ✅ Yes |

**Always capture on `eth1`** to see O-DU ↔ SMO traffic.

---

## Phase 5 — Capturing O-DU ↔ SMO Traffic in Wireshark

### Step 1: Open Wireshark in browser
```
http://localhost:3000
```

### Step 2: Select `eth1` interface
1. In Wireshark, click **Capture → Options** (`Ctrl+K`)
2. Uncheck all interfaces
3. Check only **`eth1`**
4. Click **Start**

### Step 3: Apply display filter
In the filter bar at the top type:
```
tcp.port == 8080
```
Or for more specific O-DU ↔ VES filter:
```
ip.addr == 172.21.0.5 and ip.addr == 172.21.0.3
```

### Step 4: Send a test VES event from O-DU

```bash
docker exec pynts-o-du-o1 python3 -c "
import urllib.request, json

event = {
  'event': {
    'commonEventHeader': {
      'domain': 'heartbeat',
      'eventId': 'hb-001',
      'eventName': 'heartbeat_O-DU',
      'sourceName': 'pynts-o-du-o1',
      'version': '4.1',
      'vesEventListenerVersion': '7.2.1',
      'reportingEntityName': 'pynts-o-du-o1',
      'sequence': 0,
      'priority': 'Normal',
      'startEpochMicrosec': 0,
      'lastEpochMicrosec': 0
    },
    'heartbeatFields': {
      'heartbeatFieldsVersion': '3.0',
      'heartbeatInterval': 20
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
print('Status:', urllib.request.urlopen(req).status)
"
```

### Step 5: View the captured packets

You should see packets like:
```
No.   Time     Source              Destination         Protocol  Info
2449  11.208   2001:db8:1:50::5   2001:db8:1:50::3   TCP       40272 → 8080 [SYN]
2450  11.209   2001:db8:1:50::3   2001:db8:1:50::5   TCP       8080 → 40272 [SYN ACK]
2451  11.210   2001:db8:1:50::5   2001:db8:1:50::3   HTTP      POST /eventListener/v7
2452  11.211   2001:db8:1:50::3   2001:db8:1:50::5   HTTP      HTTP/1.1 202 Accepted
```

### Step 6: View full JSON payload
Right-click on the HTTP POST packet → **Follow → TCP Stream**

This shows the complete O-DU → SMO HTTP conversation including the full JSON VES event body.

---

## Phase 6 — Troubleshooting

### Problem: "Promiscuous mode not supported on the 'any' device"
**Solution:** Do not select `any`. Select `eth1` specifically.

### Problem: Packets captured but 0 displayed
```
Packets: 4916 · Displayed: 0 (0.0%)
```
**Solution:** The display filter is too strict. Clear the filter bar completely and press Enter. All packets will appear.

### Problem: Filter shows no packets even on eth1
**Solution:** The traffic uses **IPv6** addresses (`2001:db8:1:50::x`) on the `dcn` network. Use this filter instead:
```
tcp.port == 8080
```

### Problem: Wireshark running but no traffic visible at all
**Solution:** Verify Wireshark is on the `dcn` network:
```bash
docker inspect wireshark | grep -A5 "Networks"
```
If `dcn` is not listed, run:
```bash
docker network connect dcn wireshark
```

### Problem: Cannot ping O-DU from Wireshark
```bash
docker exec wireshark ping -c 3 pynts-o-du-o1
```
If this fails, the containers are not on the same network. Connect Wireshark to `dcn` as above.

---

## Verified Capture Result

The following was confirmed captured in Wireshark:

```
Frame 2449: 94 bytes on wire, captured on interface eth1
  Source:      2001:db8:1:50::5  (pynts-o-du-o1 / O-DU)
  Destination: 2001:db8:1:50::3  (ves-collector / SMO)
  Protocol:    TCP → HTTP
  Dst Port:    8080
  Type:        [SYN] — TCP connection initiation
  Timestamp:   May 1, 2026 23:26:36 UTC
```

This confirms the **O-DU successfully initiates a TCP connection to the SMO VES collector** and sends VES events over HTTP on port 8080.

---

## Quick Reference Commands

```bash
# Connect Wireshark to dcn network
docker network connect dcn wireshark

# Check Wireshark network interfaces
docker exec wireshark ip addr show

# Check routing table
docker exec wireshark ip route

# Verify connectivity between Wireshark and O-DU
docker exec wireshark ping -c 3 pynts-o-du-o1

# Send test heartbeat event from O-DU
docker exec pynts-o-du-o1 python3 -c "
import urllib.request, json
event = {'event': {'commonEventHeader': {'domain': 'heartbeat', 'eventId': 'hb-001', 'eventName': 'heartbeat_O-DU', 'sourceName': 'pynts-o-du-o1', 'version': '4.1', 'vesEventListenerVersion': '7.2.1', 'reportingEntityName': 'pynts-o-du-o1', 'sequence': 0, 'priority': 'Normal', 'startEpochMicrosec': 0, 'lastEpochMicrosec': 0}, 'heartbeatFields': {'heartbeatFieldsVersion': '3.0', 'heartbeatInterval': 20}}}
data = json.dumps(event).encode()
req = urllib.request.Request('http://ves-collector:8080/eventListener/v7', data=data, headers={'Content-Type': 'application/json'}, method='POST')
print('Status:', urllib.request.urlopen(req).status)
"

# Send test pnfRegistration event from O-DU
docker exec pynts-o-du-o1 python3 -c "
import urllib.request, json
event = {'event': {'commonEventHeader': {'domain': 'pnfRegistration', 'eventId': 'reg-001', 'eventName': 'pnfRegistration_O-DU', 'sourceName': 'pynts-o-du-o1', 'version': '4.1', 'vesEventListenerVersion': '7.2.1', 'reportingEntityName': 'pynts-o-du-o1', 'sequence': 0, 'priority': 'Normal', 'startEpochMicrosec': 0, 'lastEpochMicrosec': 0}, 'pnfRegistrationFields': {'pnfRegistrationFieldsVersion': '2.1', 'serialNumber': 'O-DU-1122', 'vendorName': 'O-RAN-SC'}}}
data = json.dumps(event).encode()
req = urllib.request.Request('http://ves-collector:8080/eventListener/v7', data=data, headers={'Content-Type': 'application/json'}, method='POST')
print('Status:', urllib.request.urlopen(req).status)
"

# Open Wireshark in browser
open http://localhost:3000
```

---

## Wireshark Display Filters Reference

| Filter | Shows |
|---|---|
| `tcp.port == 8080` | All VES HTTP traffic |
| `ip.addr == 172.21.0.5 and ip.addr == 172.21.0.3` | Only O-DU ↔ VES collector |
| `http` | All HTTP traffic |
| `tcp.port == 830` | NETCONF SSH traffic |
| `tcp.port == 4335` | NETCONF CallHome |
| `tcp.flags.syn == 1` | TCP connection initiations only |

 
## Key Commands Reference
 
```bash
# Start network containers
docker compose -f network/docker-compose.yaml up -d
 
# Force recreate containers to apply env changes
docker compose -f network/docker-compose.yaml up -d --force-recreate
 
# Check O-DU environment variables
docker exec pynts-o-du-o1 env | grep VES_URL
 
# Check O-DU internal processes
docker exec pynts-o-du-o1 ps aux
 
# Watch VES collector for incoming events (new only)
docker logs ves-collector --since 5m -f
 
# Watch VES collector all logs
docker logs ves-collector
 
# Check O-DU logs
docker logs pynts-o-du-o1 --tail 50
 
# Check all container statuses
docker ps --format "table {{.Names}}\t{{.Status}}"
 
# Test connectivity from O-DU to VES collector
docker exec pynts-o-du-o1 python3 -c "
import urllib.request
try:
    r = urllib.request.urlopen('http://ves-collector:8080/eventListener/v7')
    print('Connected! Status:', r.status)
except Exception as e:
    print('Failed:', e)
"
```

## ------------------  Commands Reference ------------------

### Show all addresses
```bash
hostname -I
```

### Show IPv4 addresses only
```bash
ip -4 addr show
```

### Confirm the active outbound IPv4
```bash
ip route get 8.8.8.8
```
Look for:
```text
src <your-ip>
```

```bash
# Check all container statuses
docker ps --format "table {{.Names}}\t{{.Status}}"

# Watch controller NETCONF logs
docker exec -it controller tail -f /opt/opendaylight/data/log/karaf.log

# Watch VES events from O-DU
docker logs -f ves-collector

# Check O-DU connection status via RESTCONF
curl -u admin:Kp8bJ4SXszM0WXlhak3eHlcse2gAw84vaoGGmJvUy2U \
  http://localhost:8181/rests/data/network-topology:network-topology/topology=topology-netconf \
  -H "Accept: application/json" | python3 -m json.tool

# Check docker networks
docker network ls

# Inspect container health
docker inspect <container_name> | grep -A10 "Health"
```


## ------------------------------- Troubleshooting -------------------------------


### Problem 1 — Docker Compose YAML Invalid Boolean Types

**Problem:**
```
ERROR: The Compose file './smo/common/docker-compose.yaml' is invalid because:
services.identitydb.environment.ALLOW_EMPTY_PASSWORD contains false, which is an invalid type,
it should be a string, number, or a null
services.identity.environment.KEYCLOAK_CREATE_ADMIN_USER contains true, which is an invalid type,
it should be a string, number, or a null

```

**Cause:**
Docker Compose requires boolean values to be quoted as strings. Raw `true`/`false` YAML booleans are not accepted in the `environment` section.

**Solution:**
```bash
# Fix smo/common/docker-compose.yaml
sed -i 's/ALLOW_EMPTY_PASSWORD: false/ALLOW_EMPTY_PASSWORD: "false"/' ./smo/common/docker-compose.yaml

```

Or manually edit the files and wrap booleans in quotes:
```yaml
# Wrong
ALLOW_EMPTY_PASSWORD: false

# Correct
ALLOW_EMPTY_PASSWORD: "false"
```



### Problem 2 — Controller Container Architecture Mismatch (ARM64 vs AMD64)

**Problem:**
```
The requested image's platform (linux/amd64) does not match the detected host
platform (linux/arm64/v8) and no specific platform was requested
dependency failed to start: container controller is unhealthy
```

**Cause:**
Running on Apple Silicon (M1/M2/M3) Mac (ARM64), but the controller image (`sdnr-image`) is only built for `linux/amd64`. Rosetta alone is not sufficient — Docker must be explicitly told to emulate.

**Solution:**

Step 1 — Enable Rosetta emulation in Docker Desktop:
- Open Docker Desktop → Settings → General
- Enable **"Use Rosetta for x86/amd64 emulation on Apple Silicon"**
- Click Apply & Restart

Step 2 — Add `platform` to the controller service in `smo/oam/docker-compose.yaml`:
```yaml
services:
  controller:
    platform: linux/amd64
    image: ...
```

Step 3 — Or set the default platform globally before running:
```bash
export DOCKER_DEFAULT_PLATFORM=linux/amd64
docker compose -f smo/oam/docker-compose.yaml up -d
```

Step 4 — If health checks fail due to slow emulation, increase timeouts:
```yaml
healthcheck:
  timeout: 60s
  retries: 15
  start_period: 300s
```

---

### Problem 3 — Controller Container Stuck on HTTP 401 / Certificate Installation Loop

**Problem:**
The controller container kept looping indefinitely with:
```
Certificate installation in progress. Elapsed time - Xs. Waiting for 10 secs...
Problem code was: 401
TIME OUT: Healthcheck not passed in 1000 seconds...
Stopping SDNR container due to failure in installing Certificates
Killed
```

**Root Cause:**
The environment variable `SDNC_ENABLE_OAUTH=true` was set in `smo/oam/.env`. This enabled OAuth/Keycloak authentication for the certificate installer script, which was then trying to authenticate against Keycloak before reaching the ODL REST API — and failing with 401 every time.

**Diagnosis steps:**
```bash
# Check if identity (Keycloak) is healthy
docker ps | grep identity

# Check OAuth setting in .env
grep OAUTH smo/oam/.env

# Check controller logs for the actual error
docker logs -f controller
```

**Solution:**
Disable OAuth in the `smo/oam/.env` file:

```bash
sed -i 's/SDNC_ENABLE_OAUTH=true/SDNC_ENABLE_OAUTH=false/' smo/oam/.env

# Verify the change
grep OAUTH smo/oam/.env
# Should output: SDNC_ENABLE_OAUTH=false
```

Then remove the dead container and restart:
```bash
docker rm -f controller
docker compose -f smo/oam/docker-compose.yaml up -d controller
docker logs -f controller
```

**Expected successful output:**
```
Certificate installation script completed execution
```

And after a few minutes:
```bash
docker ps | grep controller
# Shows: Up X minutes (healthy)











# O-RU ↔ O-DU ↔ SMO Connection Guide

This document covers the complete process of connecting the simulated O-RU to the O-DU and verifying the full O-RU ↔ O-DU ↔ SMO communication chain in the NTS simulation environment.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    SMO Stack                            │
│  ┌──────────────────┐    ┌───────────────────────────┐  │
│  │   controller     │    │      ves-collector        │  │
│  │ (ODL) port:8181  │    │    (VES) port:8080        │  │
│  └────────┬─────────┘    └──────────────┬────────────┘  │
└───────────┼──────────────────────────────┼──────────────┘
            │ NETCONF CallHome             │ VES/HTTP
            │ HTTP REST (cert mgmt)        │ (events)
            ▼                             ▲
┌───────────────────────────────────────────────────────┐
│                  pynts-o-du-o1                        │
│               (Simulated O-DU)                        │
│            IP: 172.21.0.5 / 2001:db8:1:50::5         │
└──────┬────────────────────────────────┬───────────────┘
       │ NETCONF TLS Session            │ NETCONF TLS Session
       ▼                                ▼
┌─────────────────┐          ┌──────────────────────────┐
│ pynts-o-ru-     │          │ pynts-o-ru-              │
│ hybrid          │          │ hierarchical             │
│ 2001:db8:1:50   │          │ 2001:db8:1:50::6         │
│ ::7             │          │                          │
└─────────────────┘          └──────────────────────────┘
```

---

## Container Overview

| Container | Role | IP |
|---|---|---|
| pynts-o-du-o1 | Simulated O-DU | 172.21.0.5 / 2001:db8:1:50::5 |
| pynts-o-ru-hybrid | Simulated O-RU (hybrid mode) | 2001:db8:1:50::7 |
| pynts-o-ru-hierarchical | Simulated O-RU (hierarchical mode) | 2001:db8:1:50::6 |
| controller | SMO SDN Controller (ODL) | port 8181 |
| ves-collector | SMO VES Event Collector | port 8080 |

---

## Phase 1 — Verifying O-RU and O-DU are Running

### Step 1: Check all pynts containers

```bash
docker ps | grep pynts
```

Expected output:
```
pynts-o-ru-hierarchical   Up X hours   830/tcp
pynts-o-du-o1             Up X hours   830/tcp
pynts-o-ru-hybrid         Up X hours   830/tcp
```

### Step 2: Check O-RU and O-DU internal logs

```bash
docker logs pynts-o-ru-hybrid --tail 30
docker logs pynts-o-du-o1 --tail 30
```

All four services should show `RUNNING` state:
- `netopeer2-server`
- `pynts`
- `sshd`
- `vsftpd`

---

## Phase 2 — Problems Encountered and Solutions

### Problem 1: DHCP Failure — `OSError: [Errno 100] Network is down`

**Symptom:**
```
OSError: [Errno 100] Network is down
Could not determine macvlan or bridge network interfaces. Exiting.
```

**Root Cause:** The PyNTS application tries to get its IP configuration via DHCP on startup using a macvlan network interface. On Mac with Docker Desktop, macvlan networking is not supported. The DHCP server in `infra/docker-compose.yaml` uses macvlan which fails with:

```
failed to create network dhcp: invalid subinterface vlan name en0
```

The pynts application crashes during initialization because it tries to send DHCP packets on tunnel interfaces (`tunl0`, `gre0`, etc.) that are in DOWN state.

**Solution:** Patch the `config.py` inside the containers to skip all virtual/tunnel interfaces:

```bash
# Copy config.py out of container
docker cp pynts-o-ru-hybrid:/app/core/config.py /tmp/config.py

# Patch to skip tunnel interfaces (Mac uses sed -i '' not sed -i)
sed -i '' "s/if iface == 'lo':/if iface in ['lo', 'tunl0', 'gre0', 'gretap0', 'erspan0', 'ip_vti0', 'ip6_vti0', 'sit0', 'ip6tnl0', 'ip6gre0']:/" /tmp/config.py

# Verify the patch
grep -n "if iface in" /tmp/config.py

# Copy patched file back to all three containers
docker cp /tmp/config.py pynts-o-ru-hybrid:/app/core/config.py
docker cp /tmp/config.py pynts-o-ru-hierarchical:/app/core/config.py
docker cp /tmp/config.py pynts-o-du-o1:/app/core/config.py

# Restart containers
docker restart pynts-o-ru-hybrid pynts-o-ru-hierarchical pynts-o-du-o1
```

**Important:** This patch is lost every time the container is recreated with `--force-recreate`. Always re-apply after recreating containers.

**Permanent fix** — add a volume mount in `network/docker-compose.yaml`:
```yaml
volumes:
  - /tmp/config.py:/app/core/config.py
```

---

### Problem 2: O-RU Cannot Connect to SMO Controller — `Connection refused`

**Symptom:**
```
HTTPSConnectionPool(host='controller.dcn.192.168.0.104', port=443):
Max retries exceeded: [Errno 111] Connection refused
```

**Root Cause:** The O-RU was trying to reach the SMO controller at `https://controller.dcn.192.168.0.104:443` — a domain-based HTTPS URL that doesn't resolve inside Docker. The controller is accessible as `controller` on port `8181`.

**Solution:** Update `SDNR_RESTCONF_URL` in `network/.env`:

```bash
nano ~/Desktop/TU_Ilmenau/Seminar/oam/solution/network/.env
```

Change:
```env
# Wrong
SDNR_RESTCONF_URL=https://controller.dcn.${HTTP_DOMAIN}

# Correct
SDNR_RESTCONF_URL=http://controller:8181
```

---

### Problem 3: SSL Error After URL Fix — `WRONG_VERSION_NUMBER`

**Symptom:**
```
SSLError: [SSL: WRONG_VERSION_NUMBER] wrong version number
HTTPSConnectionPool(host='controller', port=8181)
```

**Root Cause:** After fixing the hostname, the URL was still `https://` but port 8181 speaks plain HTTP. The SSL handshake failed.

**Solution:** Ensure the URL uses `http://` not `https://`:

```env
SDNR_RESTCONF_URL=http://controller:8181
```

---

## Phase 3 — O-DU ↔ O-RU Connection

The O-RU connects to the O-DU via **NETCONF TLS CallHome** on port **4335**. This is configured in the O-RU data file:

```json
{
  "call-home": {
    "netconf-client": [{
      "name": "default-odu-tls",
      "endpoints": {
        "endpoint": [{
          "tls": {
            "tcp-client-parameters": {
              "remote-address": "pynts-o-du-o1",
              "remote-port": 4335
            }
          }
        }]
      }
    }]
  }
}
```

The O-RU initiates a TLS CallHome connection to the O-DU on port 4335. The O-DU accepts and maintains the session.

### Verifying O-DU ↔ O-RU Sessions

```bash
docker exec pynts-o-du-o1 cat /var/log/pynts.log | grep "Session" | tail -10
```

Expected output confirming both O-RUs are connected:
```
Session 1 with pynts-o-ru-hybrid ('2001:db8:1:50::7', 54364, 0, 0) is still active
Session 2 with pynts-o-ru-hierarchical ('2001:db8:1:50::6', 54634, 0, 0) is still active
```

---

## Phase 4 — O-RU ↔ SMO Controller Connection

The O-RU registers itself with the SMO controller by:

1. Removing its old TLS certificate from the controller keystore
2. Adding its new TLS certificate to the controller keystore
3. Adding itself to the controller allowed devices list for NETCONF CallHome

### Verifying O-RU to SMO Registration

```bash
docker exec pynts-o-ru-hybrid cat /var/log/pynts.log | grep -i "succeeded\|201\|204" | tail -10
```

Expected successful output:
```
HTTP response to .../netconf-keystore:remove-trusted-certificate succeeded with code 204
HTTP response to .../netconf-keystore:add-trusted-certificate succeeded with code 204
HTTP response to .../allowed-devices/device=pynts-o-ru-hybrid succeeded with code 201
```

| HTTP Code | Meaning |
|---|---|
| 204 | Success — certificate operation completed |
| 201 | Created — O-RU added to allowed devices list |

---

## Phase 5 — O-DU Sending Events to SMO

The O-DU automatically sends performance management events to the VES collector every minute:

```bash
docker exec pynts-o-du-o1 cat /var/log/pynts.log | grep "ves\|POST" | tail -10
```

Example VES event being sent:
```
POST http://ves-collector:8080/eventListener/v7
domain: stndDefined
eventName: stndDefined_PyNTS_FileReady
fileLocation: sftp://netconf:netconf!@172.21.0.5:22/ftp/A20260503.xml
```

These are 3GPP Performance Assurance file-ready notifications.

---

## Full Connection Verification Commands

```bash
# Check all pynts containers running
docker ps | grep pynts

# Check O-DU active sessions with both O-RUs
docker exec pynts-o-du-o1 cat /var/log/pynts.log | grep "Session" | tail -5

# Check O-RU SMO registration success
docker exec pynts-o-ru-hybrid cat /var/log/pynts.log | grep "succeeded" | tail -5
docker exec pynts-o-ru-hierarchical cat /var/log/pynts.log | grep "succeeded" | tail -5

# Check O-DU VES events to SMO
docker exec pynts-o-du-o1 cat /var/log/pynts.log | grep "ves\|POST" | tail -5

# Check VES collector receiving events
docker logs ves-collector --since 5m | grep "domain\|Successfully"

# Check NETCONF server logs
docker exec pynts-o-du-o1 cat /var/log/netopeer2-server.log | tail -20
docker exec pynts-o-ru-hybrid cat /var/log/netopeer2-server.log | tail -20
```

---

## After Every Container Restart — Required Steps

Since the config.py patch is lost on container recreation, always run these after `--force-recreate`:

```bash
# 1. Force recreate with new env
docker compose -f network/docker-compose.yaml up -d --force-recreate

# 2. Immediately copy patched config.py back
docker cp /tmp/config.py pynts-o-ru-hybrid:/app/core/config.py
docker cp /tmp/config.py pynts-o-ru-hierarchical:/app/core/config.py
docker cp /tmp/config.py pynts-o-du-o1:/app/core/config.py

# 3. Restart to apply patch
docker restart pynts-o-ru-hybrid pynts-o-ru-hierarchical pynts-o-du-o1

# 4. Wait and verify
sleep 30
docker exec pynts-o-ru-hybrid cat /var/log/pynts.log | grep "succeeded" | tail -5
docker exec pynts-o-du-o1 cat /var/log/pynts.log | grep "Session" | tail -5
```

---

## Correct Values for `network/.env`

```env
HOST_IP=192.168.0.104
HTTP_DOMAIN=192.168.0.104

# SDN Controller - container name and HTTP port
SDNR_RESTCONF_URL=http://controller:8181
SDNR_USERNAME=admin
SDNR_PASSWORD=Kp8bJ4SXszM0WXlhak3eHlcse2gAw84vaoGGmJvUy2U

# VES Collector - container name and HTTP port
VES_URL=http://ves-collector:8080/eventListener/v7
VES_ENDPOINT_USERNAME=sample1
VES_ENDPOINT_PASSWORD=sample1

# NETCONF credentials
NETCONF_USERNAME=netconf
NETCONF_PASSWORD=netconf!

# PyNTS image settings
LOCAL_DOCKER_REPO=
PYNTS_VERSION=latest
```

---

## Confirmed Working Communication Chain

```
pynts-o-ru-hybrid
  ↓ NETCONF TLS CallHome (port 4335)
pynts-o-du-o1
  ↓ VES HTTP POST (port 8080)
ves-collector → Kafka → SMO

pynts-o-ru-hybrid
  ↓ HTTP REST (port 8181)
controller (ODL)
  Certificate registered        ✅ HTTP 204
  Added to allowed devices      ✅ HTTP 201

pynts-o-du-o1 Sessions:
  Session 1 with pynts-o-ru-hybrid         ✅ Active
  Session 2 with pynts-o-ru-hierarchical   ✅ Active
```

---

*Document generated based on actual connection session — May 2026*













```
## What to do everyday

1. make all the container down if not
cd ~/Desktop/TU_Ilmenau/Seminar/oam/solution

docker compose -f network/docker-compose.yaml down
docker compose -f smo/apps/docker-compose.yaml down
docker compose -f smo/oam/docker-compose.yaml down
docker compose -f smo/common/docker-compose.yaml down
docker compose -f infra/docker-compose.yaml down

2. Start everything in order

    # 1. Infrastructure
    docker compose -f infra/docker-compose.yaml up -d

    # Wait 1 minute
    sleep 60

    # 2. Common services (Keycloak)
    docker compose -f smo/common/docker-compose.yaml up -d

    # Wait 2 minutes for Keycloak to be healthy
    sleep 120

    # 3. OAM layer (Controller + VES)
    docker compose -f smo/oam/docker-compose.yaml up -d

    # Wait 2 minutes for controller to be healthy
    sleep 120

    # 4. Apps (Wireshark, Node-RED)
    docker compose -f smo/apps/docker-compose.yaml up -d

    # 5. Network (O-DU + O-RUs)
    docker compose -f network/docker-compose.yaml up -d

3. Connect wireshark with dcn network

docker network connect dcn wireshark

4. Restart O-DU 

docker restart pynts-o-du-o1

5. Send event manually 

docker exec pynts-o-du-o1 python3 -c "
import urllib.request, json
event = {
  'event': {
    'commonEventHeader': {
      'domain': 'pnfRegistration',
      'eventId': 'reg-001',
      'eventName': 'pnfRegistration_O-DU',
      'sourceName': 'pynts-o-du-o1',
      'version': '4.1',
      'vesEventListenerVersion': '7.2.1',
      'reportingEntityName': 'pynts-o-du-o1',
      'sequence': 0,
      'priority': 'Normal',
      'startEpochMicrosec': 0,
      'lastEpochMicrosec': 0
    },
    'pnfRegistrationFields': {
      'pnfRegistrationFieldsVersion': '2.1',
      'serialNumber': 'O-DU-1122',
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
print('Status:', urllib.request.urlopen(req).status)
"

6. Check VES Collector

docker logs ves-collector --since 1m -f


************************************************************************

1- 

cd ~/Desktop/TU_Ilmenau/Seminar/oam/solution

docker compose -f network/docker-compose.yaml down
docker compose -f smo/apps/docker-compose.yaml down
docker compose -f smo/oam/docker-compose.yaml down
docker compose -f smo/common/docker-compose.yaml down
docker compose -f infra/docker-compose.yaml down

2 - 

docker ps

3- 
# 1. Infrastructure
docker compose -f infra/docker-compose.yaml up -d
echo "Waiting for infra..."
sleep 60

# 2. Common services
docker compose -f smo/common/docker-compose.yaml up -d
echo "Waiting for Keycloak..."
sleep 120

# 3. OAM layer
docker compose -f smo/oam/docker-compose.yaml up -d
echo "Waiting for controller..."
sleep 120

# 4. Apps
docker compose -f smo/apps/docker-compose.yaml up -d

# 5. Network
docker compose -f network/docker-compose.yaml up -d

4 - 

docker ps --format "table {{.Names}}\t{{.Status}}"

5 - 
docker cp pynts-o-ru-hybrid:/app/core/config.py /tmp/config.py

sed -i '' "s/if iface == 'lo':/if iface in ['lo', 'tunl0', 'gre0', 'gretap0', 'erspan0', 'ip_vti0', 'ip6_vti0', 'sit0', 'ip6tnl0', 'ip6gre0']:/" /tmp/config.py

docker cp /tmp/config.py pynts-o-ru-hybrid:/app/core/config.py
docker cp /tmp/config.py pynts-o-ru-hierarchical:/app/core/config.py
docker cp /tmp/config.py pynts-o-du-o1:/app/core/config.py

docker restart pynts-o-ru-hybrid pynts-o-ru-hierarchical pynts-o-du-o1

7 - 

docker exec pynts-o-du-o1 ss -tlnp                                     

8- In one terminal 

docker exec pynts-o-du-o1 tcpdump -i any port 8080 -v -c 15 2>/dev/null

9 - In another terminal 

docker exec pynts-o-ru-hybrid python3 -c "
import urllib.request
req = urllib.request.Request('http://pynts-o-du-o1:8080/', headers={'Accept': 'application/json'})
r = urllib.request.urlopen(req, timeout=5)
print('O-RU -> O-DU Status:', r.status)
print('Response:', r.read().decode())
"





****************** Response ******************

O-RU → O-DU Request
pynts-o-ru-hybrid.dcn.45488 > pynts-o-du-o1.http-alt  [S]
→ TCP SYN (connection initiated by O-RU)

GET / HTTP/1.1
Host: pynts-o-du-o1:8080
User-Agent: Python-urllib/3.10
Accept: application/json
Connection: close
→ O-RU sent HTTP GET to O-DU
O-DU → O-RU Response
pynts-o-du-o1.http-alt > pynts-o-ru-hybrid.dcn.45488
HTTP/1.1 200 OK
date: Tue, 05 May 2026 16:27:35 GMT
server: uvicorn
content-type: application/json
content-length: 30
→ O-DU responded with HTTP 200 OK
JSON Response Content
{"status": "ok", "routes": {}}
Also captured at the bottom
pynts-o-du-o1 > ves-collector.dcn.http-alt  [S]
→ O-DU automatically sending VES event to SMO

All three communications confirmed ✅
DirectionProtocolPortStatusO-DU → SMOHTTP VES8080✅ CapturedO-DU ↔ O-RU hybridNETCONF TLS4335✅ CapturedO-DU ↔ O-RU hierarchicalNETCONF TLS4335✅ CapturedO-RU → O-DUHTTP REST8080✅ Captured — HTTP 200 OK



```

