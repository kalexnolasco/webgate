# Authentication API

## Login

```
POST /api/auth/login
```

Rate limited: 10 requests/minute per IP.

```json title="Request"
{ "username": "admin", "password": "secret" }
```

```json title="Response 200"
{ "access_token": "eyJ...", "token_type": "bearer" }
```

## Current User

```
GET /api/auth/me
Authorization: Bearer <token>
```

```json title="Response 200"
{
  "id": 1,
  "username": "admin",
  "is_admin": true,
  "must_change_password": false,
  "allowed_groups": []
}
```

## Change Password

```
POST /api/auth/change-password
Authorization: Bearer <token>
```

Rate limited: 5 requests/minute.

```json title="Request"
{ "new_password": "newsecret" }
```

## User Management (Admin Only)

### List Users

```
GET /api/auth/users
```

### Create User

```
POST /api/auth/users
```

```json title="Request"
{
  "username": "alice",
  "password": "alicepass",
  "allowed_groups": ["production", "staging"]
}
```

### Update User Groups

```
PUT /api/auth/users/{user_id}/groups
```

```json title="Request"
{ "allowed_groups": ["production"] }
```

### Reset User Password

```
PUT /api/auth/users/{user_id}/password
```

```json title="Request"
{ "username": "alice", "password": "newpass" }
```

### Delete User

```
DELETE /api/auth/users/{user_id}
```

!!! note
    The admin account cannot be deleted.

## Audit Log (Admin Only)

```
GET /api/auth/audit?limit=100&offset=0&username=alice&action=login
```

Returns a list of audit entries with timestamp, user, action, detail, and IP address.
