"""Instagram support: recognise links and list the photos and videos behind them.

The lookup itself is done by gallery-dl, run as a separate process so a slow or
stuck request can be timed out. This module only shapes its output for the dashboard.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from yt_dlp.utils import sanitize_filename

HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com", "instagr.am"}
# Hosts Instagram serves media from. Downloads and thumbnails are limited to these.
MEDIA_HOST_SUFFIXES = (".cdninstagram.com", ".fbcdn.net")

# First path segments that are site sections, not usernames.
RESERVED = {
    "about", "accounts", "api", "challenge", "developer", "direct", "directory", "emails",
    "explore", "graphql", "legal", "locations", "press", "privacy", "reels", "session",
    "static", "web", "your_activity",
}
USERNAME = re.compile(r"[A-Za-z0-9._]{1,30}")

MESSAGE_DIRECTORY = 2
MESSAGE_URL = 3
LOOKUP_TIMEOUT = 150
MAX_ITEMS = 300

KIND_LABELS = {
    "reel": "Reel",
    "post": "Post",
    "story": "Story",
    "highlight": "Highlight",
    "avatar": "Profile picture",
}
NEEDS_LOGIN = (
    "Instagram asked for a login. Add your Instagram login cookies in Settings, then try again."
)


class InstagramError(ValueError):
    """A lookup problem worth showing to the user as-is."""


def is_instagram(url: str) -> bool:
    try:
        return (urlsplit(url).hostname or "").lower() in HOSTS
    except ValueError:
        return False


def is_media_url(url: str) -> bool:
    """True for an https link to Instagram's own media servers."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and host.endswith(MEDIA_HOST_SUFFIXES)


def classify(url: str) -> dict[str, str | None]:
    """Work out what an Instagram link points at.

    Returns the kind, the link to hand to gallery-dl, and the username when the
    link itself names one.
    """
    parts = urlsplit(url.strip())
    segments = [s for s in parts.path.split("/") if s]
    if not segments:
        raise InstagramError("Paste a link to a reel, post, story or profile, not the Instagram home page.")
    root = "https://www.instagram.com"
    head = segments[0].lower()

    def find(names: set[str]) -> int | None:
        for position, segment in enumerate(segments[:2]):
            if segment.lower() in names:
                return position
        return None

    if head == "share":
        kind = "reel" if len(segments) > 1 and segments[1].lower().startswith("reel") else "post"
        return {"kind": kind, "url": f"{root}{parts.path}", "username": None}

    if head == "s" and len(segments) > 1:
        query = f"?{parts.query}" if parts.query else ""
        return {"kind": "highlight", "url": f"{root}/s/{segments[1]}{query}", "username": None}

    if head == "stories":
        if len(segments) < 2:
            raise InstagramError("That stories link is missing the username.")
        if segments[1].lower() == "highlights":
            if len(segments) < 3 or not segments[2].isdigit():
                raise InstagramError("That highlight link is incomplete.")
            return {"kind": "highlight", "url": f"{root}/stories/highlights/{segments[2]}/", "username": None}
        username = segments[1]
        if not USERNAME.fullmatch(username):
            raise InstagramError("That stories link does not contain a valid username.")
        tail = f"{segments[2]}/" if len(segments) > 2 and segments[2].isdigit() else ""
        return {"kind": "story", "url": f"{root}/stories/{username}/{tail}", "username": username}

    position = find({"reel", "reels"})
    if position is not None and len(segments) > position + 1:
        return {"kind": "reel", "url": f"{root}/reel/{segments[position + 1]}/", "username": None}

    position = find({"p", "tv"})
    if position is not None and len(segments) > position + 1:
        return {"kind": "post", "url": f"{root}/p/{segments[position + 1]}/", "username": None}

    if head in RESERVED or not USERNAME.fullmatch(segments[0]):
        raise InstagramError("That Instagram link is not a reel, post, story or profile.")
    return {"kind": "avatar", "url": f"{root}/{segments[0]}/avatar/", "username": segments[0]}


def _friendly_error(stderr: str, errors: list[str], has_cookies: bool) -> str:
    text = " ".join(errors + [stderr]).lower()
    login_hints = ("login", "401", "403", "redirect", "sessionid", "authrequired", "authentication", "checkpoint")
    if any(hint in text for hint in login_hints):
        if has_cookies:
            return ("Instagram refused this even with your login cookies. They may have expired. "
                    "Export fresh cookies and choose the file again in Settings.")
        return NEEDS_LOGIN
    if "429" in text or "too many" in text or "rate" in text:
        return "Instagram is limiting requests right now. Wait a few minutes and try again."
    if "404" in text or "notfound" in text or "not found" in text:
        return "Instagram could not find that. It may be deleted, expired or private."
    if "private" in text:
        return "That account is private. Add login cookies for an account that follows it."
    lines = stderr.strip().splitlines()
    detail = next((e for e in errors if e), "") or (lines[-1].strip() if lines else "")
    return f"Instagram lookup failed. {detail}" if detail else "Instagram lookup failed."


def _run_gallery_dl(url: str, cookies: Path | None) -> tuple[list[Any], list[str], str]:
    """Ask gallery-dl to describe a link. Returns (messages, errors, stderr)."""
    command = [
        sys.executable, "-m", "gallery_dl",
        "--config-ignore", "--no-input", "--no-colors",
        "--dump-json", "--range", f"1-{MAX_ITEMS}",
        # "merged" gives one plain video file link instead of separate audio and video streams.
        "-o", "videos=merged",
    ]
    if cookies:
        command += ["--cookies", str(cookies)]
    command.append(url)
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=LOOKUP_TIMEOUT, env=os.environ | {"PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired as exc:
        raise InstagramError("Instagram took too long to answer. Try again in a moment.") from exc
    except OSError as exc:
        raise InstagramError("The Instagram helper could not start. Run start.bat again to repair the setup.") from exc

    messages: list[Any] = []
    try:
        parsed = json.loads(result.stdout) if result.stdout.strip() else []
        if isinstance(parsed, list):
            messages = parsed
    except ValueError:
        pass
    errors = []
    for message in messages:
        if isinstance(message, list) and message and message[0] == -1 and len(message) > 1:
            info = message[1] if isinstance(message[1], dict) else {}
            errors.append(f"{info.get('error', '')} {info.get('message', '')}".strip())
    return messages, errors, result.stderr or ""


def _stem(kind: str, username: str, meta: dict[str, Any], multiple: bool) -> str:
    """A tidy, unique file name (without extension) for one item."""
    media_id = str(meta.get("media_id") or "")
    code = str(meta.get("post_shortcode") or "")
    if kind == "avatar":
        tail = f"profile_picture_{media_id or code}".rstrip("_")
    elif kind in ("story", "highlight"):
        tail = f"{kind}_{media_id or code}"
    else:
        tail = f"{kind}_{code or media_id}"
        if multiple and meta.get("num"):
            tail += f"_{int(meta['num']):02d}"
    return sanitize_filename(f"{username}_{tail}", restricted=False).strip(" .") or "instagram"


def build_result(kind: str, source_url: str, messages: list[Any], fallback_username: str | None = None) -> dict[str, Any]:
    """Turn gallery-dl's message list into what the dashboard shows."""
    files = [
        m for m in messages
        if isinstance(m, list) and len(m) >= 3 and m[0] == MESSAGE_URL
        and isinstance(m[1], str) and isinstance(m[2], dict)
    ]
    username = fallback_username
    fullname = None
    caption = ""
    for _, _, meta in files:
        username = username or meta.get("username")
        fullname = fullname or meta.get("fullname")
        caption = caption or (meta.get("description") or "")
    username = username or "instagram"

    items = []
    for number, (_, url, meta) in enumerate(files, start=1):
        if not is_media_url(url):
            continue
        is_video = bool(meta.get("video_url")) and url == meta.get("video_url")
        extension = str(meta.get("extension") or ("mp4" if is_video else "jpg")).lower()
        if is_video and extension not in ("mp4", "mov", "webm"):
            extension = "mp4"
        if not is_video and extension not in ("jpg", "jpeg", "png", "webp", "heic"):
            extension = "jpg"
        preview = meta.get("display_url") if is_media_url(str(meta.get("display_url") or "")) else None
        if not is_video:
            preview = preview or url
        items.append({
            "index": number,
            "kind": "video" if is_video else "photo",
            "media_url": url,
            "preview_url": preview,
            "ext": extension,
            "width": meta.get("width") or None,
            "height": meta.get("height") or None,
            "file_stem": _stem(kind, username, meta, len(files) > 1),
            "title": f"{KIND_LABELS[kind]} {number}" if len(files) > 1 else KIND_LABELS[kind],
        })

    label = KIND_LABELS[kind]
    title = f"{label} by @{username}" if kind != "avatar" else f"@{username}"
    return {
        "type": "instagram",
        "kind": kind,
        "label": label,
        "title": title,
        "username": username,
        "fullname": fullname,
        "caption": caption.strip()[:280],
        "url": source_url,
        "count": len(items),
        "photo_count": sum(1 for i in items if i["kind"] == "photo"),
        "video_count": sum(1 for i in items if i["kind"] == "video"),
        "items": items,
    }


def analyze(url: str, cookies: Path | None = None) -> dict[str, Any]:
    """Look up an Instagram link and list what can be downloaded from it."""
    target = classify(url)
    kind = str(target["kind"])
    if kind in ("story", "highlight") and not cookies:
        raise InstagramError(
            "Stories need you to be logged in. Add your Instagram login cookies in Settings, then try again.")

    messages, errors, stderr = _run_gallery_dl(str(target["url"]), cookies)
    result = build_result(kind, str(target["url"]), messages, target["username"])
    if not result["items"]:
        if kind == "story" and not errors and "error" not in stderr.lower():
            raise InstagramError(f"@{target['username']} has no active story right now.")
        raise InstagramError(_friendly_error(stderr, errors, bool(cookies)))
    return result
