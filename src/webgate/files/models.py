from pydantic import BaseModel


class FileEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int
    permissions: str
    owner: str
    group: str
    modified: str


class DirectoryListing(BaseModel):
    path: str
    entries: list[FileEntry]


class FileWriteRequest(BaseModel):
    path: str
    content: str


class MkdirRequest(BaseModel):
    path: str


class RenameRequest(BaseModel):
    old_path: str
    new_path: str


class ChmodRequest(BaseModel):
    path: str
    mode: str


class CopyToServerRequest(BaseModel):
    """Move a file between two hosts without it going via somebody's laptop."""

    source_path: str
    target_server_id: int
    target_path: str
