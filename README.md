# TubeDrop

A local web dashboard for saving YouTube videos and playlists as MP3 audio or high-quality MP4 video,
and Instagram reels, posts, stories and profile pictures as photos, videos or MP3 audio.
Everything runs on your own PC. Nothing is uploaded anywhere.

## Start it

Double-click `start.bat`. The dashboard opens in your browser at http://127.0.0.1:8756.
Keep the black window open while you use it. Close that window to stop the app.

The first run sets up its own Python environment, which takes about a minute.

## What it does

- **Single videos and playlists.** Paste a link and press Fetch. Playlists show every item so you can tick the ones you want.
- **MP3 audio** at 320, 256, 192 or 128 kbps, with the title, artist and cover art written into the file.
- **MP4 video** from 360p up to 4K. It always picks the sharpest version within your limit and prefers H.264 so files play everywhere.
- **Live queue** with progress, speed and time left. Cancel, retry or clear items at any time.
- **Library** to search, play, reveal in Explorer or delete what you have downloaded. Deleted files go to the Recycle Bin.
- **Settings** for the download folder, how many downloads run at once, and tagging.

## Instagram

Paste any of these links and press Fetch:

| Link | What you get |
| --- | --- |
| `instagram.com/reel/...` | The reel as a video, or its sound as MP3 |
| `instagram.com/p/...` | Every photo and video in the post, with checkboxes to pick |
| `instagram.com/stories/username/` | That account's current stories. Needs a login. |
| `instagram.com/stories/highlights/...` | A highlight. Needs a login. |
| `instagram.com/username` | The profile picture, plus a button to load their stories |

Use the switch to choose between **Photos and videos** as posted, or **Audio only (MP3)**.
In MP3 mode photos are skipped, because they have no sound.

### Instagram login

Stories always need a login, and Instagram often asks for one on other links too.
TubeDrop never asks for your password. Instead you give it a cookies file from your own browser:

1. Log in to instagram.com in your normal browser.
2. Add a browser extension that exports cookies in the `cookies.txt` format.
3. While on instagram.com, export a cookies file and save it somewhere safe.
4. In TubeDrop, open **Settings**, press **Choose cookies file…** and select it.

Treat that file like a password. Anyone holding it can use your account. Keep it out of this
folder if you share the project, and note that Instagram may limit accounts that download a lot.

Media links from Instagram expire after a few hours. If a queued item says its link has expired,
fetch the post again.

## Where files go

Inside the download folder (default: `downloads` next to this file):

```
downloads/
  Music/                     single MP3s
  Music/<playlist name>/     playlist MP3s, numbered in playlist order
  Videos/                    single MP4s, e.g. "Title [1080p].mp4"
  Videos/<playlist name>/    playlist MP4s
  Instagram/<username>/      photos, videos and MP3s from that account
```

A file that already exists is skipped, so re-running a playlist only fetches what is new.

## If downloads stop working

YouTube changes often. Run `update.bat` to get the newest download engine, then start the app again.

## Requirements

- Windows with Python 3.10 or newer
- ffmpeg on the PATH (`winget install Gyan.FFmpeg`)
- Node.js or Deno, which the download engine uses to read YouTube's player

## Project layout

```
run.py               starts the server and opens the browser
app/server.py        web API
app/downloader.py    download queue built on yt-dlp
app/instagram.py     Instagram link handling, built on gallery-dl
app/static/          the dashboard (HTML, CSS, JavaScript)
data/                saved settings and download history
```

Only download content you own or have permission to save.
