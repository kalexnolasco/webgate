# Servers API

All endpoints require authentication. Server CRUD operations require admin role.

## List Servers

```
GET /api/servers?group=production&search=web&tag=nginx
```

Returns servers filtered by the user's allowed groups. Admin sees all.

## Create Server (Admin)

```
POST /api/servers
```

```json title="Request"
{
  "name": "prod-web-01",
  "hostname": "10.0.1.50",
  "port": 22,
  "username": "deploy",
  "auth_method": "password",
  "password": "secret",
  "group": "production",
  "tags": ["web", "nginx"],
  "description": "Primary web server"
}
```

## Get Server

```
GET /api/servers/{id}
```

## Update Server (Admin)

```
PUT /api/servers/{id}
```

Only send the fields you want to update.

## Delete Server (Admin)

```
DELETE /api/servers/{id}
```

## Test Connectivity

```
POST /api/servers/{id}/test
```

```json title="Response"
{ "success": true, "message": "Connection successful" }
```

## Groups

```
GET /api/servers/groups
```

Returns distinct group names. Filtered by user's access.

## Import (Admin)

```
POST /api/servers/import
```

```json title="Request"
{ "servers": [ { "name": "...", "hostname": "...", ... } ] }
```

## Export (Admin)

```
GET /api/servers/export
```

Returns all servers as JSON (credentials excluded).
