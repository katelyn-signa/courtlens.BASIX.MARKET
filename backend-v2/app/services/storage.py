"""Private local file storage (no public directory, generated names, traversal-safe)."""

import hashlib
import os
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Optional

from app.core.exceptions import FileTooLargeError, InvalidInputError, UnsupportedFileTypeError

_SIGNATURES = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".tif": (b"II*\x00", b"MM\x00*"),
    ".tiff": (b"II*\x00", b"MM\x00*"),
    ".docx": (b"PK\x03\x04",),
}
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,254}$")
_CHUNK = 64 * 1024


def safe_display_name(name: str) -> str:
    """Strip any path components and control characters from a client-supplied filename."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip().strip(".")
    return (base[:200] or "unnamed")


def validate_storage_key(key: str) -> str:
    if not _KEY_RE.match(key) or ".." in PurePosixPath(key).parts or "//" in key:
        raise InvalidInputError("storage_key must be a relative key without '..' segments.")
    return key


class LocalFileStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def resolve(self, storage_key: str) -> Path:
        validate_storage_key(storage_key)
        path = (self.root / storage_key).resolve()
        if not path.is_relative_to(self.root):
            raise InvalidInputError("storage_key escapes the storage directory.")
        return path

    def content_path_if_present(self, storage_key: Optional[str]) -> Optional[str]:
        if not storage_key:
            return None
        try:
            path = self.resolve(storage_key)
        except InvalidInputError:
            return None
        return str(path) if path.is_file() else None

    def save_stream(self, case_id: str, original_name: str, stream: BinaryIO, *,
                    allowed_extensions: list[str], max_bytes: int) -> tuple[str, str, int]:
        """Validate and store an upload. Returns (storage_key, sha256, size_bytes)."""
        ext = os.path.splitext(safe_display_name(original_name))[1].lower()
        if ext not in allowed_extensions:
            raise UnsupportedFileTypeError(f"File extension {ext or '(none)'!r} is not allowed.",
                                           details={"allowed": allowed_extensions})
        directory = self.root / case_id
        directory.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}{ext}"
        final, tmp = directory / stored_name, directory / f".{stored_name}.part"
        digest, size, first = hashlib.sha256(), 0, b""
        try:
            with open(tmp, "wb") as out:
                while True:
                    chunk = stream.read(_CHUNK)
                    if not chunk:
                        break
                    if not first:
                        first = chunk[:16]
                        sigs = _SIGNATURES.get(ext)
                        if sigs and not any(first.startswith(s) for s in sigs):
                            raise UnsupportedFileTypeError(
                                "File content does not match its extension.")
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileTooLargeError(f"File exceeds {max_bytes} bytes.",
                                                details={"max_bytes": max_bytes})
                    digest.update(chunk)
                    out.write(chunk)
            if size == 0:
                raise InvalidInputError("Uploaded file is empty.")
            os.replace(tmp, final)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return f"{case_id}/{stored_name}", digest.hexdigest(), size
