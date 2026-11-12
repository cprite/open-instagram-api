"""Phase B: more DM features — send a photo, unsend, react, share a post/reel into a chat, older messages.

Captured from the instagram.com chat:
  photo:  POST https://rupload.instagram.com/messenger_image/<uuid>?<page params>  (raw JPEG, image_type FILE_ATTACHMENT)
          -> {"media_id": <attachment fbid>}  ->  IGDirectMediaSendMutation {attachment_fbid, thread_id, offline_threading_id}
  unsend: IGDMessageUnsendDialogOffMsysMutation {message_id, send_data: {thread_id: <long thread_id>}}
  react:  IGDirectReactionSendMutation {input: {emoji, message_id, thread_id, reaction_status: created|deleted}}
  share:  reels: IGDirectReelShareMutation {ig_media_igid, otid, data: {thread_id | recipient_users}, clip_share_params}
          other posts: IGDirectMediaShareMutation {data: {media_id}, send_data: {thread_id | recipient_users, offline_threading_id}}
  older:  IGDMessageListOffMsysQuery {id: thread_fbid, after: cursor, first}
Not available on the web client: editing messages (the web menu only offers Forward / Pin / Unsend).
Mute/unmute goes over the Lightspeed WebSocket, which this client doesn't speak.
"""
from __future__ import annotations

import random
import uuid
from pathlib import Path

from .client import ASBD_ID, IGError, _otid


class DMMixin:
    def send_photo(self, thread_fbid: str, path: str, reply_to_message_id: str | None = None):
        from .publish import _as_jpeg
        self.bootstrap()
        t = self.tokens
        blob = _as_jpeg(Path(path))
        dt = t.get("fb_dtsg_full") or t["fb_dtsg"]
        q = {"__d": "www", "__user": "0", "__a": "1", "__req": format(random.randint(1, 60), "x"), "__hs": t["hs"],
             "dpr": "1", "__ccg": "EXCELLENT", "__rev": t["rev"], "__hsi": t["hsi"], "__comet_req": "7",
             "fb_dtsg": dt, "jazoest": "2" + str(sum(map(ord, dt))), "lsd": t["lsd"], "__spin_r": t["rev"],
             "__spin_b": t["spin_b"], "__spin_t": t["spin_t"], "__crn": "comet.igweb.PolarisDirectInboxRoute"}
        h = {"image_type": "FILE_ATTACHMENT", "Offset": "0", "X-Entity-Length": str(len(blob)), "X-Entity-Type": "image/jpeg",
             "X-Entity-Name": Path(path).with_suffix(".jpg").name, "X-IG-D": "www", "X-ASBD-ID": ASBD_ID,
             "Origin": "https://www.instagram.com", "Referer": f"https://www.instagram.com/direct/t/{thread_fbid}/"}
        with self.lock:
            r = self.s.post(f"https://rupload.instagram.com/messenger_image/{uuid.uuid4()}", params=q, data=blob,
                            headers=h, timeout=120)
        try:
            up = r.json()
        except ValueError:
            raise IGError(f"DM photo upload HTTP {r.status_code}", 502, r.text[:200])
        fbid = up.get("media_id_str") or str(up.get("media_id") or "")
        if not fbid:
            raise IGError("DM photo upload returned no media_id", 502, up)
        d = self.gql("IGDirectMediaSendMutation", {
            "attachment_fbid": fbid, "thread_id": str(thread_fbid), "offline_threading_id": _otid(),
            "reply_to_message_id": reply_to_message_id, "forwarded_from_thread_id": None,
            "is_forwarded_from_own_message": None}, write=True)
        res = d.get("xig_direct_media_send_with_slide_messaging_response") or {}
        if not res.get("message_id"):
            raise IGError("photo send returned no message_id", 502, d)
        return {"message_id": res["message_id"], "timestamp_ms": int(res.get("timestamp_ms") or 0), "attachment_fbid": fbid}

    def unsend(self, thread_fbid: str, message_id: str):
        t = self.thread_raw(thread_fbid)
        d = self.gql("IGDMessageUnsendDialogOffMsysMutation",
                     {"message_id": message_id, "send_data": {"thread_id": t["thread_id"]}}, write=True)
        if not d.get("direct_unsend_message"):
            raise IGError("unsend was not confirmed", 502, d)
        return {"ok": True, "message_id": message_id}

    # reactions: IGDirectReactionSendMutation {input: {emoji, item_id: "", message_id, reaction_status, thread_id}}
    def _react(self, thread_fbid: str, message_id: str, emoji: str, status: str):
        self.op("IGDirectReactionSendMutation", {"input": {"emoji": emoji, "item_id": "", "message_id": message_id,
                                                           "reaction_status": status, "thread_id": str(thread_fbid)}},
                write=True)
        return {"ok": True, "message_id": message_id, "emoji": emoji, "reaction_status": status}

    def react(self, thread_fbid: str, message_id: str, emoji: str = "❤"):
        return self._react(thread_fbid, message_id, emoji, "created")

    def unreact(self, thread_fbid: str, message_id: str, emoji: str = "❤"):
        return self._react(thread_fbid, message_id, emoji, "deleted")

    def share_media(self, code: str, thread_fbid: str | None = None, users: list[str] | None = None):
        """Share a post or reel into a chat (by thread) or to users (by username/pk)."""
        from .read import shortcode_to_pk
        pk = str(code) if str(code).isdigit() else shortcode_to_pk(code)
        if not thread_fbid and not users:
            raise IGError("give thread_fbid or users", 400)
        otid = _otid()
        recipients = __import__("json").dumps([self.user_id(u) for u in users]) if users else None
        send_data = {"forwarded_from_thread_id": None, "is_forwarded_from_own_message": None, "offline_threading_id": otid,
                     "recipient_users": recipients, "thread_id": None if recipients else str(thread_fbid)}
        # the web share sheet sends reels (product_type "clips") via IGDirectReelShareMutation and every other
        # post via IGDirectMediaShareMutation (IGDMAPISendMediaShare); the reel mutation returns null for photos
        if self.media_info(code).get("kind") != "reel":
            d = self.gql("IGDirectMediaShareMutation", {"data": {"media_id": pk}, "send_data": send_data}, write=True)
            r = d.get("direct_media_share_with_slide_response") or {}
            if not r.get("message_id"):
                raise IGError("share returned no message_id", 502, d)
            return {"message_id": r["message_id"], "timestamp_ms": int(r.get("timestamp_ms") or 0)}
        d = self.op("IGDirectReelShareMutation", {
            "ig_media_igid": pk, "otid": otid,
            "data": {"forwarded_from_thread_id": None, "is_forwarded_from_own_message": None, "offline_threading_id": otid,
                     "recipient_users": recipients, "thread_id": str(thread_fbid) if thread_fbid else None},
            "clip_share_params": {"inventory_source": "", "send_attribution": "igd_web_share_sheet:reel",
                                  "social_context_share_type": None, "text": None, "tracking_token": None}}, write=True)
        r = d.get("xig_direct_clip_share_with_slide_msg_response") or {}
        if not r.get("message_id"):
            raise IGError("share returned no message_id", 502, d)
        return {"message_id": r["message_id"], "timestamp_ms": int(r.get("timestamp_ms") or 0)}

    def older_messages(self, thread_fbid: str, cursor: str, count: int = 20):
        """Messages before `cursor` (thread.page_info.end_cursor from GET /threads/{id}). Newest-last order."""
        d = self.op("IGDMessageListOffMsysQuery", {"id": str(thread_fbid), "after": cursor, "first": count,
                                                   "before": None, "last": None})
        t = (d.get("fetch__SlideThread") or {}).get("as_ig_direct_thread") or {}
        vf = self.state.get("viewer_fbid")
        conn = t.get("slide_messages") or {}
        msgs = sorted((self._message(e["node"], vf) for e in conn.get("edges") or []), key=lambda m: m["timestamp_ms"])
        pi = conn.get("page_info") or {}
        return {"messages": msgs, "next_cursor": pi.get("end_cursor") if pi.get("has_next_page") else None}
