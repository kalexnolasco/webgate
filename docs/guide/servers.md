# Server Management

## Adding Servers

Only **admin** users can add servers. Click **New Server** and fill in the connection details.

### Authentication Methods

| Method | Fields | Use Case |
|--------|--------|----------|
| **Password** | Password field | Simple setups |
| **Private Key** | Upload or paste key | Production servers, key-only auth |

Servers with key authentication show a :key: icon in the server list.

### Groups

Groups organize servers and control user access. Examples:

- `production` -- production servers
- `staging` -- staging/QA environment  
- `development` -- dev machines
- `client-acme` -- client-specific servers

!!! info "Groups = Access Control"
    When you create a user, you assign which groups they can see. A user with `allowed_groups: ["staging"]` will only see servers in the `staging` group.

### Tags

Tags are labels for filtering (e.g., `web`, `database`, `redis`). They don't affect access control.

## Import / Export

Admin can bulk import/export servers as JSON:

- **Export** (arrow down button) -- downloads all servers as `webgate-servers.json`
- **Import** (arrow up button) -- uploads a JSON file with server definitions

```json title="webgate-servers.json"
[
  {
    "name": "web-01",
    "hostname": "10.0.1.10",
    "port": 22,
    "username": "deploy",
    "auth_method": "password",
    "password": "secret",
    "group": "production",
    "tags": ["web", "nginx"]
  }
]
```

!!! warning "Credentials in exports"
    Exported JSON does **not** include passwords or private keys. You'll need to re-enter them after import.

## Testing Connectivity

Click **Test** on any server to verify SSH connectivity. This performs a quick connect/disconnect handshake.

## Quick Connect

The toolbar at the top provides a **Quickconnect** bar (like FileZilla) for one-off connections without saving:

1. Enter host, username, password, port
2. Click **Quickconnect**
3. A terminal opens immediately
