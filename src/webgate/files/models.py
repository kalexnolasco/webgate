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
