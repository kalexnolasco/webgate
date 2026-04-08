# webgate

**Self-hosted SSH terminal & SFTP file browser for remote server management.**

Deploy on a single gateway server and give your entire team browser-based access to every machine in the network -- no VPN, no local SSH clients, no credential files.

## Key Features

- **SSH Web Terminal** -- xterm.js powered terminal in your browser
- **SFTP File Browser** -- navigate, upload, download, edit files remotely
- **Server Registry** -- save servers with groups, tags, encrypted credentials
- **User Management** -- admin creates users and controls access by group
- **Split View** -- terminal + file browser side by side
- **Audit Log** -- track who did what and when
- **Docker Ready** -- single command to deploy

## Architecture

```mermaid
flowchart TB
    subgraph internet ["Your Team"]
        B1["Browser 1"]
        B2["Browser 2"]
        B3["Browser 3"]
    end

    subgraph gateway ["Gateway Server"]
        WG["webgate :443"]
    end

    subgraph servers ["Internal Network"]
        S1["Server 1"]
        S2["Server 2"]
        S3["Server 3"]
        S4["Server N"]
    end

    B1 & B2 & B3 -- "HTTPS" --> WG
    WG -- "SSH/SFTP" --> S1 & S2 & S3 & S4

    style internet fill:#e8f0fe,stroke:#4a90d9
    style gateway fill:#f0f9e8,stroke:#5cb85c
    style servers fill:#fff3e0,stroke:#ff9800
    style WG fill:#5cb85c,stroke:#449d44,color:#fff
```

## Quick Install

```bash
git clone https://github.com/kalexnolasco/webgate.git
cd webgate
docker compose up -d
# Open http://localhost:8443 -- login: admin / admin
```

!!! warning "First Login"
    The default password `admin` must be changed on first login.

## Next Steps

- [Installation](getting-started/installation.md) -- all deployment options
- [Quick Start](getting-started/quickstart.md) -- step-by-step first use guide
- [Server Management](guide/servers.md) -- adding and organizing servers
