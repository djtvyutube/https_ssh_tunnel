# HTTP(S) Relay Tunnel for SSH: Zero-Data-Loss Remote Access Behind Strict Firewalls

A robust, loss-tolerant TCP-over-HTTPS tunnel crafted for high-security, restrictive enterprise environments, Carrier-Grade NAT (CGNAT), and isolated networks. This system enables users to maintain reliable, interactive SSH shell sessions and high-throughput SFTP/SCP file transfers without packet loss, port forwarding, or public IP addresses.

---

## The Problem & The Solution

In many enterprise, campus, and secure production environments:
* Outbound TCP connections on non-standard ports (such as port 22) are blocked by Next-Generation Firewalls (NGFW) and Deep Packet Inspection (DPI).
* Inbound ports are strictly prohibited and NAT traversal is blocked.
* Direct peer-to-peer tunnels (WireGuard, OpenVPN, standard reverse SSH tunnels) get throttled, blocked, or severed.

**How This Project Solves It:**
Instead of fighting perimeter firewalls, this system encapsulates raw SSH TCP packets into standard, compliant HTTPS `POST` and `GET` requests (`application/octet-stream`). It establishes a bidirectional bridge through a neutral, lightweight web server:

```text
[ Local Client PC ]                  [ Public Relay Host ]                 [ Target Server PC ]
 (Your Laptop/PC)                     (External PHP Server)                 (Workstation behind NAT)
        |                                      |                                       |
  Local SSH Client                             |                                  OpenSSH Daemon
(ssh user@127.0.0.1:2222)                      |                                  (127.0.0.1:22)
        |                                      |                                       |
    ssh.py (client)    === Outbound HTTPS ===> api.php <=== Outbound Long-Poll ===  ssh.py (server)
                       (Port 443 / TLS 1.3)            (Port 443 / TLS 1.3)
```

Both endpoints initiate **outbound** connections over port 443. To corporate firewalls, proxies, and DPI engines, all traffic appears as standard browser web requests with valid browser `User-Agent` headers.

---

## Infrastructure Requirements (The 3 Components)

To establish the tunnel, you need exactly 3 nodes:

1. **One External Relay Server (Web Host)**:
   * Any server capable of running standard PHP 7.4+ (cPanel, shared hosting, Apache, Nginx, VPS, Docker).
   * Does **not** require root/sudo access, system services, or open custom ports.
   * Runs the single standalone script: `api.php`.
   * Must have an active SSL/TLS certificate (HTTPS on port 443).

2. **Target Machine (Remote PC to be Controlled)**:
   * The computer inside the secured network you need to access (e.g., Ubuntu, Debian, CentOS, macOS, WSL).
   * Runs standard OpenSSH server (`sshd`) on `127.0.0.1:22`.
   * Runs `ssh.py` in `--mode server`.

3. **Client Machine (Your Local PC)**:
   * The computer you are physically using (Windows, macOS, or Linux).
   * Runs standard SSH client (`ssh` command, PuTTY, VS Code Remote SSH, WinSCP, etc.).
   * Runs `ssh.py` in `--mode client`.

---

## Core Features & Engineering Highlights

* **Guaranteed Reliability & Zero Data Loss**: Employs strict sequential chunk indexing (`seq=0, 1, 2...`) with atomic queue tracking. Chunks are acknowledged and removed only once fully consumed, preventing dropped keystrokes or corrupted file transfers.
* **Micro-Batching & Packet Aggregation**: Under high throughput (such as scp/sftp transfers or verbose terminal outputs), queued socket chunks are bundled into unified multi-packet HTTP payloads (up to 25 packets per round-trip), dramatically slashing HTTP header overhead and latency.
* **Responsive Long-Polling Engine**: Uses ultra-fast microsecond polling intervals with HTTP 204 keep-alives and 20-second connection listeners, delivering near-instant terminal responsiveness.
* **Stealth DPI & WAF Evasion**: Mimics authentic Google Chrome browser requests (`User-Agent`, standard TLS, HTTP keep-alive, standard MIME types).
* **Self-Healing Connection Pool**: Utilizes a persistent HTTP session pool with exponential backoffs and retry mechanisms to survive temporary network hiccups.
* **Automated Session Cleanup**: Automatically purges completed session buffers and queue directories upon disconnection, preventing disk clutter on the relay server.

---

## Network Troubleshooting & DPI Bypass (Crucial Advice)

In certain strict networks (corporate proxies, deep packet inspection firewalls, or regional censorship), long-polling HTTPS connections or frequent chunked requests on the **Target Server PC** (`--mode server`) may experience stalled streams or intermittent timeouts. 

If your target machine runs `ssh.py --mode server` but fails to establish a continuous stream or drops packets:

### Recommended Fix: Cloudflare WARP / Quick VPN on Target PC
You only need to install a fast tunnel/VPN **on the target server PC itself**:
1. **Cloudflare WARP (Recommended)**:
   * Free, lightweight, and specifically optimized for enterprise egress routing.
   * On Linux/Ubuntu:
     ```bash
     # Install cloudflare-warp
     sudo apt-get install cloudflare-warp
     warp-cli register
     warp-cli connect
     ```
   * WARP wraps the target PC's outbound HTTPS traffic into Cloudflare's WireGuard-based edge network, completely bypassing local corporate proxy filtering and ISP throttling to your relay domain.
2. **Alternative Fast WireGuard / Shadowsocks**:
   * Running any low-overhead WireGuard connection or lightweight egress proxy on the target PC will instantly resolve packet dropping caused by intermediate middleboxes.
   * **Note:** You do *not* need a VPN on your client PC unless your client's network is also blocking outbound web access to your relay domain.

### Additional Network Tips
* **Disable Proxy Buffering on Web Server**: If hosting `api.php` behind Nginx or Apache, disable output buffering (`proxy_buffering off;`) to allow chunks to stream instantly.
* **Cloudflare CDN Settings**: If your relay domain is behind Cloudflare, disable features that buffer POST requests or strip persistent connections for `/ssh/api.php`. Set caching to bypass for the relay path.
* **Keep-Alive Configuration**: Keep `TCP_NODELAY` enabled (default in `ssh.py`) to prevent Nagle's algorithm from buffering interactive SSH keystrokes.

---

## Project Directory Layout

```text
.
├── api.php             # Lightweight PHP relay API to host on your web server
├── ssh.py              # Multi-threaded Python bridge (handles client, server, & diag modes)
├── requirements.txt    # Python package dependencies (requests, urllib3)
├── .env.example        # Environment variable template for credentials
├── .gitignore          # Git exclusion rules for logs, virtual environments, and caches
├── LICENSE             # MIT License file
└── README.md           # Full technical documentation
└── README_TR.md        # Türkçe teknik dokümantasyon
```

---

## Step-by-Step Deployment & Setup

### Step 1: Deploy the PHP Relay (External Server)

1. Upload `api.php` to your web server (for example, into `public_html/ssh/api.php` so it is accessible at `https://your-domain.com/ssh/api.php`).
2. Verify that PHP has write permissions to create temporary storage folders (`.relay_data/` in the script directory or the system temp directory).
3. **Protect Data Buffer**: Ensure direct web access to `.relay_data/` is forbidden by placing an `.htaccess` or configuring your web server:
   ```apache
   # Apache (.htaccess inside .relay_data/ or root)
   <Directory ".relay_data">
       Require all denied
   </Directory>
   ```
4. Set your secret authentication token:
   * **Recommended**: Set the environment variable on your web server:
     ```bash
     RELAY_AUTH_TOKEN="your_super_strong_random_token_here"
     ```
   * **Alternative**: Edit the fallback token directly in `api.php`:
     ```php
     $AUTH_KEY = getenv('RELAY_AUTH_TOKEN') ?: 'your_super_strong_random_token_here';
     ```

### Step 2: Set Up the Target PC (Remote Machine)

1. Clone or download this repository on the target machine:
   ```bash
   git clone https://github.com/djtvyutube/https_ssh_tunnel.git
   cd https_ssh_tunnel
   ```
2. Set up a virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Ensure the local OpenSSH daemon is active:
   ```bash
   sudo systemctl status ssh
   # If not running: sudo systemctl start ssh
   ```
4. Run the diagnostic check to ensure connectivity:
   ```bash
   python3 ssh.py --mode test \
     --relay-url "https://your-domain.com/ssh/api.php" \
     --token "your_super_strong_random_token_here"
   ```
5. Start the server listener:
   ```bash
   python3 ssh.py --mode server \
     --relay-url "https://your-domain.com/ssh/api.php" \
     --token "your_super_strong_random_token_here" \
     --port 22
   ```
   *(The server will begin listening for incoming tunnel sessions from the relay).*

#### (Optional) Run Target Server in Background as a Systemd Service

To keep the tunnel running 24/7 on your remote Linux machine, create a systemd service:

```bash
sudo nano /etc/systemd/system/https-ssh-tunnel.service
```

Paste the following configuration (adjust paths and user accordingly):

```ini
[Unit]
Description=HTTP(S) Relay Tunnel for SSH (Target Server)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/https_ssh_tunnel
ExecStart=/home/ubuntu/https_ssh_tunnel/venv/bin/python3 ssh.py --mode server --relay-url "https://your-domain.com/ssh/api.php" --token "your_super_strong_random_token_here" --port 22
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now https-ssh-tunnel
```

---

### Step 3: Set Up the Client PC (Your Local Machine)

1. On your local laptop/PC, clone the repository and navigate to the project directory:
   ```bash
   git clone https://github.com/djtvyutube/https_ssh_tunnel.git
   cd https_ssh_tunnel
   ```
2. Create a virtual environment and install requirements:
   * **Linux / macOS:**
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     pip install -r requirements.txt
     ```
   * **Windows (PowerShell):**
     ```powershell
     python -m venv venv
     .\venv\Scripts\Activate.ps1
     pip install -r requirements.txt
     ```
3. Start the client bridge:
   ```bash
   python3 ssh.py --mode client \
     --relay-url "https://your-domain.com/ssh/api.php" \
     --token "your_super_strong_random_token_here" \
     --port 2222
   ```
   *(The client opens a local listening port on `127.0.0.1:2222`).*

---

### Step 4: Connect via SSH / SFTP

Open a new terminal window on your local PC and connect directly through the local bridge port:

```bash
# Interactive SSH shell
ssh <remote_user>@127.0.0.1 -p 2222

# SCP file upload
scp -P 2222 ./local_file.tar.gz <remote_user>@127.0.0.1:/home/<remote_user>/

# SCP file download
scp -P 2222 <remote_user>@127.0.0.1:/var/log/syslog ./syslog_backup.log
```

---

## Command-Line Arguments Reference

| Option | Flag | Description | Default |
| :--- | :--- | :--- | :--- |
| **Mode** | `--mode` | Operation mode: `client`, `server`, or `test` | `client` |
| **Relay URL** | `--relay-url` | Full HTTPS endpoint of `api.php` | `RELAY_URL` environment variable |
| **Token** | `--token` | Pre-shared authentication key | `RELAY_TOKEN` environment variable |
| **Port** | `--port` | Local listen port (client) or target SSH port (server) | `2222` (client) / `22` (server) |
| **SSH Host** | `--ssh-host` | Target host IP for SSH service (server mode) | `127.0.0.1` |
| **Debug** | `--debug` | Enable detailed packet sequence, latency, and throughput logging | `False` |

---

## Production Security Best Practices

1. **Mandatory HTTPS (TLS 1.2 / 1.3)**: Always serve `api.php` behind an active SSL/TLS certificate. Standard TLS ensures that all data payloads traveling through public infrastructure remain fully encrypted.
2. **Cryptographically Secure Tokens**: Generate high-entropy keys using `openssl rand -hex 32` for the shared authentication secret.
3. **SSH Key Authentication**: Disable password authentication on the target machine's `/etc/ssh/sshd_config` (`PasswordAuthentication no`) and use standard public key cryptography (`~/.ssh/authorized_keys`).
4. **Data Buffer Hardening**: Restrict direct HTTP access to the `.relay_data/` directory created by `api.php` so unauthenticated users cannot access queue chunks.
5. **IP Filtering / WAF Rules**: When feasible, restrict access to `api.php` via Cloudflare, Nginx, or `.htaccess` to only allow requests originating from your trusted ISP or IP ranges.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
