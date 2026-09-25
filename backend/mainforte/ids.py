from __future__ import annotations

import ulid


def new_id() -> str:
    """Time-sortable 26-char ULID. Used for every primary key and every event id."""
    return str(ulid.new())
