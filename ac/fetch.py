"""Download a video (picture and sound) from a link."""
import re
import time
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")


class FetchError(RuntimeError):
    pass


def clean_url(url):
    m = re.search(r"https?://\S+", (url or "").strip())
    if not m:
        raise FetchError("Paste a full link that starts with https://")
    return m.group(0)


def video_key(url):
    """Same video, however the link was copied (playlist, tracking, share params)."""
    from urllib.parse import parse_qs, urlparse
    u = urlparse(url)
    q = parse_qs(u.query)
    host = u.netloc.lower()
    if "youtube." in host or "youtu.be" in host:
        vid = q.get("v", [None])[0] or (u.path.strip("/").split("/")[-1] if "youtu.be" in host or "/shorts/" in u.path else None)
        if vid:
            return f"youtube:{vid}"
    m = re.search(r"(BV[0-9A-Za-z]{10})", url)
    if m:
        return f"bilibili:{m.group(1)}:p{q.get('p', ['1'])[0]}"
    return f"url:{host}{u.path}".rstrip("/")


def download(url, job_dir, on_progress):
    """Returns (summary dict, path to the video file)."""
    import yt_dlp

    url = clean_url(url)
    bilibili = "bilibili." in url or "b23.tv" in url
    headers = {"User-Agent": UA}
    if bilibili:
        headers["Referer"] = "https://www.bilibili.com/"

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            on_progress((d.get("downloaded_bytes") or 0) / total if total else None)

    opts = {
        # up to 1080p; prefer H.264 + AAC so every browser (Safari too) can play it
        "format": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
        "format_sort": ["vcodec:h264", "res:1080", "acodec:aac"],
        "merge_output_format": "mp4",
        "outtmpl": str(Path(job_dir) / "source.%(ext)s"),
        "noplaylist": True,
        "http_headers": headers,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "overwrites": True,
    }
    last = None
    for attempt, wait in enumerate((0, 8, 20, 45)):
        if wait:
            on_progress(None, f"The site pushed back ({last}). Retrying in {wait} s…")
            time.sleep(wait)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            break
        except yt_dlp.utils.DownloadError as e:
            last = _short(str(e))
            if not _retryable(str(e)) or attempt == 3:
                raise FetchError(last) from None
    if info.get("_type") == "playlist":
        entries = [e for e in info.get("entries") or [] if e]
        if not entries:
            raise FetchError("That link is a playlist with nothing playable in it.")
        info = entries[0]
    files = [f for f in sorted(Path(job_dir).glob("source.*"))
             if f.suffix.lower() not in (".part", ".ytdl", ".jpg", ".webp", ".png")]
    if not files:
        raise FetchError("The download finished but no video file was written.")
    summary = {"url": url, "title": info.get("title") or "", "duration": info.get("duration") or 0,
               "uploader": info.get("uploader") or info.get("channel") or "",
               "description": (info.get("description") or "")[:1500]}
    return summary, files[0]


def _retryable(msg):
    return any(s in msg for s in ("412", "429", "403", "timed out", "Connection reset",
                                   "IncompleteRead", "HTTP Error 5"))


def _short(msg):
    msg = re.sub(r"\x1b\[[0-9;]*m", "", msg).replace("ERROR: ", "")
    return msg.strip().splitlines()[0][:240]
