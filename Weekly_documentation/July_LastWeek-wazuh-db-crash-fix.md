# Wazuh Manager (Docker) on Apple Silicon — Full Troubleshooting Log

## Summary

On a dockerized single-node Wazuh deployment (`wazuh/wazuh-manager:4.7.3`, `wazuh-indexer:4.7.3`, `wazuh-dashboard:4.7.3`) running on an Apple Silicon Mac via Docker Desktop, the manager API and dashboard connection were down. This turned out to be **three separate, compounding issues**, uncovered one at a time:

1. `wazuh-db` crashing on startup due to a Rosetta emulation bug (intermittent, load-dependent).
2. The dashboard's `wazuh.yml` pointing at a stale manager IP after container recreation.
3. A wrong `wazuh-wui` API password in `wazuh.yml` after the credentials were reset/changed.

Each section below documents one issue, in the order they were found and fixed.

## Environment

- **Host:** Apple Silicon Mac (`arm64`)
- **Docker Desktop VMM:** Apple Virtualization Framework
- **Image:** `wazuh/wazuh-manager:4.7.3` (published as `amd64` only — no native `arm64` build)
- **Emulation:** Rosetta enabled ("Use Rosetta for x86_64/amd64 emulation on Apple Silicon")

## Symptoms

- `wazuh-control status` repeatedly showed:
  ```
  wazuh-db: Process XXXX not used by Wazuh, removing...
  wazuh-db not running...
  ```
- `wazuh-analysisd` failed to start as a direct consequence (it depends on `wazuh-db`).
- Running `wazuh-db` in the foreground surfaced the real crash reason:
  ```
  assertion failed [!open_result.is_error]: Could not open /proc/cpuinfo
  (ThreadContextFcntl.cpp:302 number_of_processors)
  ```
- `cat /proc/cpuinfo` worked fine and returned valid data — ruling out a simple missing-file or permissions issue.

## Root Cause

The container was running under **Rosetta-based x86_64 emulation** (confirmed via `vendor_id: VirtualApple` in `/proc/cpuinfo`, plus `uname -m` = `arm64` on the host vs. `Architecture: amd64` on the image). `wazuh-db` links against a library (RocksDB/Folly) that performs CPU-count detection by opening `/proc/cpuinfo` and issuing an `fcntl()` call on the file descriptor. Under Rosetta's translation layer, this specific `/proc` + `fcntl` interaction doesn't behave like it does on a real Linux kernel or under standard QEMU-based emulation, causing the internal consistency check to fail and the process to abort.

This is an environment/emulation compatibility issue, not a Wazuh misconfiguration.

## Fix

1. Open **Docker Desktop → Settings → General → Virtual Machine Options**.
2. Uncheck **"Use Rosetta for x86_64/amd64 emulation on Apple Silicon."**
3. Restart Docker Desktop (full quit/reopen, not just container restart).
4. Recreate the whole stack so the setting fully takes effect:
   ```bash
   docker compose down
   docker compose up -d
   ```
5. Verify `wazuh-db` now starts cleanly:
   ```bash
   docker exec single-node-wazuh.manager-1 /var/ossec/bin/wazuh-control status
   ```

### Important: this bug is intermittent, not 100% deterministic

Running `wazuh-db -f` **standalone** in the foreground can succeed even with Rosetta *enabled* — the crash appears to depend on contention/timing when the full daemon set starts together. Don't treat a single successful standalone run as proof the bug is gone. Confirm health via a full `wazuh-control status` after a complete stack restart, not a foreground one-off test.

### This fix does not break the indexer or dashboard

It's reasonable to worry that disabling Rosetta would cause an "architecture incompatibility" error on the `amd64`-only indexer/dashboard images. In practice, disabling Rosetta only removes the accelerated translation path — Docker Desktop still emulates `amd64` via its standard QEMU-based path regardless. Verified in this deployment: with Rosetta off, `wazuh-indexer` and `wazuh-dashboard` started and ran normally with no errors. The `platform mismatch` message during `docker compose up` is a harmless, informational warning that appears either way, not a failure.

### Pitfall: don't run `wazuh-db -f` while the manager is already running

If `wazuh-db` is already running as part of the normal stack and you start a second instance with `wazuh-db -f` for diagnostics, then `Ctrl+C` it, you kill the real running instance — not just your test one. This looks identical to the original crash (`wazuh-db not running`, downstream daemons failing to connect to `queue/db/wdb`) but is self-inflicted, not a recurrence of the bug. If you need to test `wazuh-db` in isolation, stop the whole manager first:
```bash
docker exec single-node-wazuh.manager-1 /var/ossec/bin/wazuh-control stop
docker exec -it single-node-wazuh.manager-1 /var/ossec/bin/wazuh-db -f
```

## Secondary Issue: Stale `.restart` Lock File

After the fix above, the manager API (`wazuh-apid`) continued to report:
```json
{"title": "Bad Request", "detail": "Some Wazuh daemons are not ready yet in node \"node01\" (...->restarting)", "error": 1017}
```
even though `wazuh-control status` showed every daemon running and `wazuh-analysisd.state` showed active event processing. This was caused by a leftover `/var/ossec/var/run/.restart` flag file from the earlier manual restart/kill cycles performed while diagnosing the crash. The API checks for this file to decide whether the manager is mid-restart, and doesn't clear it if the restart sequence was interrupted.

**Fix:**
```bash
docker exec single-node-wazuh.manager-1 rm -f /var/ossec/var/run/.restart
docker exec single-node-wazuh.manager-1 /var/ossec/bin/wazuh-control restart
```

## Verification (Issue 1)

```bash
docker exec single-node-wazuh.manager-1 /var/ossec/bin/wazuh-control status
docker exec single-node-wazuh.manager-1 curl -s -k -u 'wazuh-wui:<password>' \
  https://localhost:55000/security/user/authenticate
```

Expected: a JSON response containing a `token` field and `"error": 0`.

---

## Issue 2: Dashboard Shows "Offline" — Stale Manager IP

### Symptom
The manager API itself worked fine (`curl` from inside the manager container succeeded), but the Wazuh dashboard's **API configuration** page showed the configured host as **Offline**.

### Root Cause
Docker assigns container IPs dynamically by default. Every `docker compose down && docker compose up -d` cycle can hand the manager container a new IP on the bridge network. The dashboard's `wazuh.yml` had a hardcoded IP (`172.22.0.2`) from an earlier session, but the manager had since come back up as `172.22.0.3`.

### Fix
1. Confirm the manager's current IP:
   ```bash
   docker inspect single-node-wazuh.manager-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
   ```
2. Update the IP in the dashboard's `wazuh.yml` to match (see Issue 3's note on locating this file correctly).
3. Restart the dashboard:
   ```bash
   docker restart single-node-wazuh.dashboard-1
   ```

### Permanent Fix (recommended)
Assign the manager a **static IP** in `docker-compose.yml` so it never drifts again:
```yaml
networks:
  default:
    ipam:
      config:
        - subnet: 172.22.0.0/24

services:
  wazuh.manager:
    networks:
      default:
        ipv4_address: 172.22.0.2
```
Alternatively, reference the manager by its Docker Compose **hostname** instead of an IP in `wazuh.yml` (`https://wazuh.manager`) — Docker's internal DNS resolves this regardless of IP changes, which is more robust than pinning an IP.

---

## Issue 3: Editing `wazuh.yml` Didn't Take Effect — Volume Precedence

### Symptom
Editing the "obvious" `wazuh.yml` found in the repo (`config/wazuh_dashboard/wazuh.yml`) had no effect — the running container kept serving old values.

### Root Cause
`docker-compose.yml` mounted **two overlapping sources** onto the same container directory:
```
./config/wazuh_dashboard/wazuh.yml               -> .../data/wazuh/config/wazuh.yml   (bind mount, specific file)
single-node_wazuh-dashboard-config (named volume) -> .../data/wazuh/config             (whole directory)
```
When a bind mount and a named volume overlap like this, the more specific/later mount takes precedence. In this deployment, the **named volume was winning**, so edits to the host-side file in the repo were silently ignored — the dashboard was actually reading/writing to Docker's internal named volume storage instead.

### How to find the real, active file
Inspect actual mounts on the running container rather than assuming from the repo structure:
```bash
docker inspect single-node-wazuh.dashboard-1 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
```
Check which entry has `.Destination` = `/usr/share/wazuh-dashboard/data/wazuh/config` (the whole dir) vs. `.../wazuh.yml` (the specific file) — whichever is mounted determines where edits actually need to go.

### Fix (quick, works immediately)
Edit the live file directly inside the container:
```bash
docker exec single-node-wazuh.dashboard-1 sed -i 's/<old_ip>/<new_ip>/' \
  /usr/share/wazuh-dashboard/data/wazuh/config/wazuh.yml
docker restart single-node-wazuh.dashboard-1
```

### Fix (permanent — makes the host file authoritative)
Remove the named-volume mount for the config directory from `docker-compose.yml`, leaving only the specific file bind mount:
```yaml
services:
  wazuh.dashboard:
    volumes:
      - ./config/wazuh_dashboard/wazuh.yml:/usr/share/wazuh-dashboard/data/wazuh/config/wazuh.yml
      # remove any line mounting a named volume over the parent config/ directory
```
Then `docker compose down && docker compose up -d`. After this, the host file is the single source of truth and survives every rebuild.

---

## Issue 4: Dashboard Shows "Invalid Credentials" (`ERROR3099`)

### Symptom
After fixing the IP, the dashboard reached the manager but failed with:
```
3099 - ERROR3099 - Invalid credentials
```

### Root Cause
The `password` field in `wazuh.yml` for the `wazuh-wui` user didn't match the manager's actual configured API password (drifted across the various restarts/recreates performed during troubleshooting).

### Fix
1. Check the password currently in `wazuh.yml`:
   ```bash
   docker exec single-node-wazuh.dashboard-1 cat /usr/share/wazuh-dashboard/data/wazuh/config/wazuh.yml
   ```
2. Confirm the correct password (check `.env` / `docker-compose.yml` for `API_PASSWORD`, or reset it via the manager if needed).
3. Update `wazuh.yml` with the correct password and restart the dashboard:
   ```bash
   docker restart single-node-wazuh.dashboard-1
   ```

---

## Final Verification

```bash
docker exec single-node-wazuh.manager-1 /var/ossec/bin/wazuh-control status
docker exec single-node-wazuh.manager-1 curl -s -k -u 'wazuh-wui:<password>' \
  https://localhost:55000/security/user/authenticate
```

In the dashboard: **Server Management → API configuration** should show status **Online** for the configured host.

Confirmed working end state: manager daemons all running, API returns a valid JWT token, dashboard shows the API host as **Online**.

## Notes / Follow-ups

- Disabling Rosetta means all `amd64`-emulated containers on this host now run under the slower QEMU-based translation path instead of Rosetta. If other emulated containers become noticeably slower, check whether a native `arm64` image exists for them:
  ```bash
  docker manifest inspect <image>:<tag>
  ```
- Check whether a newer Wazuh version publishes a native `arm64` manager image — running natively would avoid this entire class of emulation bug rather than working around it.
- The manager's `nofile` ulimit is currently set very high (`655360`). This wasn't the cause of this issue, but it has no real benefit for a single-node deployment and could be reduced (e.g., to `65536`) as general cleanup.
