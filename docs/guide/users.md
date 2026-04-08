# User Management

## Roles

| Role | Capabilities |
|------|-------------|
| **Admin** | Full access: manage servers, users, view audit log |
| **User** | SSH/SFTP to servers in their allowed groups only |

## Default Admin

On first launch, webgate creates a default admin account:

- **Username:** `admin`
- **Password:** `admin`

!!! warning
    You must change this password on first login. The app will block all access until the password is changed.

## Creating Users

1. Login as admin
2. Click **Users** in the top bar
3. Fill in Username, Password, and Groups
4. Click **Add**

### Groups Assignment

Groups control which servers a user can see:

```mermaid
flowchart LR
    ADMIN["Admin"] -->|creates| S1["web-01 (production)"]
    ADMIN -->|creates| S2["web-02 (production)"]
    ADMIN -->|creates| S3["stg-01 (staging)"]
    ADMIN -->|creates| ALICE["alice
    groups: production, staging"]
    ADMIN -->|creates| BOB["bob
    groups: staging"]

    ALICE -->|sees| S1 & S2 & S3
    BOB -->|sees| S3

    style ADMIN fill:#5cb85c,stroke:#449d44,color:#fff
    style ALICE fill:#e8f0fe,stroke:#4a90d9
    style BOB fill:#fff3e0,stroke:#ff9800
```

## Editing Groups

Click **Groups** on any user in the User Management panel to change their allowed groups. You can:

- Type group names separated by commas
- Click available group buttons to toggle them

## Audit Log

Admin can view all user actions by clicking **Audit** in the top bar:

- Login events
- SSH connections
- Server changes
- Timestamps and IP addresses
