"""Range-capable file serving for audio.

The player seeks, and a browser that cannot ask for a byte range has to
download a whole take before it can play the middle of it.
"""
import os
import re

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

CHUNK = 64 * 1024
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")

MIME = {".wav": "audio/wav", ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
        ".flac": "audio/flac", ".ogg": "audio/ogg", ".mp4": "audio/mp4"}


def content_type(path):
    return MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def serve(path, request: Request, filename=None, download=False):
    if not path or not os.path.isfile(path):
        raise HTTPException(404, "audio not found")

    size = os.path.getsize(path)
    media_type = content_type(path)
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-cache"}
    if filename:
        disposition = "attachment" if download else "inline"
        headers["Content-Disposition"] = f'{disposition}; filename="{filename}"'

    raw = request.headers.get("range")
    if not raw:
        return FileResponse(path, media_type=media_type, headers=headers)

    match = _RANGE.match(raw.strip())
    if not match:
        return FileResponse(path, media_type=media_type, headers=headers)

    start_s, end_s = match.groups()
    if start_s:
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    else:                                   # suffix range: last N bytes
        length = int(end_s or 0)
        start = max(size - length, 0)
        end = size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

    headers.update({
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(end - start + 1),
    })
    return StreamingResponse(_read(path, start, end), status_code=206,
                             media_type=media_type, headers=headers)


def _read(path, start, end):
    with open(path, "rb") as fh:
        fh.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = fh.read(min(CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data
