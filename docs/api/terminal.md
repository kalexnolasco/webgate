# Terminal API (WebSocket)

## SSH to Saved Server

```
WS /api/ws/terminal/{server_id}?token=<jwt>
```

The client sends an initial JSON message with terminal size:

```json title="First message"
{ "cols": 80, "rows": 24 }
```

After that, the WebSocket carries raw terminal I/O:

- **Client -> Server**: keystrokes (text frames)
- **Server -> Client**: terminal output (text frames)

### Resize

Send a JSON message at any time:

```json
{ "type": "resize", "cols": 120, "rows": 40 }
```

## Quick Connect

```
WS /api/ws/terminal/quick?token=<jwt>
```

First message includes connection details:

```json title="First message"
{
  "host": "10.0.1.50",
  "port": 22,
  "username": "deploy",
  "password": "secret",
  "cols": 80,
  "rows": 24
}
```

## Error Handling

If SSH connection fails, the server sends:

```json
{ "type": "error", "message": "SSH connection failed: ..." }
```

Then closes the WebSocket with code `1011`.

## Authentication

WebSocket authentication uses a JWT token in the query string. If invalid, the connection closes with code `4001`.
