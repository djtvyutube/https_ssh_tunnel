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
