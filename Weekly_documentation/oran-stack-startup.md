# O-RAN SC OAM Stack — Startup and Troubleshooting Log

Project: O-RAN Network Intrusion Detection Pipeline (Suricata + Wazuh + anomaly detection)
Scope: Bringing the O-RAN SC OAM/SMO simulator stack back up after several weeks, and establishing a working O1 interface (NETCONF over TLS, port 6513) between the SMO controller and the simulated O-DU — the prerequisite for capturing a benign traffic baseline.

Environment: Apple Silicon Mac, Docker Desktop, O-RAN SC OAM solution (`oam/solution`), Wazuh single-node stack running alongside.

---

## Stack overview

The OAM solution is split into four Docker Compose projects. They must start in dependency order.

| Order | Project | Path | Main contents |
|---|---|---|---|
| 1 | `common` | `smo/common/docker-compose.yaml` | gateway (Traefik), identity (Keycloak), identitydb (PostgreSQL), persistence (MariaDB), kafka, zookeeper, kafka-bridge, topology |
| 2 | `oam` | `smo/oam/docker-compose.yaml` | controller (SDN-R / OpenDaylight), odlux (web UI), ves-collector |
| 3 | `network` | `network/docker-compose.yaml` | pynts-o-du-o1, pynts-o-ru-hybrid, pynts-o-ru-hierarchical |
| — | `apps` | `smo/apps/docker-compose.yaml` | Node-RED, Jenkins — not needed for this project |

The `scripts` project (`ntsim-master/ntsimulator`) belongs to the older NTS simulator and is not used.

### Networks

| Network | Subnet | Purpose |
|---|---|---|
| `dcn` | 172.21.0.0/16 | Data Communication Network — the O1 management network between SMO and network functions. NETCONF runs here. Same segment as the original attack captures. |
| `smo` | 172.19.0.0/16 | Internal SMO traffic, e.g. VES event reporting |

The Wazuh manager is also attached to `dcn` (172.21.0.2).

---

## Working startup procedure

Run from `~/Desktop/TU_Ilmenau/Seminar/oam/solution`. Do not use `sudo`.

```bash
# 1. Common services
docker compose -f smo/common/docker-compose.yaml up -d

# If topology stays unhealthy after Keycloak is up (see Issue 2):
docker restart topology

# 2. OAM layer — wait for "Karaf started in ..." before continuing
docker compose -f smo/oam/docker-compose.yaml up -d
docker logs -f controller

# 3. Network functions
docker compose -f network/docker-compose.yaml up -d
```

`--wait` is deliberately omitted for the OpenDaylight-based services: their health checks can time out under emulation even when the service is starting correctly.

### Verification

```bash
# Helper: run curl inside the controller's network namespace
alias ctlcurl='docker run --rm -i --network container:controller nicolaka/netshoot curl'

# O-DU listening on 6513?
docker run --rm --network container:pynts-o-du-o1 nicolaka/netshoot ss -tlnp

# Controller connected to the O-DU?
ctlcurl -s -u 'admin:<ADMIN_PASSWORD>' \
  "http://localhost:8181/rests/data/network-topology:network-topology/topology=topology-netconf?content=nonconfig" \
  | grep -o '"node-id":"[^"]*"\|"connection-status":"[^"]*"'
```

Expected: port `6513` listening, and `"connection-status":"connected"` for `pynts-o-du-o1`.

---

## Issues encountered and solutions

### 1. Keycloak (`identity`) fails to start — timezone mount

**Problem**
```
Error response from daemon: error while creating mount source path
'/host_mnt/private/var/db/timezone/tz/2025c.1.0/zoneinfo/Asia/Karachi':
mkdir ...: operation not permitted
```

**Cause**
The compose file bind-mounts `/etc/localtime` into the container. On macOS, `/etc/localtime` is a symlink into a versioned, system-protected directory. A macOS update changed the timezone database version (`2025c.1.0`), so the resolved path no longer exists inside Docker Desktop's VM, and macOS forbids creating it. `sudo` does not help.

**Solution**
In `smo/common/docker-compose.yaml`, under the `identity` service, comment out the mount and set the timezone through an environment variable instead:

```yaml
    environment:
      ...
      TZ: Europe/Berlin
    volumes:
#      - /etc/localtime:/etc/localtime:ro
```

Back up the file first. Check the other compose files for the same mount:

```bash
grep -n "localtime\|zoneinfo" smo/oam/docker-compose.yaml network/docker-compose.yaml
```

---

### 2. `topology` reports unhealthy

**Problem**
`container topology is unhealthy`. The health check (`curl -u admin:admin http://localhost:8181`) timed out on every attempt. A manual request with a 60-second limit returned `HTTP 000` after ~30 seconds — the server closed the connection without responding.

**Cause**
Topology (OpenDaylight/Karaf) booted while Keycloak was still starting, and cached a broken authentication connection. Every authenticated request then hung.

**Solution**
```bash
docker restart topology
```
After restart, with Keycloak already healthy, topology became healthy. Topology is not on the controller–O-DU path, so this does not block the O1 link.

---

### 3. Platform mismatch warning on simulators

**Problem**
```
The requested image's platform (linux/amd64) does not match the detected host platform (linux/arm64/v8)
```

**Cause**
The pynts images are x86-only and run under emulation on Apple Silicon. The warning is printed only when a container is *created*, which is why it appeared after Compose recreated the simulators, but not on earlier restarts.

**Solution**
Warning only — no action needed. Optionally silence it with `platform: linux/amd64` in each simulator service.

---

### 4. Controller logs show no device activity

**Problem**
`docker logs controller | grep pynts` returned nothing.

**Cause**
Container stdout only contains the startup script. OpenDaylight writes device connection events to its own log file.

**Solution**
```bash
docker exec controller sh -c 'grep -i "pynts-o-du-o1" /opt/opendaylight/data/log/karaf.log | tail -20'
```

---

### 5. Controller dials the O-DU at a stale address

**Problem**
The controller log showed it connecting to `pynts-o-du-o1` at `172.21.0.7:6513`, but the O-DU was now at `172.21.0.8`. Status stayed `onCreated`, never connected.

**Cause**
The controller stores device connection entries in its database (`persistence`), which survives container recreation. The entry was created when the O-DU was at `.7`. After recreation, Docker assigned new addresses — `.7` went to `pynts-o-ru-hybrid`, so the controller was trying to open an O-DU session to an O-RU.

**Solution**
Edit the stored entry over RESTCONF. Two obstacles had to be worked around first:

- **ODLUX unreachable.** `https://odlux.192.168.0.104` cannot resolve: a subdomain cannot be prefixed to an IP address, and `HTTP_DOMAIN=192.168.0.104` was the Mac's address on a previous network.
- **No `curl` in the controller image.** Solved with a helper container sharing the controller's network namespace (`ctlcurl` alias above), so `localhost:8181` reaches the controller directly.

```bash
BASE="http://localhost:8181/rests/data/network-topology:network-topology/topology=topology-netconf/node=pynts-o-du-o1"

# Read the current entry
ctlcurl -s -u 'admin:<ADMIN_PASSWORD>' "$BASE?content=config" > odu-node.json
cp odu-node.json odu-node.json.bak

# Change only the address (macOS sed syntax)
sed -i '' 's/172\.21\.0\.7/172.21.0.8/' odu-node.json

# Write it back — expect HTTP 204
ctlcurl -s -o /dev/null -w "HTTP %{http_code}\n" -u 'admin:<ADMIN_PASSWORD>' \
  -X PUT -H "Content-Type: application/json" --data @- "$BASE" < odu-node.json
```

Reading and editing the existing entry preserves all other settings (credentials, TLS, keepalive). The admin password was read from the container environment:

```bash
docker inspect controller --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -i -E "pass|user"
```

---

### 6. Stale O-CU entry pointing at the O-DU

**Problem**
A second controller entry, `276782eb8264`, was also connecting to `172.21.0.8:6513`.

**Cause**
`276782eb8264` was the container ID of `pynts-o-cu`, which had registered itself (without a hostname set, so under its container ID) when it was at `.8`. The O-CU is no longer running, and `.8` now belonged to the O-DU. Both entries competed for the O-DU with `lockDatastore=true`.

**Solution**
Confirmed identity, then deleted the stale entry:

```bash
docker inspect 276782eb8264 --format '{{.Name}}'   # -> /pynts-o-cu

ctlcurl -s -o /dev/null -w "HTTP %{http_code}\n" -u 'admin:<ADMIN_PASSWORD>' -X DELETE \
  "http://localhost:8181/rests/data/network-topology:network-topology/topology=topology-netconf/node=276782eb8264"
```

The O-CU re-registers itself if started again.

---

### 7. Port 6513 closed — pynts crashes under QEMU emulation

**Problem**
```
nc: connect to 172.21.0.8 port 6513 (tcp) failed: Connection refused
```
`ss -tlnp` inside the O-DU showed no NETCONF listeners at all (neither 830 nor 6513). `/var/log/pynts.log` ended in:
```
set_promisc(self.ins, self.iface)
OSError: [Errno 92] Protocol not available
```

**Cause**
At startup, pynts performs O-RAN plug-and-play DHCP discovery using scapy, which sets the interface to promiscuous mode. Docker was emulating the x86 image with **QEMU**, which does not support that packet-socket option. The unhandled exception crashed pynts before it configured netopeer2's listeners. The same error had appeared earlier in the project when running scapy inside the Wazuh manager.

**Solution**
Enabled Rosetta: Docker Desktop → Settings → General → "Use Rosetta for x86_64/amd64 emulation on Apple Silicon". Rosetta passes system calls to the real kernel, so the option works. Then restarted the stack in order (see procedure above) and recreated the simulators.

Note: application logs are in `/var/log/pynts.log` and `/var/log/netopeer2-server.log`, not in `docker logs`.

---

### 8. pynts crashes again — DHCP on down tunnel interfaces

**Problem**
After enabling Rosetta, pynts got past the promiscuous-mode call but crashed with:
```
OSError: [Errno 100] Network is down
```

**Cause**
`dhcp_get_config()` in `/app/core/config.py` sends a DHCP broadcast on every interface except `lo`, without checking whether the interface is up and without error handling. Docker Desktop's kernel creates ten tunnel interfaces in each container (`tunl0`, `gre0`, `sit0`, …), all `DOWN`, listed before `eth0`. The first send on `tunl0` raised an exception and killed the process. These interfaces likely appeared through a Docker Desktop update since the original captures were made.

The DHCP results are never used — the code that would process a DHCP offer is commented out — so restricting DHCP to real interfaces has no functional effect.

**Solution**
Patched the loop to use only `eth*` interfaces, and mounted the patched file into the container so the fix persists across recreation:

```bash
mkdir -p network/pynts-patches
docker cp pynts-o-du-o1:/app/core/config.py network/pynts-patches/config.py
cp network/pynts-patches/config.py network/pynts-patches/config.py.orig
sed -i '' "s/if iface == 'lo':/if not iface.startswith('eth'):/" network/pynts-patches/config.py
```

In `network/docker-compose.yaml`, under `pynts-o-du-o1`:

```yaml
    volumes:
      - ./o-du-o1/data:/data
      - ./pynts-patches/config.py:/app/core/config.py:ro
```

The O-RU simulators likely need the same mount if they are ever required.

TLS on 6513 did not need an environment variable: although `TLS_LISTEN_ENDPOINT` defaults to `False` in the code, the endpoint is defined directly in `network/o-du-o1/data/ietf-netconf-server-running.json`.

---

### 9. O-DU address changes on every recreate

**Problem**
After recreating the O-DU, its `dcn` address moved again, from `.8` to `.6`, invalidating the controller entry once more.

**Cause**
Docker assigns addresses dynamically in the order containers start.

**Solution**
Pinned the O-DU to a fixed address, chosen high in the range so dynamically assigned containers never claim it first. In `network/docker-compose.yaml`, under `pynts-o-du-o1` (overriding the networks inherited from `common_nf`):

```yaml
    networks:
      smo:
      dcn:
        ipv4_address: 172.21.0.100
```

Then recreated the O-DU and updated the controller entry to `172.21.0.100` using the same RESTCONF procedure as Issue 5.

---

## Result

```
RemoteDeviceId[name=pynts-o-du-o1, address=/172.21.0.100:6513]: Netconf connector initialized successfully
```

The controller holds a live NETCONF-over-TLS session to the O-DU on the `dcn` network — the same protocol, port, and network segment targeted by the TLS flood attack captures.

## Known open issue

The O-DU's VES `pnfRegistration` POSTs to `http://ves-collector:8080/eventListener/v7` return `HTTP 500`. This does not affect the O1 link and was left for later.

## Addresses to remember

| Component | `dcn` address | Note |
|---|---|---|
| controller | 172.21.0.5 | dynamic |
| pynts-o-du-o1 | 172.21.0.100 | pinned |
| Wazuh manager | 172.21.0.2 | dynamic |
| Attack captures | target 172.21.0.7 | historical — O-DU's address at capture time |

Signature rules referencing `172.21.0.7` match the historical attack pcaps but not the live O-DU.
