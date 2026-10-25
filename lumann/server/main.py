#!/usr/bin/env python3
"""Lumann Soundsystem — local web app for producing and repairing TTS audiobooks.

    python lumann/server/main.py            # http://127.0.0.1:8420
    python lumann/server/main.py --port 9000 --reload

localhost only, single user, no auth. Serves the API and the built Vite app
from one process; run `npm run dev` in lumann/web for frontend hot reload.
"""
import argparse
import asyncio
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_LUMANN = os.path.dirname(_HERE)
if _LUMANN not in sys.path:
    sys.path.insert(0, _LUMANN)

from contextlib import asynccontextmanager                       # noqa: E402

from fastapi import FastAPI                                      # noqa: E402
from fastapi.responses import FileResponse, JSONResponse         # noqa: E402
from fastapi.staticfiles import StaticFiles                      # noqa: E402

from server.api import (compose_api, events_api, projects_api,   # noqa: E402
                        recording_api, segments_api, voices_api)
from server.core import espeak, paths, voices                    # noqa: E402
from server.jobs.events import bus                               # noqa: E402
from server.jobs.runner import runner                            # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    paths.ensure_dirs()
    voices.ensure_builtin()
    bus.bind(asyncio.get_running_loop())
    restored = runner.restore()
    if restored:
        print(f"  {restored} segment(s) still queued from a previous run — "
              f"press Record to resume", flush=True)
    yield
    runner.shutdown()


app = FastAPI(title="Lumann Soundsystem", lifespan=lifespan)

for module in (projects_api, segments_api, recording_api, compose_api, events_api,
               voices_api):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    return {"ok": True, "projects": paths.PROJECTS_DIR, "worker": runner.state()}


if os.path.isdir(paths.WEB_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(paths.WEB_DIST, "assets")),
              name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        """Serve the built app, letting the client router own every path."""
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        candidate = os.path.join(paths.WEB_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(paths.WEB_DIST, "index.html"))
else:
    @app.get("/")
    def no_build():
        return JSONResponse({
            "detail": "frontend not built",
            "fix": "cd lumann/web && npm install && npm run build",
        }, status_code=503)


def main():
    import uvicorn

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()

    print("  Lumann Soundsystem")
    print(f"  open      http://{args.host}:{args.port}")
    print(f"  projects  {paths.PROJECTS_DIR}")
    if os.environ.get("LUMANN_FAKE_TTS") == "1":
        print("  FAKE TTS  generating silence, no engine will be used")
    elif espeak.available():
        print(f"  espeak-ng {espeak.binary()}")
    else:
        print("  espeak-ng NOT FOUND — the built-in voices will not work.")
        print("            Install it: https://github.com/espeak-ng/espeak-ng")
    sys.stdout.flush()              # before uvicorn takes over; matters when piped
    uvicorn.run("server.main:app" if args.reload else app,
                host=args.host, port=args.port, reload=args.reload,
                app_dir=_LUMANN if args.reload else None, log_level="warning")


if __name__ == "__main__":
    main()
