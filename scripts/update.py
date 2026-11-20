#!/usr/bin/env python3
"""Garunesia comment leaderboard updater.

Runs on GitHub Actions. Reads YouTube comments through the YouTube Data API v3,
scores the first N commenters of every video within its 24-hour window, and
writes:
  data/state.json            -> per-video results (persisted between runs)
  docs/data/leaderboard.json -> what the website reads

Only the Python standard library is used, so nothing needs installing.
Environment: YT_API_KEY (required).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
STATE_PATH = os.path.join(ROOT, "data", "state.json")
OUT_PATH = os.path.join(ROOT, "docs", "data", "leaderboard.json")

API = "https://www.googleapis.com/youtube/v3/"
WIB = timezone(timedelta(hours=7))
AUTHOR_REFRESH_DAYS = 7
MAX_COMMENT_PAGES = 50       # 5.000 komentar per video, lebih dari cukup
MAX_PLAYLIST_PAGES = 20      # 1.000 video terakhir saat backfill pertama


class ApiError(Exception):
    def __init__(self, status, reason, message):
        super().__init__(f"{status} {reason}: {message}")
        self.status, self.reason = status, reason


# ---------------------------------------------------------------- helpers
def now_utc():
    return datetime.now(timezone.utc)


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, data):
    """Write only when the content really changed (keeps git history clean)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == new:
                return False
    except FileNotFoundError:
        pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    return True


def api_get(endpoint, params):
    key = os.environ.get("YT_API_KEY")
    if not key:
        sys.exit("YT_API_KEY belum diisi di GitHub Secrets.")
    url = API + endpoint + "?" + urllib.parse.urlencode({**params, "key": key})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                err = json.load(e).get("error", {})
            except Exception:
                err = {}
            reason = (err.get("errors") or [{}])[0].get("reason", "")
            if e.code >= 500 and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise ApiError(e.code, reason, err.get("message", str(e)))
        except urllib.error.URLError:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise


# ---------------------------------------------------------------- YouTube
def list_uploads(channel_id, start):
    """Videos uploaded on/after `start`, newest first."""
    playlist = "UU" + channel_id[2:]
    videos, token = [], None
    for _ in range(MAX_PLAYLIST_PAGES):
        params = {"part": "snippet,contentDetails", "playlistId": playlist, "maxResults": 50}
        if token:
            params["pageToken"] = token
        data = api_get("playlistItems", params)
        reached_old = False
        for it in data.get("items", []):
            cd, sn = it.get("contentDetails", {}), it.get("snippet", {})
            pub = cd.get("videoPublishedAt")
            if not pub:  # private / deleted / not yet published
                continue
            if parse_ts(pub) < start:
                reached_old = True
                continue
            thumbs = sn.get("thumbnails", {})
            thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
            videos.append({"id": cd["videoId"], "title": sn.get("title", ""),
                           "published": pub, "thumb": thumb})
        token = data.get("nextPageToken")
        if not token or reached_old:
            break
    return videos


def fetch_comments(video_id):
    """All top-level comments of a video (replies are ignored on purpose)."""
    out, token = [], None
    for _ in range(MAX_COMMENT_PAGES):
        params = {"part": "snippet", "videoId": video_id, "order": "time",
                  "maxResults": 100, "textFormat": "plainText"}
        if token:
            params["pageToken"] = token
        try:
            data = api_get("commentThreads", params)
        except ApiError as e:
            if e.reason in ("commentsDisabled", "videoNotFound", "forbidden"):
                return out
            raise
        for it in data.get("items", []):
            c = it["snippet"]["topLevelComment"]
            s = c["snippet"]
            out.append({
                "comment_id": c["id"],
                "author_id": (s.get("authorChannelId") or {}).get("value", ""),
                "display": s.get("authorDisplayName", ""),
                "url": s.get("authorChannelUrl", ""),
                "avatar": s.get("authorProfileImageUrl", ""),
                "time": s.get("publishedAt"),
                "text": s.get("textDisplay", ""),
            })
        token = data.get("nextPageToken")
        if not token:
            break
    return out


def fetch_channels(ids):
    """channel id -> {title, handle, avatar, url}. 1 quota unit per 50 channels."""
    result = {}
    ids = list(ids)
    for i in range(0, len(ids), 50):
        data = api_get("channels", {"part": "snippet", "id": ",".join(ids[i:i + 50]),
                                    "maxResults": 50})
        for it in data.get("items", []):
            sn = it.get("snippet", {})
            handle = sn.get("customUrl", "")
            if handle and not handle.startswith("@"):
                handle = "@" + handle
            th = sn.get("thumbnails", {})
            result[it["id"]] = {
                "title": sn.get("title", ""),
                "handle": handle,
                "avatar": (th.get("default") or {}).get("url", ""),
                "url": f"https://www.youtube.com/{handle}" if handle
                       else f"https://www.youtube.com/channel/{it['id']}",
            }
    return result


# ---------------------------------------------------------------- scoring
def score_video(video, comments, cfg, owner_id):
    pub = parse_ts(video["published"])
    closes = pub + timedelta(hours=cfg["window_hours"])
    excluded = set(cfg.get("exclude_channels", [])) | {owner_id}
    eligible = []
    for c in comments:
        if not c["author_id"] or c["author_id"] in excluded:
            continue
        if parse_ts(c["time"]) >= closes:
            continue
        if len(c["text"].split()) < cfg.get("min_words", 1):
            continue
        eligible.append(c)
    eligible.sort(key=lambda c: (c["time"], c["comment_id"]))
    top, seen = [], set()
    for c in eligible:
        if c["author_id"] in seen:
            continue  # satu orang hanya dihitung sekali per video
        seen.add(c["author_id"])
        rank = len(top) + 1
        top.append({"rank": rank, "points": cfg["points"][rank - 1],
                    "author_id": c["author_id"], "display": c["display"],
                    "url": c["url"], "avatar": c["avatar"], "time": c["time"]})
        if len(top) == len(cfg["points"]):
            break
    return top, closes


def build_leaderboard(state, cfg, generated):
    authors = state.get("authors", {})
    finals = sorted((v for v in state["videos"].values() if v["status"] == "final"),
                    key=lambda v: v["published"])

    def person(entry):
        a = authors.get(entry["author_id"], {})
        return {"id": entry["author_id"],
                "name": a.get("title") or entry["display"].lstrip("@"),
                "handle": a.get("handle") or entry["display"],
                "url": a.get("url") or entry["url"],
                "avatar": a.get("avatar") or entry["avatar"]}

    def table(videos):
        stats, order = {}, [v["id"] for v in videos]
        appear = {}
        for v in videos:
            for e in v["top"]:
                s = stats.setdefault(e["author_id"], {
                    "points": 0, "appearances": 0, "firsts": 0, "first_seen": v["published"],
                    "entry": e})
                s["points"] += e["points"]
                s["appearances"] += 1
                s["firsts"] += e["rank"] == 1
                appear.setdefault(e["author_id"], set()).add(v["id"])
        rows = []
        for aid, s in stats.items():
            best = cur = 0
            for vid in order:
                cur = cur + 1 if vid in appear[aid] else 0
                best = max(best, cur)
            rows.append({**person(s["entry"]), "points": s["points"],
                         "appearances": s["appearances"], "firsts": s["firsts"],
                         "best_streak": best, "_first_seen": s["first_seen"]})
        rows.sort(key=lambda r: (-r["points"], -r["firsts"], -r["appearances"],
                                 r["_first_seen"]))
        rows = rows[:cfg["leaderboard_size"]]
        prev, rank = None, 0
        for i, r in enumerate(rows, 1):
            key = (r["points"], r["firsts"], r["appearances"])
            rank = rank if key == prev else i
            prev = key
            r["rank"] = rank
            del r["_first_seen"]
        return rows

    by_month = {}
    for v in finals:
        m = parse_ts(v["published"]).astimezone(WIB).strftime("%Y-%m")
        by_month.setdefault(m, []).append(v)

    def video_out(v):
        return {"id": v["id"], "title": v["title"], "published": v["published"],
                "closes": v["closes"], "thumb": v.get("thumb", ""),
                "top": [{**person(e), "rank": e["rank"], "points": e["points"],
                         "time": e["time"]} for e in v["top"]]}

    return {
        "generated_at": generated,
        "channel": state.get("channel", {}),
        "rules": {"window_hours": cfg["window_hours"], "points": cfg["points"],
                  "min_words": cfg.get("min_words", 1)},
        "totals": {"videos": len(finals),
                   "people": len({e["author_id"] for v in finals for e in v["top"]})},
        "alltime": table(finals),
        "months": {m: table(vs) for m, vs in sorted(by_month.items())},
        "recent": [video_out(v) for v in reversed(finals[-12:])],
    }


# ---------------------------------------------------------------- main
def main():
    cfg = load_json(CONFIG_PATH, None)
    if not cfg or cfg["channel_id"].startswith("GANTI"):
        sys.exit("Isi channel_id di config.json terlebih dahulu.")
    owner = cfg["channel_id"]
    start = datetime.fromisoformat(cfg["start_date"]).replace(tzinfo=WIB)
    now = now_utc()
    grace = timedelta(minutes=cfg.get("final_grace_minutes", 10))

    state = load_json(STATE_PATH, {"videos": {}, "authors": {}})
    state.setdefault("videos", {})
    state.setdefault("authors", {})

    if not state.get("channel"):
        info = fetch_channels([owner]).get(owner)
        if not info:
            sys.exit("channel_id tidak ditemukan. Periksa lagi config.json.")
        state["channel"] = {"id": owner, **info}

    uploads = list_uploads(owner, start)
    upload_ids = {v["id"] for v in uploads}
    # video yang dihapus/diprivat dikeluarkan dari hitungan
    for vid in [k for k in state["videos"] if k not in upload_ids]:
        del state["videos"][vid]

    processed = 0
    for v in uploads:
        old = state["videos"].get(v["id"])
        if old and old["status"] == "final":
            old["title"], old["thumb"] = v["title"], v["thumb"]
            continue
        closes = parse_ts(v["published"]) + timedelta(hours=cfg["window_hours"])
        if now < closes + grace:
            continue  # jendela 24 jam belum tutup, dihitung nanti
        comments = fetch_comments(v["id"])
        top, closes = score_video(v, comments, cfg, owner)
        state["videos"][v["id"]] = {**v, "closes": iso(closes), "top": top,
                                    "status": "final"}
        processed += 1

    # profil komentator (nama channel & @handle), diperbarui seminggu sekali
    needed = {e["author_id"] for v in state["videos"].values() for e in v["top"]}
    stale_before = iso(now - timedelta(days=AUTHOR_REFRESH_DAYS))
    todo = [a for a in needed
            if state["authors"].get(a, {}).get("fetched", "") < stale_before]
    if todo:
        fetched = fetch_channels(todo)
        for a in todo:
            if a in fetched:
                state["authors"][a] = {**fetched[a], "fetched": iso(now)}
    for a in [a for a in state["authors"] if a not in needed]:
        del state["authors"][a]

    changed_state = save_json(STATE_PATH, state)
    board = build_leaderboard(state, cfg, iso(now))
    old_board = load_json(OUT_PATH, {})
    old_board["generated_at"] = board["generated_at"]
    changed_board = old_board != board and save_json(OUT_PATH, board)
    print(f"{len(uploads)} video dalam periode, {processed} diproses, "
          f"{board['totals']['videos']} sudah dikunci. "
          f"state {'berubah' if changed_state else 'tetap'}, "
          f"leaderboard {'berubah' if changed_board else 'tetap'}.")


if __name__ == "__main__":
    main()
