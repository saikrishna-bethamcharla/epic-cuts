"""Fast content fingerprints for cache keys and the Cut List.

Hashing a multi-gigabyte source on every run is wasted work: the analysis cache
only needs to notice that a file changed. The default fingerprint combines the
file size, its modification time and a BLAKE2b hash of the first and last 4 MiB.
``--full-hash`` switches to a full SHA-256 when a run needs content identity
that survives a copy or an mtime change.

Neither mode is a substitute for verifying a file's integrity: the fast mode
deliberately cannot see edits that only touch the middle of a large file.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from autocut.errors import InputError

FAST_WINDOW_BYTES = 4 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024


def _full_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def file_fingerprint(path: Path, *, full_hash: bool = False) -> str:
    """Identify a file cheaply (default) or by full content (``full_hash``)."""
    target = Path(path)
    try:
        stat = target.stat()
    except OSError as exc:
        raise InputError(f"cannot read {target}: {exc}") from exc

    if full_hash:
        try:
            return f"sha256:{_full_sha256(target)}"
        except OSError as exc:
            raise InputError(f"cannot read {target}: {exc}") from exc

    digest = hashlib.blake2b(digest_size=16)
    try:
        with target.open("rb") as handle:
            digest.update(handle.read(FAST_WINDOW_BYTES))
            if stat.st_size > FAST_WINDOW_BYTES:
                handle.seek(max(FAST_WINDOW_BYTES, stat.st_size - FAST_WINDOW_BYTES))
                digest.update(handle.read(FAST_WINDOW_BYTES))
    except OSError as exc:
        raise InputError(f"cannot read {target}: {exc}") from exc

    return f"fast:{stat.st_size}:{stat.st_mtime_ns}:{digest.hexdigest()}"
