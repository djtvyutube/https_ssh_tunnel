#!/usr/bin/env python3
"""
HTTPS-based SSH Tunnel Client & Server (ssh.py)
Relays SSH TCP traffic across HTTP(S) long-polling via a lightweight PHP relay.
Designed for high-security environments, zero-packet-loss SSH access, and CGNAT bypass.
"""

import argparse
import os
import socket
import sys
import threading
import time
import uuid
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CONFIG = {
    # Public HTTPS URL of the PHP relay script
    "RELAY_URL": os.environ.get("RELAY_URL", "https://your-domain.com"),
    # Shared secret authentication token between client, server, and relay
    "TOKEN": os.environ.get("RELAY_TOKEN", "YOUR_SECRET_TOKEN_HERE"),
    # Local port on client machine to listen for incoming SSH connections
    "LOCAL_LISTEN_PORT": int(os.environ.get("LOCAL_LISTEN_PORT", 2222)),
    # SSH daemon port on the target remote machine
    "REMOTE_SSH_PORT": int(os.environ.get("REMOTE_SSH_PORT", 22)),
    # SSH daemon host address on the target remote machine
    "REMOTE_SSH_HOST": os.environ.get("REMOTE_SSH_HOST", "127.0.0.1"),
    # Verbose packet and round-trip timing logs
    "DEBUG": False
}

def log(tag, msg, color=None):
    colors = {
        "GREEN": "\033[92m",
        "YELLOW": "\033[93m",
        "RED": "\033[91m",
        "CYAN": "\033[96m",
        "RESET": "\033[0m"
    }
    t = time.strftime("%H:%M:%S")
    c_start = colors.get(color, "") if sys.stdout.isatty() else ""
    c_end = colors.get("RESET", "") if sys.stdout.isatty() else ""
    print(f"[{t}] {c_start}[{tag}]{c_end} {msg}")

def debug_log(tag, msg, color=None):
    if CONFIG.get("DEBUG", False):
        log(tag, msg, color)

def create_http_session():
    """Configures a pooled HTTP session with browser User-Agent and automatic retries."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Connection": "keep-alive"
    })
    retries = Retry(total=2, backoff_factor=0.05, status_forcelist=[502, 503, 504])
    s.mount('https://', HTTPAdapter(max_retries=retries, pool_connections=35, pool_maxsize=35))
    s.mount('http://', HTTPAdapter(max_retries=retries, pool_connections=35, pool_maxsize=35))
    return s

# ----------------- DIAGNOSTIC & HEALTH CHECK -----------------

def run_diagnostic(cfg):
    """Verifies relay connectivity, write permissions, and local OpenSSH daemon status."""
    log("TEST", "Testing relay server and HTTPS connectivity...", "CYAN")
    http = create_http_session()

    try:
        t0 = time.time()
        r = http.get(cfg["RELAY_URL"], params={"action": "diag", "token": cfg["TOKEN"]}, timeout=8)
        ms = int((time.time() - t0) * 1000)

        if r.status_code == 200:
            data = r.json()
            log("TEST", f"HTTPS Relay connection successful ({ms}ms) | Storage: {data.get('storage_dir')} (Writable: {data.get('is_writable')})", "GREEN")
            if not data.get("is_writable"):
                log("ERROR", "PHP storage directory is NOT writable! Check web server permissions.", "RED")
        elif r.status_code == 403:
            log("ERROR", "Authentication Failed (HTTP 403 Forbidden)! Ensure TOKEN matches the PHP script.", "RED")
            return
        else:
            log("ERROR", f"Relay returned unexpected response: HTTP {r.status_code} - {r.text}", "RED")
            return
    except Exception as e:
        log("ERROR", f"Failed to connect to relay server: {e}", "RED")
        return

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect((cfg["REMOTE_SSH_HOST"], cfg["REMOTE_SSH_PORT"]))
        banner = s.recv(1024).decode(errors="ignore").strip()
        s.close()
        log("TEST", f"Local SSH daemon reachable ({cfg['REMOTE_SSH_HOST']}:{cfg['REMOTE_SSH_PORT']}) -> Banner: {banner}", "GREEN")
    except Exception as e:
        log("INFO", f"Local SSH check note ({cfg['REMOTE_SSH_HOST']}:{cfg['REMOTE_SSH_PORT']}): {e}")

# ----------------- TUNNEL WORKERS (BIDIRECTIONAL) -----------------

def start_tunnel_workers(sock, session_id, push_target, pull_target, cfg, http, role):
    """Bridges TCP socket data and HTTP relay requests concurrently."""
    active = [True]
    stats = {"sent_bytes": 0, "recv_bytes": 0, "push_pkts": 0, "pull_pkts": 0}

    def status_monitor():
        while active[0]:
            time.sleep(1)
            if not active[0]:
                break
            if not CONFIG.get("DEBUG", False):
                kb_in = stats['recv_bytes'] / 1024
                kb_out = stats['sent_bytes'] / 1024
                sys.stdout.write(
                    f"\r\033[K[{time.strftime('%H:%M:%S')}] [{role}] ACTIVE (HTTPS) | "
                    f"Sent: {kb_out:.1f} KB ({stats['push_pkts']} pkts) | "
                    f"Recv: {kb_in:.1f} KB ({stats['pull_pkts']} pkts)"
                )
                sys.stdout.flush()
        if not CONFIG.get("DEBUG", False):
            print()

    def pull_worker():
        seq = 0
        consecutive_errors = 0
        while active[0]:
            try:
                t0 = time.time()
                r = http.get(
                    cfg["RELAY_URL"],
                    params={"action": "pull", "target": pull_target, "seq": seq, "session": session_id, "token": cfg["TOKEN"]},
                    timeout=8
                )
                ms = int((time.time() - t0) * 1000)

                if r.status_code == 200 and len(r.content) > 0:
                    sock.sendall(r.content)
                    consumed = int(r.headers.get("X-Consumed", 1))
                    stats["recv_bytes"] += len(r.content)
                    stats["pull_pkts"] += consumed
                    debug_log(f"PULL:{role}", f"seq={seq}+{consumed} | {len(r.content)} bytes received ({ms}ms)", "GREEN")
                    seq += consumed
                    consecutive_errors = 0
                elif r.status_code == 204:
                    consecutive_errors = 0
                    continue
                elif r.status_code == 410:
                    debug_log(f"PULL:{role}", "Remote party terminated the session (HTTP 410).", "YELLOW")
                    break
                else:
                    debug_log(f"ERROR:{role}", f"PULL HTTP {r.status_code}", "RED")
                    time.sleep(0.2)
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors % 5 == 0:
                    debug_log(f"ERROR:{role}", f"PULL connection error ({consecutive_errors}): {e}", "RED")
                time.sleep(0.02)

        active[0] = False

    def push_worker():
        seq = 0
        while active[0]:
            try:
                chunk = sock.recv(16384)
                if not chunk:
                    debug_log(f"PUSH:{role}", "Socket closed by local peer (EOF).", "YELLOW")
                    break

                # Micro-batching: combine ready TCP bytes into one HTTP request to reduce latency
                sock.setblocking(False)
                extra = []
                while True:
                    try:
                        more = sock.recv(16384)
                        if not more:
                            break
                        extra.append(more)
                    except BlockingIOError:
                        break
                sock.setblocking(True)
                if extra:
                    chunk += b"".join(extra)

                while active[0]:
                    try:
                        t0 = time.time()
                        pr = http.post(
                            cfg["RELAY_URL"],
                            params={"action": "push", "target": push_target, "seq": seq, "session": session_id, "token": cfg["TOKEN"]},
                            data=chunk,
                            timeout=8
                        )
                        ms = int((time.time() - t0) * 1000)

                        if pr.status_code == 200:
                            stats["sent_bytes"] += len(chunk)
                            stats["push_pkts"] += 1
                            debug_log(f"PUSH:{role}", f"seq={seq} | {len(chunk)} bytes forwarded to relay ({ms}ms)", "CYAN")
                            seq += 1
                            break
                        elif pr.status_code == 410:
                            active[0] = False
                            break
                        else:
                            time.sleep(0.05)
                    except Exception:
                        time.sleep(0.05)
            except Exception:
                break

        active[0] = False

    t_pull = threading.Thread(target=pull_worker, daemon=True)
    t_push = threading.Thread(target=push_worker, daemon=True)
    t_stat = threading.Thread(target=status_monitor, daemon=True)
    t_pull.start()
    t_push.start()
    t_stat.start()

    while active[0] and t_push.is_alive() and t_pull.is_alive():
        time.sleep(0.05)

    active[0] = False
    try:
        sock.close()
    except Exception:
        pass

# ----------------- TARGET SERVER MODE (REMOTE PC) -----------------

def handle_server_session(session_id, cfg):
    """Connects to local OpenSSH daemon and bridges to the relay session."""
    http = create_http_session()
    log("SERVER", f"[{session_id}] Connecting to local OpenSSH service...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.connect((cfg["REMOTE_SSH_HOST"], cfg["REMOTE_SSH_PORT"]))
        log("SERVER", f"[{session_id}] Connected to local OpenSSH service.", "GREEN")
    except Exception as e:
        log("ERROR", f"[{session_id}] Could not connect to local SSH service: {e}", "RED")
        try:
            http.get(cfg["RELAY_URL"], params={"action": "close_session", "session": session_id, "token": cfg["TOKEN"]}, timeout=3)
        except Exception:
            pass
        return

    start_tunnel_workers(sock, session_id, push_target="to_client", pull_target="to_server", cfg=cfg, http=http, role="SERVER")

    try:
        http.get(cfg["RELAY_URL"], params={"action": "close_session", "session": session_id, "token": cfg["TOKEN"]}, timeout=3)
    except Exception:
        pass
    log("SERVER", f"[{session_id}] Session terminated.", "YELLOW")

def run_server_mode(cfg):
    """Polls the relay long-polling queue for incoming connections from clients."""
    log("SERVER", f"Listening for sessions. Forwarding to SSH daemon at {cfg['REMOTE_SSH_HOST']}:{cfg['REMOTE_SSH_PORT']}", "CYAN")
    http = create_http_session()

    while True:
        try:
            resp = http.get(
                cfg["RELAY_URL"],
                params={"action": "wait_connection", "token": cfg["TOKEN"]},
                timeout=20
            )
            if resp.status_code == 200 and resp.text.strip():
                session_id = resp.text.strip()
                log("SERVER", f"New incoming session detected: {session_id}", "GREEN")
                threading.Thread(target=handle_server_session, args=(session_id, cfg), daemon=True).start()
            elif resp.status_code == 403:
                log("ERROR", "Invalid token (HTTP 403 Forbidden)!", "RED")
                time.sleep(3)
        except Exception:
            time.sleep(1)

# ----------------- CLIENT MODE (LOCAL PC) -----------------

def handle_client_connection(client_sock, addr, cfg):
    """Registers session with the relay and pairs the local client socket."""
    http = create_http_session()
    session_id = "sess_" + uuid.uuid4().hex[:8]
    log("CLIENT", f"Inbound connection from {addr[0]}:{addr[1]}. Session: {session_id}", "CYAN")

    try:
        r = http.get(
            cfg["RELAY_URL"],
            params={"action": "register_session", "session": session_id, "token": cfg["TOKEN"]},
            timeout=5
        )
        if r.status_code != 200 or "REGISTERED" not in r.text:
            log("ERROR", f"Could not register session with relay: HTTP {r.status_code}", "RED")
            client_sock.close()
            return
    except Exception as e:
        log("ERROR", f"Relay registration error: {e}", "RED")
        client_sock.close()
        return

    start_tunnel_workers(client_sock, session_id, push_target="to_server", pull_target="to_client", cfg=cfg, http=http, role="CLIENT")

    try:
        http.get(cfg["RELAY_URL"], params={"action": "close_session", "session": session_id, "token": cfg["TOKEN"]}, timeout=3)
    except Exception:
        pass
    log("CLIENT", f"[{session_id}] Session closed.", "YELLOW")

def run_client_mode(cfg):
    """Listens on local TCP port for SSH client commands."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    srv.bind(("127.0.0.1", cfg["LOCAL_LISTEN_PORT"]))
    srv.listen(5)

    log("CLIENT", f"Listening on 127.0.0.1:{cfg['LOCAL_LISTEN_PORT']}", "GREEN")
    print("[*] To connect, run this command in another terminal:")
    print(f"    ssh <username>@127.0.0.1 -p {cfg['LOCAL_LISTEN_PORT']}\n")

    while True:
        try:
            client_sock, addr = srv.accept()
            client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(target=handle_client_connection, args=(client_sock, addr, cfg), daemon=True).start()
        except KeyboardInterrupt:
            break
        except Exception as e:
            log("ERROR", f"Accept error: {e}", "RED")

# ----------------- ENTRYPOINT -----------------

def main():
    parser = argparse.ArgumentParser(description="SSH over HTTPS Relay Tunnel")
    parser.add_argument("--mode", choices=["client", "server", "test"], default="client",
                        help="Operation mode: client, server, or test (default: client)")
    parser.add_argument("--relay-url", type=str, default=None,
                        help="Full URL of the PHP relay script (overrides RELAY_URL env var)")
    parser.add_argument("--token", type=str, default=None,
                        help="Shared authentication token (overrides RELAY_TOKEN env var)")
    parser.add_argument("--port", type=int, default=None,
                        help="Port number (client listen port or server SSH daemon port)")
    parser.add_argument("--ssh-host", type=str, default=None,
                        help="Target SSH host (default: 127.0.0.1)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable verbose packet and timing logs")
    args = parser.parse_args()

    if args.relay_url:
        CONFIG["RELAY_URL"] = args.relay_url
    if args.token:
        CONFIG["TOKEN"] = args.token
    if args.ssh_host:
        CONFIG["REMOTE_SSH_HOST"] = args.ssh_host
    if args.debug:
        CONFIG["DEBUG"] = True
    if args.port:
        if args.mode == "client":
            CONFIG["LOCAL_LISTEN_PORT"] = args.port
        else:
            CONFIG["REMOTE_SSH_PORT"] = args.port

    if args.mode == "test":
        run_diagnostic(CONFIG)
    elif args.mode == "server":
        run_server_mode(CONFIG)
    elif args.mode == "client":
        run_client_mode(CONFIG)

if __name__ == "__main__":
    main()
