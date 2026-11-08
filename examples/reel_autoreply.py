"""Example bot: reel auto-responder. While you're "working", reply to every reel someone sends you in the inbox.

Listens to the realtime stream (GET /events) and replies within about a second; also polls /updates as a
safety net (every 5 min while the stream is up, every poll_seconds while it's down).
"Working" = schedule in autoreply.json, overridden by autoreply_override.json (set via POST /autoreply on the API):  {"mode": "auto"|"on"|"off", "until_ms": <epoch ms|null>}.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

HOME = Path(__file__).resolve().parent.parent   # repo root
CONFIG = HOME / "autoreply.json"
OVERRIDE = HOME / "autoreply_override.json"
STATE = HOME / "autoreply_state.json"
API = os.environ.get("IGDM_API", "http://127.0.0.1:8765")
TOKEN = (HOME / "api_token").read_text().strip()
H = {"Authorization": f"Bearer {TOKEN}"}

DEFAULT_CONFIG = {
    "timezone": "Europe/London",
    "work_hours": {"mon": ["09:00", "18:00"], "tue": ["09:00", "18:00"], "wed": ["09:00", "18:00"],
                   "thu": ["09:00", "18:00"], "fri": ["09:00", "18:00"]},
    "reply_text": "[auto reply]\nHi! I'm busy right now and will watch your reel later.",
    "kinds": ["reel"],
    "include_requests": False,
    "poll_seconds": 30,
    "max_replies_per_hour": 20,
    "skip_if_i_replied_after": True,
}
log = logging.getLogger("autoreply")


def load_json(p, default):
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, ValueError):
        return default


def save_json(p, obj):
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def is_working(cfg, now_ms=None):
    """-> (working: bool, reason: str)"""
    now_ms = now_ms or int(time.time() * 1000)
    ov = load_json(OVERRIDE, {"mode": "auto"})
    mode = ov.get("mode", "auto")
    if mode in ("on", "off") and (not ov.get("until_ms") or now_ms < ov["until_ms"]):
        return mode == "on", f"override:{mode}" + (f" until {ov['until_ms']}" if ov.get("until_ms") else "")
    now = datetime.fromtimestamp(now_ms / 1000, ZoneInfo(cfg["timezone"]))
    span = cfg["work_hours"].get(now.strftime("%a").lower())
    if not span:
        return False, "schedule:day off"
    hm = now.strftime("%H:%M")
    return span[0] <= hm < span[1], f"schedule:{span[0]}-{span[1]}"


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not CONFIG.exists():
        save_json(CONFIG, DEFAULT_CONFIG)
    st = load_json(STATE, {})
    st.setdefault("since_ms", int(time.time() * 1000))   # never answer reels that predate the first start
    st.setdefault("replied", [])
    st.setdefault("sent_ts", [])
    save_json(STATE, st)
    log.info("started; since_ms=%s", st["since_ms"])
    threading.Thread(target=stream_loop, args=(st,), daemon=True).start()
    while True:
        cfg = {**DEFAULT_CONFIG, **load_json(CONFIG, {})}
        try:
            with LOCK:
                tick(cfg, st)
        except requests.RequestException as e:
            log.warning("API unreachable: %s", e)
        except Exception:
            log.exception("tick failed")
        # realtime stream up -> polling is only a safety net for anything the socket missed
        time.sleep(STREAM_POLL_SECONDS if STREAM["up"] else max(15, int(cfg["poll_seconds"])))


LOCK = threading.Lock()
STREAM = {"up": False}
STREAM_POLL_SECONDS = 300


_FOLDERS = {}   # thread_fbid -> (folder, title, fetched_at); accepted requests move to INBOX, so cache 10 min


def thread_folder(thread_fbid):
    hit = _FOLDERS.get(thread_fbid)
    if hit and time.time() - hit[2] < 600:
        return hit[0], hit[1]
    t = requests.get(f"{API}/threads/{thread_fbid}", headers=H, timeout=30).json()
    _FOLDERS[thread_fbid] = ((t.get("folder") or "").upper(), t.get("title"), time.time())
    return _FOLDERS[thread_fbid][:2]


def stream_loop(st):
    """Follow GET /events (realtime gateway via the API) and handle reels the moment they arrive."""
    backoff = 5
    while True:
        try:
            with requests.get(f"{API}/events", headers=H, stream=True, timeout=(10, 60)) as r:
                r.raise_for_status()
                for line in r.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data: "):
                        continue
                    ev = json.loads(line[6:])
                    if ev["type"] in ("connected", "disconnected"):
                        STREAM["up"] = ev["type"] == "connected"
                        log.info("realtime %s%s", ev["type"], f" ({ev.get('error')})" if ev.get("error") else "")
                        backoff = 5
                        continue
                    if ev["type"] != "message":
                        continue
                    m = ev["message"]
                    cfg = {**DEFAULT_CONFIG, **load_json(CONFIG, {})}
                    if m.get("is_from_me") or m.get("kind") not in cfg["kinds"] or not m.get("thread_fbid"):
                        continue
                    if not cfg["include_requests"]:
                        folder, title = thread_folder(m["thread_fbid"])
                        if folder == "PENDING":
                            continue
                        m["thread_title"] = title
                    working, why = is_working(cfg)
                    with LOCK:
                        log.info("realtime reel %s; working=%s (%s)", m["id"], working, why)
                        handle(cfg, st, m, working, fresh=True)
                        st["replied"] = st["replied"][-1000:]
                        save_json(STATE, st)
        except Exception as e:
            log.warning("realtime stream down: %s: %s", type(e).__name__, str(e)[:160])
        STREAM["up"] = False
        time.sleep(backoff)
        backoff = min(backoff * 2, 300)


def handle(cfg, st, m, working, fresh=False):
    """Decide and (maybe) reply to one incoming reel. Caller holds LOCK.
    fresh=True (realtime event): the reel just arrived, so the owner can't have replied after it yet."""
    if m["id"] in st["replied"]:
        return
    if not working:
        st["replied"].append(m["id"])          # mark as handled: off-hours reels are not answered later
        return
    if cfg["skip_if_i_replied_after"] and not fresh and i_replied_after(m, cfg["reply_text"]):
        log.info("skip %s: I already wrote in %s after it", m["id"], m.get("thread_title") or m["thread_fbid"])
        st["replied"].append(m["id"]); return
    now = time.time()
    st["sent_ts"] = [t for t in st["sent_ts"] if now - t < 3600]
    if len(st["sent_ts"]) >= cfg["max_replies_per_hour"]:
        log.warning("hourly cap %d reached; not replying to %s", cfg["max_replies_per_hour"], m["id"])
        st["replied"].append(m["id"]); return
    s = requests.post(f"{API}/threads/{m['thread_fbid']}/messages", headers=H, timeout=60,
                      json={"text": cfg["reply_text"], "reply_to_message_id": m["id"]})
    if s.ok:
        st["sent_ts"].append(time.time()); st["replied"].append(m["id"])
        lag = (time.time() * 1000 - m["timestamp_ms"]) / 1000 if m.get("timestamp_ms") else -1
        log.info("replied to reel %s from %s (%s by @%s) %.1fs after it arrived", m["id"],
                 m.get("sender_username") or m.get("thread_title") or m["thread_fbid"],
                 (m.get("share") or {}).get("shortcode"), (m.get("share") or {}).get("author"), lag)
    else:
        log.error("send failed %s: %s", s.status_code, s.text[:300])


def tick(cfg, st):
    r = requests.get(f"{API}/updates", headers=H, timeout=120,
                     params={"since_ms": st["since_ms"], "include_requests": str(cfg["include_requests"]).lower()})
    if r.status_code == 401 and "session" in r.text:
        log.error("Instagram session expired — re-export cookies.json")
        save_json(STATE, st); return
    r.raise_for_status()
    upd = r.json()
    working, why = is_working(cfg)
    targets = [m for m in upd["messages"] if m.get("kind") in cfg["kinds"] and m["id"] not in st["replied"]]
    if targets:
        log.info("%d new %s msg(s); working=%s (%s)", len(targets), "/".join(cfg["kinds"]), working, why)
    for m in targets:
        handle(cfg, st, m, working)
    st["replied"] = st["replied"][-1000:]
    st["since_ms"] = max(st["since_ms"], upd["next_since_ms"])
    st["last_tick"] = {"at_ms": int(time.time() * 1000), "working": working, "why": why}
    save_json(STATE, st)


def i_replied_after(m, auto_text):
    """True if I (a human, not this bot) wrote in the thread after message m."""
    t = requests.get(f"{API}/threads/{m['thread_fbid']}/messages", headers=H, timeout=60).json()
    return any(x["is_from_me"] and x["timestamp_ms"] > m["timestamp_ms"] and x.get("text") != auto_text
               for x in t["messages"])


if __name__ == "__main__":
    main()
