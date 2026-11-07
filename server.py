"""Open Instagram API: local HTTP API for Instagram DMs.  Run:  python3 server.py   (binds 127.0.0.1:8765)
Auth: header `Authorization: Bearer <contents of ./api_token>`."""
import os
import secrets
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from igdm.client import IGDirect, IGError

HOME = Path(__file__).resolve().parent
TOKEN_FILE = HOME / "api_token"
if not TOKEN_FILE.exists():
    TOKEN_FILE.write_text(secrets.token_urlsafe(32))
    os.chmod(TOKEN_FILE, 0o600)
API_TOKEN = TOKEN_FILE.read_text().strip()

ig = IGDirect()
app = FastAPI(title="Open Instagram API", version="0.1")


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


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("IGDM_PORT", 8765)))
