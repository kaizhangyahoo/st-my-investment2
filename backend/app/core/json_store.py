"""The write half of a JSON-file store: replace the file or leave it exactly as it was.

A plain `open(path, "w")` truncates before it writes, so a crash, a full disk or a serialisation
error partway through leaves a truncated file -- and these files are read by a second process
(the legacy Streamlit app), which would then parse the wreckage. Writing a sibling temp file and
renaming it over the target makes the swap atomic: a reader sees either the old file or the new
one. The temp file must live in the *same directory* for the rename to stay within one
filesystem, which is also why the data directory is bind-mounted as a directory in Compose
rather than file by file.

Raises `OSError` rather than logging, because what to say and what to do about it differ per
store -- a lost FX close is re-fetched, a lost portfolio value is recomputed.
"""
import json
import os
import tempfile
from typing import Any


def write_json_atomically(path: str, data: Any, *, prefix: str) -> None:
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
