"""Local web server: JSON API plus the dashboard's static files."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

import requests
import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import downloader as dl
from . import instagram as ig

STATIC_DIR = Path(__file__).resolve().parent / "static"

settings = dl.Settings()
manager = dl.JobManager(settings)
app = FastAPI(title="TubeDrop", docs_url=None, redoc_url=None)


@app.middleware("http")
async def local_only(request: Request, call_next):
    """Only answer requests addressed to this machine and sent by this dashboard."""
    host = (request.headers.get("host") or "").split(":")[0]
    if host not in ("127.0.0.1", "localhost"):
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and request.method != "GET":
        origin_host = origin.split("://")[-1].split(":")[0]
        if origin_host not in ("127.0.0.1", "localhost"):
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# --------------------------------------------------------------------------- models


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    noplaylist: bool = False


class DownloadItem(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    title: str | None = None
    thumbnail: str | None = None
    duration: float | None = None
    uploader: str | None = None
    index: int | None = None
    # Instagram items only
    media_url: str | None = Field(default=None, max_length=4000)
    kind: Literal["video", "photo"] | None = None
    ext: str | None = Field(default=None, max_length=5)
    file_stem: str | None = Field(default=None, max_length=200)


class DownloadRequest(BaseModel):
    items: list[DownloadItem] = Field(min_length=1, max_length=5000)
    mode: Literal["audio", "video"]
    quality: str
    playlist_title: str | None = None
    number_files: bool = False
    source: Literal["youtube", "instagram"] = "youtube"


class SettingsUpdate(BaseModel):
    download_dir: str | None = None
    max_concurrent: int | None = None
    embed_thumbnail: bool | None = None
    embed_metadata: bool | None = None
    instagram_cookies: str | None = None


class PathRequest(BaseModel):
    path: str | None = None


def _require_web_url(url: str) -> str:
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "Please paste a full link starting with https://")
    return url


# --------------------------------------------------------------------------- routes


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {
        "ytdlp_version": yt_dlp.version.__version__,
        "ffmpeg": bool(dl.find_ffmpeg()),
        "download_dir": str(settings.download_dir),
        "instagram_login": settings.instagram_cookies is not None,
    }


def _analyze_instagram(url: str) -> dict:
    cookies = settings.instagram_cookies
    try:
        return ig.analyze(url, cookies)
    except ig.InstagramError as problem:
        # Reels and video posts have a second route through yt-dlp, which sometimes works without a login.
        try:
            kind = ig.classify(url)["kind"]
        except ig.InstagramError:
            kind = None
        if kind in ("reel", "post"):
            try:
                return dl.analyze(url, True, cookies)
            except ValueError:
                pass
        raise HTTPException(422, str(problem)) from problem


@app.post("/api/analyze")
def analyze(body: AnalyzeRequest):
    url = _require_web_url(body.url)
    if ig.is_instagram(url):
        return _analyze_instagram(url)
    try:
        return dl.analyze(url, body.noplaylist)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _instagram_items(body: DownloadRequest) -> list[dict]:
    """Check Instagram items before queueing: real media links only, safe names."""
    items = []
    for item in body.items:
        if not item.media_url or not ig.is_media_url(item.media_url):
            raise HTTPException(400, "That is not an Instagram media link. Fetch the post again.")
        kind = item.kind or "video"
        if body.mode == "audio" and kind == "photo":
            continue  # nothing to convert
        allowed_ext = ("jpg", "jpeg", "png", "webp", "heic") if kind == "photo" else ("mp4", "mov", "webm")
        ext = (item.ext or "").lower().lstrip(".")
        items.append({
            "source": "instagram",
            "kind": kind,
            "url": _require_web_url(item.url),
            "media_url": item.media_url,
            "media_ext": ext if ext in allowed_ext else allowed_ext[0],
            "file_stem": item.file_stem,
            "title": item.title,
            "thumbnail": item.thumbnail if item.thumbnail and ig.is_media_url(item.thumbnail) else None,
            "uploader": item.uploader,
        })
    if not items:
        raise HTTPException(400, "Only videos can be saved as MP3, and none were selected.")
    return items


@app.post("/api/download")
def download(body: DownloadRequest):
    if body.source == "instagram":
        if body.mode == "audio" and body.quality not in dl.AUDIO_QUALITIES:
            raise HTTPException(400, "Unsupported quality option.")
        quality = body.quality if body.mode == "audio" else "best"
        ids = manager.add(_instagram_items(body), body.mode, quality)
        return {"queued": len(ids), "ids": ids}

    allowed = dl.AUDIO_QUALITIES if body.mode == "audio" else dl.VIDEO_QUALITIES
    if body.quality not in allowed:
        raise HTTPException(400, "Unsupported quality option.")
    items = []
    for item in body.items:
        data = item.model_dump()
        data["url"] = _require_web_url(item.url)
        items.append(data)
    ids = manager.add(items, body.mode, body.quality, body.playlist_title, body.number_files)
    return {"queued": len(ids), "ids": ids}


@app.get("/api/jobs")
def jobs():
    return manager.snapshot()


@app.post("/api/jobs/clear")
def clear_jobs():
    return {"removed": manager.clear_finished()}


@app.post("/api/jobs/cancel-all")
def cancel_all():
    return {"cancelled": manager.cancel_all()}


@app.post("/api/jobs/retry-failed")
def retry_failed():
    return {"retried": manager.retry_failed()}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not manager.cancel(job_id):
        raise HTTPException(404, "Download not found.")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str):
    if not manager.retry(job_id):
        raise HTTPException(409, "Only failed or cancelled downloads can be retried.")
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def remove_job(job_id: str):
    if not manager.remove(job_id):
        raise HTTPException(409, "Cancel the download before removing it.")
    return {"ok": True}


@app.get("/api/library")
def library():
    files = dl.list_library(settings.download_dir)
    return {
        "files": files,
        "total_size": sum(f["size"] for f in files),
        "audio_count": sum(1 for f in files if f["kind"] == "audio"),
        "video_count": sum(1 for f in files if f["kind"] == "video"),
        "image_count": sum(1 for f in files if f["kind"] == "image"),
        "download_dir": str(settings.download_dir),
    }


def _library_file(rel: str) -> Path:
    try:
        target = dl.resolve_in_library(settings.download_dir, rel)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    if not target.is_file() or target.suffix.lower() not in dl.LIBRARY_EXTENSIONS:
        raise HTTPException(404, "File not found.")
    return target


THUMB_LIMIT = 8 * 1024 * 1024


@app.get("/api/thumb")
def thumbnail(url: str):
    """Relay an Instagram preview image. Their servers refuse to show images inside other pages."""
    if not ig.is_media_url(url):
        raise HTTPException(400, "Only Instagram media links can be previewed.")
    try:
        with requests.get(url, stream=True, timeout=(10, 20),
                          headers={"User-Agent": dl.DIRECT_USER_AGENT}) as upstream:
            content_type = upstream.headers.get("content-type", "")
            if upstream.status_code != 200 or not content_type.startswith("image/"):
                raise HTTPException(404, "Preview not available.")
            data = b""
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                data += chunk
                if len(data) > THUMB_LIMIT:
                    raise HTTPException(413, "Preview is too large.")
    except requests.RequestException as exc:
        raise HTTPException(502, "Preview not available.") from exc
    return Response(data, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})


@app.delete("/api/library")
def delete_file(path: str):
    target = _library_file(path)
    try:
        from send2trash import send2trash
        send2trash(str(target))
        return {"ok": True, "recycled": True}
    except ImportError:
        target.unlink()
        return {"ok": True, "recycled": False}
    except OSError as exc:
        raise HTTPException(500, f"Could not delete the file: {exc}") from exc


@app.get("/media/{path:path}")
def media(path: str):
    return FileResponse(_library_file(path))


@app.post("/api/open")
def open_location(body: PathRequest):
    """Open the download folder in Explorer, or highlight one file inside it."""
    root = settings.download_dir
    root.mkdir(parents=True, exist_ok=True)
    if body.path:
        candidate = Path(body.path)
        try:
            target = dl.resolve_in_library(root, body.path if not candidate.is_absolute() else str(candidate))
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc
        if target.is_file():
            subprocess.Popen(["explorer", "/select,", str(target)])
            return {"ok": True}
        if target.is_dir():
            os.startfile(str(target))  # noqa: S606 - opening a folder we own
            return {"ok": True}
    os.startfile(str(root))  # noqa: S606
    return {"ok": True}


def _settings_view() -> dict:
    """Settings for the dashboard. Only the cookies file's path is shared, never its contents."""
    return settings.data | {"instagram_connected": settings.instagram_cookies is not None}


@app.get("/api/settings")
def get_settings():
    return _settings_view()


@app.post("/api/settings")
def update_settings(body: SettingsUpdate):
    try:
        settings.update(body.model_dump(exclude_none=True))
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    manager._pump()
    return _settings_view()


def _native_dialog(script: str) -> str | None:
    """Run a small tkinter dialog on this PC and return what the user picked."""
    env = os.environ | {"PYTHONIOENCODING": "utf-8"}
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, encoding="utf-8", timeout=300, env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(500, "The file picker is unavailable. Type the path instead.") from exc
    if result.returncode != 0:
        raise HTTPException(500, "The file picker is unavailable. Type the path instead.")
    chosen = result.stdout.strip()
    return str(Path(chosen)) if chosen else None


_COOKIE_PICKER = (
    "import tkinter as tk\n"
    "from tkinter import filedialog\n"
    "root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)\n"
    "print(filedialog.askopenfilename(title='Choose your Instagram cookies file',"
    " filetypes=[('Cookies file', '*.txt'), ('All files', '*.*')]) or '')\n"
)


@app.post("/api/pick-cookies")
def pick_cookies():
    """Show a native file picker for the Instagram cookies file and return the chosen path."""
    return {"path": _native_dialog(_COOKIE_PICKER)}


_PICKER = (
    "import tkinter as tk\n"
    "from tkinter import filedialog\n"
    "root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)\n"
    "print(filedialog.askdirectory(title='Choose download folder') or '')\n"
)


@app.post("/api/pick-folder")
def pick_folder():
    """Show a native folder picker on this PC and return the chosen path."""
    return {"path": _native_dialog(_PICKER)}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
