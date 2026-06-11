"""Ownership map (PRD §4.9): per-file hashes and per-key managed/user ownership.

This is the data structure; the detection/reconciliation logic lives in
flowdesk.foam.ownership (it needs foamlib).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FileOwnership(BaseModel):
    sha256: str = ""  # hash of the file as FlowDesk last wrote it
    user_keys: list[str] = Field(default_factory=list)  # top-level keys the user owns
    detached: bool = False  # FlowDesk stops writing this file entirely


class OwnershipMap(BaseModel):
    files: dict[str, FileOwnership] = Field(default_factory=dict)  # rel path -> ownership

    def is_detached(self, rel_path: str) -> bool:
        entry = self.files.get(rel_path)
        return entry.detached if entry else False

    def user_keys_for(self, rel_path: str) -> list[str]:
        entry = self.files.get(rel_path)
        return list(entry.user_keys) if entry else []
