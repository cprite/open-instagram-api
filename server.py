"""Open Instagram API: local HTTP API for Instagram.  Run:  python3 server.py   (binds 127.0.0.1:8765)
Auth: header `Authorization: Bearer <contents of ./api_token>`."""
import os
import secrets
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from igdm.instagram import Instagram, IGError

HOME = Path(__file__).resolve().parent
TOKEN_FILE = HOME / "api_token"
if not TOKEN_FILE.exists():
    TOKEN_FILE.write_text(secrets.token_urlsafe(32))
    os.chmod(TOKEN_FILE, 0o600)
API_TOKEN = TOKEN_FILE.read_text().strip()

ig = Instagram()
app = FastAPI(title="Open Instagram API", version="0.2")


def auth(authorization: str = Header(default="")):
    if not secrets.compare_digest(authorization, f"Bearer {API_TOKEN}"):
        raise HTTPException(401, "bad or missing bearer token")


@app.exception_handler(IGError)
def ig_error(_, e: IGError):
    return JSONResponse(status_code=e.status, content={"error": str(e), "detail": e.detail})


class SendBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    reply_to_message_id: str | None = None


class SeenBody(BaseModel):
    message_id: str | None = None


@app.get("/health")
def health():
    return {"ok": True, "logged_in_actor": ig.tokens.get("av"), "tokens_age_s": None if not ig.tokens_at else int(__import__("time").time() - ig.tokens_at)}


@app.get("/threads", dependencies=[Depends(auth)])
def threads(folder: str = Query("inbox", pattern="^(inbox|requests)$")):
    return ig.list_threads(folder)


@app.get("/unread", dependencies=[Depends(auth)])
def unread():
    return ig.unread()


@app.get("/threads/{thread_fbid}", dependencies=[Depends(auth)])
def thread(thread_fbid: str):
    return ig.thread(thread_fbid)


@app.get("/threads/{thread_fbid}/messages", dependencies=[Depends(auth)])
def messages(thread_fbid: str):
    t = ig.thread(thread_fbid)
    return {"thread_fbid": t["thread_fbid"], "messages": t["messages"], "page_info": t["page_info"]}


@app.post("/threads/{thread_fbid}/messages", dependencies=[Depends(auth)])
def send(thread_fbid: str, body: SendBody):
    return ig.send_text(thread_fbid, body.text, body.reply_to_message_id)


@app.post("/threads/{thread_fbid}/seen", dependencies=[Depends(auth)])
def seen(thread_fbid: str, body: SeenBody | None = None):
    return ig.mark_seen(thread_fbid, body.message_id if body else None)


@app.post("/threads/{thread_fbid}/accept", dependencies=[Depends(auth)])
def accept(thread_fbid: str):
    return ig.accept_request(thread_fbid)


@app.get("/updates", dependencies=[Depends(auth)])
def updates(since_ms: int = Query(..., ge=0), include_requests: bool = True):
    return ig.updates(since_ms, include_requests)


class AutoreplyBody(BaseModel):
    mode: str = Field(pattern="^(auto|on|off)$")
    minutes: int | None = Field(default=None, ge=1, le=7 * 24 * 60)


@app.get("/autoreply", dependencies=[Depends(auth)])
def autoreply_status():
    from examples import reel_autoreply as ar
    cfg = {**ar.DEFAULT_CONFIG, **ar.load_json(ar.CONFIG, {})}
    working, why = ar.is_working(cfg)
    st = ar.load_json(ar.STATE, {})
    return {"working": working, "why": why, "override": ar.load_json(ar.OVERRIDE, {"mode": "auto"}),
            "reply_text": cfg["reply_text"], "work_hours": cfg["work_hours"], "timezone": cfg["timezone"],
            "last_tick": st.get("last_tick"), "replies_last_hour": len([t for t in st.get("sent_ts", []) if __import__("time").time() - t < 3600])}


@app.post("/autoreply", dependencies=[Depends(auth)])
def autoreply_set(body: AutoreplyBody):
    """mode=on → 'I'm working' (auto-reply), off → never auto-reply, auto → follow schedule. minutes = temporary override."""
    import time
    from examples import reel_autoreply as ar
    ar.save_json(ar.OVERRIDE, {"mode": body.mode,
                               "until_ms": int(time.time() * 1000) + body.minutes * 60000 if body.minutes and body.mode != "auto" else None})
    return autoreply_status()


@app.post("/admin/refresh", dependencies=[Depends(auth)])
def refresh():
    ig.bootstrap(force=True)
    return {"doc_ids": ig.refresh_doc_ids()}


# ======================= Phase A: read-only =======================
A = [Depends(auth)]
Cur = Query(None, description="next_cursor from the previous page")
Raw = Query(False, description="return Instagram's raw response")


@app.get("/search", dependencies=A)
def search(q: str = Query(..., min_length=1), raw: bool = Raw):
    return ig.search(q, raw)


@app.get("/users/{user}", dependencies=A)
def user(user: str, raw: bool = Raw):
    return ig.user_info(user, raw)


@app.get("/users/{user}/posts", dependencies=A)
def user_posts(user: str, cursor: str | None = Cur, count: int = Query(12, ge=6, le=50, description="Instagram returns nothing below 6"), raw: bool = Raw):
    return ig.user_posts(user, cursor, count, raw)


@app.get("/users/{user}/reels", dependencies=A)
def user_reels(user: str, cursor: str | None = Cur, count: int = Query(12, ge=1, le=50), raw: bool = Raw):
    return ig.user_reels(user, cursor, count, raw)


@app.get("/users/{user}/tagged", dependencies=A)
def user_tagged(user: str, count: int = Query(12, ge=1, le=50), raw: bool = Raw):
    return ig.user_tagged(user, count, raw)


@app.get("/users/{user}/highlights", dependencies=A)
def user_highlights(user: str, raw: bool = Raw):
    return ig.user_highlights(user, raw)


@app.get("/users/{user}/stories", dependencies=A)
def user_stories(user: str, raw: bool = Raw):
    return ig.user_stories(user, raw)


@app.get("/users/{user}/followers", dependencies=A)
def user_followers(user: str, cursor: str | None = Cur, count: int = Query(25, ge=1, le=100), raw: bool = Raw):
    return ig.followers(user, cursor, count, raw)


@app.get("/users/{user}/following", dependencies=A)
def user_following(user: str, cursor: str | None = Cur, count: int = Query(25, ge=1, le=100), raw: bool = Raw):
    return ig.following(user, cursor, count, raw)


@app.get("/highlights/{highlight_id}", dependencies=A)
def highlight(highlight_id: str, raw: bool = Raw):
    return ig.highlight(highlight_id, raw)


@app.get("/stories/tray", dependencies=A)
def stories_tray(raw: bool = Raw):
    return ig.story_tray(raw)


@app.get("/media/{code}", dependencies=A)
def media_info(code: str, raw: bool = Raw):
    return ig.media_info(code, raw)


@app.get("/media/{code}/comments", dependencies=A)
def media_comments(code: str, cursor: str | None = Cur, sort: str = Query("popular", pattern="^(popular|newest)$"), raw: bool = Raw):
    return ig.media_comments(code, cursor, 20, sort, raw)


@app.get("/comments/{comment_pk}/replies", dependencies=A)
def comment_replies(comment_pk: str, cursor: str | None = Cur, raw: bool = Raw):
    return ig.comment_replies(comment_pk, cursor, raw)


@app.get("/media/{code}/likers", dependencies=A)
def media_likers(code: str, raw: bool = Raw):
    return ig.media_likers(code, raw)


@app.get("/feed/timeline", dependencies=A)
def feed_timeline(cursor: str | None = Cur, raw: bool = Raw):
    return ig.timeline(cursor, raw)


@app.get("/feed/reels", dependencies=A)
def feed_reels(cursor: str | None = Cur, raw: bool = Raw):
    return ig.reels_feed(cursor, raw)


@app.get("/feed/explore", dependencies=A)
def feed_explore(cursor: str | None = Cur, raw: bool = Raw):
    return ig.explore(cursor, raw)


@app.get("/tags/{tag}", dependencies=A)
def tag(tag: str, raw: bool = Raw):
    return ig.hashtag(tag, raw)


@app.get("/locations/{location_id}", dependencies=A)
def location(location_id: str, tab: str = Query("ranked", pattern="^(ranked|recent)$"), cursor: str | None = Cur, raw: bool = Raw):
    return ig.location(location_id, tab, cursor, raw)


@app.get("/notifications", dependencies=A)
def notifications(raw: bool = Raw):
    return ig.notifications(raw)


@app.get("/saved", dependencies=A)
def saved(raw: bool = Raw):
    return ig.saved(12, raw)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("IGDM_PORT", 8765)))
