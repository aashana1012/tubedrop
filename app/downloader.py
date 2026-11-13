"""Download engine: settings, URL analysis and a threaded job queue around yt-dlp."""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadCancelled, sanitize_filename

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.json"
DEFAULT_DOWNLOAD_DIR = BASE_DIR / "downloads"

AUDIO_QUALITIES = ("320", "256", "192", "128")
VIDEO_QUALITIES = ("best", "4320", "2160", "1440", "1080", "720", "480", "360")
MEDIA_EXTENSIONS = {".mp3", ".m4a", ".opus", ".mp4", ".mkv", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".opus"}
HISTORY_LIMIT = 300

ACTIVE_STATES = {"fetching", "downloading", "processing"}
FINISHED_STATES = {"done", "error", "cancelled"}

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# What follows the title in yt-dlp's working files: "Title.f137.mp4.part", "Title.jpg", ...
_TEMP_SUFFIX = re.compile(
    r"(\.f\d+)?(\.temp)?\.(jpg|jpeg|png|webp|webm|m4a|mp4|mkv|opus)(\.part|\.ytdl)?",
    re.IGNORECASE,
)

POSTPROCESSOR_LABELS = {
    "ExtractAudio": "Converting to MP3",
    "Merger": "Merging video and audio",
    "VideoRemuxer": "Finalizing MP4",
    "Metadata": "Writing tags",
    "ThumbnailsConvertor": "Preparing cover art",
    "EmbedThumbnail": "Embedding cover art",
    "MoveFiles": "Finishing up",
}


def clean_error(exc: BaseException | str) -> str:
    text = _ANSI.sub("", str(exc)).strip()
    text = re.sub(r"^ERROR:\s*", "", text)
    text = re.sub(r"^\[[\w:+-]+\]\s*[\w-]+:\s*", "", text)
    return text or "Unknown error"


def find_ffmpeg() -> str | None:
    """Return the folder holding ffmpeg, or None if it cannot be found."""
    local = BASE_DIR / "bin" / "ffmpeg.exe"
    if local.exists():
        return str(local.parent)
    found = shutil.which("ffmpeg")
    return str(Path(found).parent) if found else None


class _QuietLogger:
    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


# --------------------------------------------------------------------------- settings


class Settings:
    DEFAULTS: dict[str, Any] = {
        "download_dir": str(DEFAULT_DOWNLOAD_DIR),
        "max_concurrent": 3,
        "embed_thumbnail": True,
        "embed_metadata": True,
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.data = dict(self.DEFAULTS)
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            self.data.update({k: v for k, v in saved.items() if k in self.DEFAULTS})
        except (OSError, ValueError):
            pass
        self.download_dir.mkdir(parents=True, exist_ok=True)

    @property
    def download_dir(self) -> Path:
        return Path(self.data["download_dir"])

    @property
    def max_concurrent(self) -> int:
        return int(self.data["max_concurrent"])

    def update(self, changes: dict[str, Any]) -> None:
        with self._lock:
            if "download_dir" in changes:
                path = Path(str(changes["download_dir"]).strip().strip('"'))
                if not path.is_absolute():
                    raise ValueError("Download folder must be a full path, e.g. D:\\Music")
                path.mkdir(parents=True, exist_ok=True)
                self.data["download_dir"] = str(path)
            if "max_concurrent" in changes:
                self.data["max_concurrent"] = max(1, min(6, int(changes["max_concurrent"])))
            for key in ("embed_thumbnail", "embed_metadata"):
                if key in changes:
                    self.data[key] = bool(changes[key])
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- analysis


def _base_opts() -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _QuietLogger(),
        "windowsfilenames": True,
        "js_runtimes": {"deno": {}, "node": {}},
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
    }
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    return opts


def _thumb(entry: dict[str, Any]) -> str | None:
    if entry.get("thumbnail"):
        return entry["thumbnail"]
    thumbs = entry.get("thumbnails") or []
    if thumbs:
        return thumbs[-1].get("url")
    if entry.get("id") and (entry.get("ie_key") or entry.get("extractor_key") or "").lower() == "youtube":
        return f"https://i.ytimg.com/vi/{entry['id']}/mqdefault.jpg"
    return None


def analyze(url: str, noplaylist: bool = False) -> dict[str, Any]:
    """Look up a URL and describe it as a single video or a playlist."""
    opts = _base_opts() | {
        "extract_flat": "in_playlist",
        "noplaylist": noplaylist,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # yt-dlp raises many types
        raise ValueError(clean_error(exc)) from exc
    if not info:
        raise ValueError("Nothing found at that link.")

    if info.get("_type") == "playlist":
        entries = []
        for number, entry in enumerate(info.get("entries") or [], start=1):
            if not entry:
                continue
            title = entry.get("title") or "Untitled"
            entry_url = entry.get("url") or entry.get("webpage_url")
            if not entry_url and entry.get("id"):
                entry_url = f"https://www.youtube.com/watch?v={entry['id']}"
            if not entry_url:
                continue
            entries.append({
                "index": number,
                "id": entry.get("id"),
                "url": entry_url,
                "title": title,
                "duration": entry.get("duration"),
                "uploader": entry.get("uploader") or entry.get("channel"),
                "thumbnail": _thumb(entry),
                "unavailable": title in ("[Private video]", "[Deleted video]"),
            })
        return {
            "type": "playlist",
            "title": info.get("title") or "Playlist",
            "uploader": info.get("uploader") or info.get("channel"),
            "url": info.get("webpage_url") or url,
            "count": len(entries),
            "entries": entries,
        }

    heights = sorted(
        {f["height"] for f in info.get("formats") or [] if f.get("height") and f.get("vcodec") not in (None, "none")},
        reverse=True,
    )
    return {
        "type": "video",
        "id": info.get("id"),
        "url": info.get("webpage_url") or url,
        "title": info.get("title") or "Untitled",
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "thumbnail": _thumb(info),
        "view_count": info.get("view_count"),
        "heights": heights,
    }


# --------------------------------------------------------------------------- jobs


@dataclass
class Job:
    id: str
    url: str
    mode: str  # "audio" | "video"
    quality: str
    title: str = "Loading…"
    thumbnail: str | None = None
    duration: float | None = None
    uploader: str | None = None
    playlist_title: str | None = None
    index: int | None = None
    index_pad: int = 2
    status: str = "queued"
    stage: str = "Waiting in queue"
    progress: float = 0.0
    speed: float | None = None
    eta: float | None = None
    downloaded_bytes: int = 0
    total_bytes: int = 0
    filepath: str | None = None
    filesize: int | None = None
    error: str | None = None
    skipped: bool = False
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    PUBLIC = (
        "id", "url", "mode", "quality", "title", "thumbnail", "duration", "uploader",
        "playlist_title", "index", "index_pad", "status", "stage", "progress", "speed", "eta",
        "downloaded_bytes", "total_bytes", "filepath", "filesize", "error", "skipped",
        "created_at", "finished_at",
    )

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.PUBLIC}


class JobManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.jobs: dict[str, Job] = {}
        self.lock = threading.RLock()
        self.running = 0
        self._load_history()

    # ---- persistence

    def _load_history(self) -> None:
        try:
            saved = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for raw in saved:
            try:
                job = Job(**{k: raw.get(k) for k in Job.PUBLIC if k in raw})
            except TypeError:
                continue
            if job.status in FINISHED_STATES:
                self.jobs[job.id] = job

    def _save_history(self) -> None:
        with self.lock:
            finished = [j.to_dict() for j in self.jobs.values() if j.status in FINISHED_STATES]
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            HISTORY_FILE.write_text(json.dumps(finished[-HISTORY_LIMIT:]), encoding="utf-8")
        except OSError:
            pass

    # ---- queue operations

    def add(self, items: list[dict[str, Any]], mode: str, quality: str,
            playlist_title: str | None = None, number_files: bool = False) -> list[str]:
        ids = []
        # Pad track numbers so files sort correctly: 01..99, or 001..999 for long playlists.
        largest = max((item.get("index") or 0 for item in items), default=0)
        pad = max(2, len(str(largest)))
        with self.lock:
            # Two unfinished jobs writing the same file would collide, so skip exact repeats.
            pending = {
                (j.url, j.mode, j.playlist_title, j.index)
                for j in self.jobs.values() if j.status not in FINISHED_STATES
            }
            for item in items:
                index = item.get("index") if number_files else None
                key = (item["url"], mode, playlist_title, index)
                if key in pending:
                    continue
                pending.add(key)
                job = Job(
                    id=uuid.uuid4().hex[:12],
                    url=item["url"],
                    mode=mode,
                    quality=quality,
                    title=item.get("title") or "Loading…",
                    thumbnail=item.get("thumbnail"),
                    duration=item.get("duration"),
                    uploader=item.get("uploader"),
                    playlist_title=playlist_title,
                    index=index,
                    index_pad=pad,
                )
                self.jobs[job.id] = job
                ids.append(job.id)
        self._pump()
        return ids

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            jobs = [j.to_dict() for j in self.jobs.values()]
        stats = {"active": 0, "queued": 0, "done": 0, "failed": 0}
        for job in jobs:
            if job["status"] in ACTIVE_STATES:
                stats["active"] += 1
            elif job["status"] == "queued":
                stats["queued"] += 1
            elif job["status"] == "done":
                stats["done"] += 1
            elif job["status"] == "error":
                stats["failed"] += 1
        return {"jobs": jobs, "stats": stats}

    def cancel(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            if job.status == "queued":
                self._finish(job, "cancelled", "Cancelled")
            elif job.status in ACTIVE_STATES:
                job.cancel.set()
                job.stage = "Cancelling…"
        self._save_history()
        return True

    def cancel_all(self) -> int:
        with self.lock:
            ids = [j.id for j in self.jobs.values() if j.status == "queued" or j.status in ACTIVE_STATES]
        for job_id in ids:
            self.cancel(job_id)
        return len(ids)

    def retry(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.status not in ("error", "cancelled"):
                return False
            self._reset(job)
        self._pump()
        return True

    def retry_failed(self) -> int:
        with self.lock:
            failed = [j for j in self.jobs.values() if j.status == "error"]
            for job in failed:
                self._reset(job)
        self._pump()
        return len(failed)

    def remove(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.status in ACTIVE_STATES:
                return False
            del self.jobs[job_id]
        self._save_history()
        return True

    def clear_finished(self) -> int:
        with self.lock:
            gone = [j.id for j in self.jobs.values() if j.status in FINISHED_STATES]
            for job_id in gone:
                del self.jobs[job_id]
        self._save_history()
        return len(gone)

    # ---- internals

    @staticmethod
    def _reset(job: Job) -> None:
        job.cancel = threading.Event()
        job.status, job.stage = "queued", "Waiting in queue"
        job.progress, job.speed, job.eta = 0.0, None, None
        job.downloaded_bytes = job.total_bytes = 0
        job.error, job.finished_at, job.skipped = None, None, False

    @staticmethod
    def _finish(job: Job, status: str, stage: str, error: str | None = None) -> None:
        job.status, job.stage, job.error = status, stage, error
        job.speed = job.eta = None
        job.finished_at = time.time()

    def _pump(self) -> None:
        with self.lock:
            while self.running < self.settings.max_concurrent:
                job = next((j for j in self.jobs.values() if j.status == "queued"), None)
                if not job:
                    break
                job.status, job.stage = "fetching", "Fetching video info"
                self.running += 1
                threading.Thread(target=self._worker, args=(job,), daemon=True).start()

    def _worker(self, job: Job) -> None:
        try:
            self._run(job)
        except DownloadCancelled:
            self._finish(job, "cancelled", "Cancelled")
        except Exception as exc:
            if job.cancel.is_set():
                self._finish(job, "cancelled", "Cancelled")
            else:
                self._finish(job, "error", "Failed", clean_error(exc))
        finally:
            with self.lock:
                self.running -= 1
            self._save_history()
            self._pump()

    def _target_dir(self, job: Job) -> Path:
        folder = self.settings.download_dir / ("Music" if job.mode == "audio" else "Videos")
        if job.playlist_title:
            name = sanitize_filename(job.playlist_title, restricted=False).strip(" .") or "Playlist"
            folder = folder / name
        return folder

    def _build_opts(self, job: Job, progress_hook, pp_hook) -> dict[str, Any]:
        folder = self._target_dir(job)
        folder.mkdir(parents=True, exist_ok=True)
        prefix = f"{job.index:0{job.index_pad or 2}d} - " if job.index else ""
        # Videos carry their resolution in the name, so a 720p and a 4K copy can sit side by side.
        name = "%(title).180B.%(ext)s" if job.mode == "audio" else "%(title).180B [%(height)sp].%(ext)s"
        template = str(folder).replace("%", "%%") + "\\" + prefix + name

        opts = _base_opts() | {
            "outtmpl": template,
            "noplaylist": True,
            "overwrites": False,
            "concurrent_fragment_downloads": 4,
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [pp_hook],
        }
        postprocessors: list[dict[str, Any]] = []

        if job.mode == "audio":
            bitrate = job.quality if job.quality in AUDIO_QUALITIES else "320"
            opts["format"] = "bestaudio/best"
            postprocessors.append({"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": bitrate})
        else:
            if job.quality.isdigit():
                h = job.quality
                opts["format"] = f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
            else:
                opts["format"] = "bv*+ba/b"
            # Highest resolution first, then prefer codecs that play everywhere.
            opts["format_sort"] = ["res", "fps", "vcodec:h264", "acodec:aac"]
            opts["merge_output_format"] = "mp4"
            postprocessors.append({"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"})

        if self.settings.data["embed_metadata"]:
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True})
        if self.settings.data["embed_thumbnail"]:
            opts["writethumbnail"] = True
            postprocessors.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
            postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})

        opts["postprocessors"] = postprocessors
        return opts

    def _run(self, job: Job) -> None:
        if not find_ffmpeg():
            raise RuntimeError("ffmpeg was not found. Install it with: winget install Gyan.FFmpeg")

        streams: dict[str, tuple[int, int]] = {}
        expected_total = 0

        def progress_hook(d: dict[str, Any]) -> None:
            if job.cancel.is_set():
                raise DownloadCancelled()
            name = d.get("filename") or "?"
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                streams[name] = (d.get("downloaded_bytes") or 0, int(total))
                job.speed, job.eta = d.get("speed"), d.get("eta")
            elif d["status"] == "finished":
                size = d.get("total_bytes") or d.get("downloaded_bytes") or streams.get(name, (0, 0))[0]
                streams[name] = (size, size)
            else:
                return
            done = sum(s[0] for s in streams.values())
            total = max(expected_total, sum(s[1] for s in streams.values()))
            job.downloaded_bytes, job.total_bytes = done, total
            job.status = "downloading"
            job.stage = "Downloading"
            if total:
                job.progress = min(99.0, done / total * 100)

        def pp_hook(d: dict[str, Any]) -> None:
            if job.cancel.is_set():
                raise DownloadCancelled()
            if d["status"] == "started" and d.get("postprocessor") != "ThumbnailsConvertor":
                job.status = "processing"
                job.speed = job.eta = None
                job.progress = max(job.progress, 99.0)
                job.stage = POSTPROCESSOR_LABELS.get(d.get("postprocessor", ""), "Processing")

        opts = self._build_opts(job, progress_hook, pp_hook)
        final_ext = ".mp3" if job.mode == "audio" else ".mp4"
        target: Path | None = None

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(job.url, download=False)
                if not info:
                    raise RuntimeError("Video is unavailable.")
                if job.cancel.is_set():
                    raise DownloadCancelled()

                job.title = info.get("title") or job.title
                job.thumbnail = info.get("thumbnail") or job.thumbnail
                job.duration = info.get("duration") or job.duration
                job.uploader = info.get("uploader") or info.get("channel") or job.uploader

                parts = info.get("requested_formats") or [info]
                expected_total = sum(int(f.get("filesize") or f.get("filesize_approx") or 0) for f in parts)

                target = Path(ydl.prepare_filename(info)).with_suffix(final_ext)
                if target.exists():
                    job.filepath, job.filesize = str(target), target.stat().st_size
                    job.skipped, job.progress = True, 100.0
                    self._finish(job, "done", "Already downloaded")
                    return

                job.status, job.stage = "downloading", "Starting download"
                result = ydl.process_ie_result(info, download=True)
        except DownloadCancelled:
            self._cleanup_partials(streams, target)
            raise

        downloads = (result or {}).get("requested_downloads") or []
        final = Path(downloads[0]["filepath"]) if downloads and downloads[0].get("filepath") else target
        if final is None or not final.exists():
            raise RuntimeError("Download finished but the output file is missing.")
        job.filepath, job.filesize = str(final), final.stat().st_size
        job.progress = 100.0
        self._finish(job, "done", "Completed")

    @staticmethod
    def _cleanup_partials(streams: dict[str, tuple[int, int]], target: Path | None) -> None:
        """Remove what a cancelled download left behind: stream parts and the cover image."""
        leftovers: set[Path] = set()
        for name in streams:
            leftovers.update((Path(name), Path(name + ".part"), Path(name + ".ytdl")))
        if target is not None and target.parent.is_dir():
            prefix = target.stem
            for path in target.parent.iterdir():
                if path == target or not path.name.startswith(prefix):
                    continue
                # Only files yt-dlp itself makes for this title, never another finished download.
                if _TEMP_SUFFIX.fullmatch(path.name[len(prefix):]):
                    leftovers.add(path)
        for candidate in leftovers:
            try:
                if candidate.is_file():
                    candidate.unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------- library


def list_library(root: Path) -> list[dict[str, Any]]:
    files = []
    if not root.exists():
        return files
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rel = path.relative_to(root)
        files.append({
            "path": rel.as_posix(),
            "name": path.stem,
            "ext": path.suffix.lower().lstrip("."),
            "folder": rel.parent.as_posix() if rel.parent != Path(".") else "",
            "kind": "audio" if path.suffix.lower() in AUDIO_EXTENSIONS else "video",
            "size": stat.st_size,
            "modified": stat.st_mtime,
        })
    files.sort(key=lambda f: f["modified"], reverse=True)
    return files


def resolve_in_library(root: Path, rel: str) -> Path:
    """Resolve a library-relative path, refusing anything outside the download folder."""
    root_resolved = root.resolve()
    target = (root_resolved / rel).resolve()
    if root_resolved != target and root_resolved not in target.parents:
        raise ValueError("Path is outside the download folder.")
    return target
