"""Phase D: publishing — photo posts, carousels, caption edits, comments.

Not offered (Instagram ignores them from scripts — they return null / "payload": null and do nothing): publishing
reels (configure_to_clips) and deleting posts (web/create/<id>/delete/). Like block/restrict, these comet-envelope
endpoints are only honoured from instagram.com's own page JavaScript.

Flow captured from instagram.com's "New post" dialog:
  photo:    POST /rupload_igphoto/fb_uploader_<id> (raw JPEG)  ->  POST /api/v1/media/configure/
  carousel: one rupload_igphoto per item (no share_type)      ->  POST /api/v1/media/configure_sidecar/ (JSON)
  edit:     POST /api/v1/media/<pk>/edit_media/ (JSON caption_text)
  comment:  PolarisPostCommentInputRevampedMutation;  delete: usePolarisPostDeleteCommentMutation
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .client import IGError
from .read import media as norm_media, pk_to_shortcode
from .social import _media_pk

PROVENANCE = json.dumps({"origin": ["EXTERNAL"]}, separators=(",", ":"))


def _upload_id() -> str:
    return str(int(time.time() * 1000))


def _image_size(path: Path):
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def _as_jpeg(path: Path) -> bytes:
    """Instagram's web uploader sends JPEG; convert anything else (PNG, WEBP…)."""
    from PIL import Image
    import io
    if path.suffix.lower() in (".jpg", ".jpeg"):
        return path.read_bytes()
    with Image.open(path) as im:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=92)
        return buf.getvalue()



class PublishMixin:
    def _upload_photo(self, path: Path, upload_id: str, extra: dict | None = None):
        w, h = _image_size(path)
        params = {"media_type": 1, "upload_id": upload_id, "upload_media_height": h, "upload_media_width": w,
                  "provenance_metadata": PROVENANCE, **(extra or {})}
        return self.rupload("igphoto", upload_id, _as_jpeg(path), params, "image/jpeg")

    def post_photo(self, path: str, caption: str = ""):
        p = Path(path)
        uid = _upload_id()
        self._upload_photo(p, uid, {"share_type": "feed"})
        j = self.rest("POST", "media/configure/", data={
            "archive_only": "false", "caption": caption, "clips_share_preview_to_feed": "1", "disable_comments": "0",
            "disable_oa_reuse": "false", "like_and_view_counts_disabled": "0", "media_share_flow": "creation_flow",
            "source_type": "library", "upload_id": uid, "video_subtitles_enabled": "0"}, write=True)
        return self._posted(j)

    def post_carousel(self, paths: list[str], caption: str = ""):
        if not 2 <= len(paths) <= 10:
            raise IGError("a carousel needs 2-10 images", 400)
        children = []
        for p in paths:
            uid = _upload_id()
            self._upload_photo(Path(p), uid)
            children.append({"upload_id": uid})
            time.sleep(0.05)   # distinct millisecond upload ids
        j = self.rest("POST", "media/configure_sidecar/", json_body={
            "archive_only": False, "caption": caption, "children_metadata": children, "client_sidecar_id": _upload_id(),
            "disable_comments": "0", "like_and_view_counts_disabled": 0, "media_share_flow": "creation_flow",
            "source_type": "library"}, write=True)
        return self._posted(j)

    @staticmethod
    def _posted(j: dict):
        m = j.get("media") or {}
        if not m.get("pk") and not m.get("id"):
            raise IGError("publish returned no media", 502, j)
        pk = str(m.get("pk") or m.get("id")).split("_")[0]
        out = norm_media(m) if m.get("code") else {"pk": pk, "code": pk_to_shortcode(pk)}
        out["code"] = out.get("code") or pk_to_shortcode(pk)
        out["url"] = out.get("url") or f"https://www.instagram.com/p/{out['code']}/"
        return out

    def edit_caption(self, code: str, caption: str):
        pk = _media_pk(code)
        self.rest("POST", f"media/{pk}/edit_media/", json_body={
            "caption_text": caption, "coauthor_invites": json.dumps({"added": [], "in": [], "removed": []}),
            "usertags": json.dumps({"added": [], "in": [], "removed": []})}, write=True)
        return {"ok": True, "media_pk": pk}

    def comment(self, code: str, text: str):
        pk = _media_pk(code)
        d = self.op("PolarisPostCommentInputRevampedMutation", {"data": {"comment_text": text, "media_id": pk},
                                                                "root_connections": []}, write=True)
        node = next(iter(d.values()), {}) if isinstance(d, dict) else {}
        c = (node or {}).get("comment") or node or {}
        return {"ok": True, "media_pk": pk, "comment_pk": str(c.get("pk") or c.get("id") or "") or None, "result": node}

    def delete_comment(self, code: str, comment_pk: str):
        pk = _media_pk(code)
        d = self.op("usePolarisPostDeleteCommentMutation", {"input": {
            "actor_id": self.tokens.get("av"), "client_mutation_id": "1", "comment_id": str(comment_pk), "media_id": pk}},
            write=True)
        return {"ok": True, "media_pk": pk, "comment_pk": str(comment_pk), "result": next(iter(d.values()), None)}
