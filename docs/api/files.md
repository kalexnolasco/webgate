# Files API (SFTP)

All endpoints require authentication. The user must have access to the server's group.

## List Directory

```
GET /api/files/{server_id}/ls?path=/home/user
```

```json title="Response"
{
  "path": "/home/user",
  "entries": [
    {
      "name": "documents",
      "path": "/home/user/documents",
      "is_dir": true,
      "size": 4096,
      "permissions": "drwxr-xr-x",
      "owner": "1000",
      "group": "1000",
      "modified": "2026-04-08T10:30:00+00:00"
    }
  ]
}
```

## Read Text File

```
GET /api/files/{server_id}/read?path=/etc/hostname
```

```json title="Response"
{ "path": "/etc/hostname", "content": "my-server\n" }
```

## Download File

```
GET /api/files/{server_id}/download?path=/home/user/report.pdf
```

Returns the file as a binary response with correct MIME type.

## Upload Files

```
POST /api/files/{server_id}/upload?path=/home/user
Content-Type: multipart/form-data
```

## Write / Save File

```
PUT /api/files/{server_id}/write
```

```json title="Request"
{ "path": "/home/user/config.yml", "content": "key: value\n" }
```

## Create Directory

```
POST /api/files/{server_id}/mkdir
```

```json title="Request"
{ "path": "/home/user/new-folder" }
```

## Rename / Move

```
POST /api/files/{server_id}/rename
```

```json title="Request"
{ "old_path": "/home/user/old.txt", "new_path": "/home/user/new.txt" }
```

## Delete

```
DELETE /api/files/{server_id}/delete?path=/home/user/temp.txt
```

## Change Permissions

```
POST /api/files/{server_id}/chmod
```

```json title="Request"
{ "path": "/home/user/script.sh", "mode": "755" }
```

## File Metadata

```
GET /api/files/{server_id}/stat?path=/home/user/file.txt
```
