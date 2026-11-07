"""Phase C: social writes — like/unlike, save/unsave, follow/unfollow (+ comments, added with Phase D).

Block/unblock/restrict/unrestrict are intentionally not offered: Instagram ignores their GraphQL mutations when
they come from a script (they return null), and driving the web UI for them was too slow to be worth it.

All of these are writes: they go through the client's write pacing (WRITE_MIN_INTERVAL) and change what other
people can see. Inputs mirror what instagram.com sends (captured, see docs/PROTOCOL.md).
"""
from __future__ import annotations

import itertools

from .client import IGError
from .read import shortcode_to_pk

_mutation_ids = itertools.count(1)


def _media_pk(code_or_pk: str) -> str:
    s = str(code_or_pk)
    return s.split("_")[0] if s.replace("_", "").isdigit() else shortcode_to_pk(s)


class SocialMixin:
    def _media_input(self, code_or_pk, extra=None):
        return {"input": {"actor_id": self.tokens.get("av") or self._actor(), "client_mutation_id": str(next(_mutation_ids)),
                          "media_id": _media_pk(code_or_pk), **(extra or {})}}

    def _actor(self):
        self.bootstrap()
        return self.tokens["av"]

    @staticmethod
    def _first(d):
        return next(iter(d.values()), None) if isinstance(d, dict) else d

    # ---------- posts ----------
    def like(self, code: str):
        d = self.op("usePolarisLikeMediaXIGLikeMutation", self._media_input(code, {"container_module": "single_post",
                                                                                   "tracking_token": None}), write=True)
        return {"ok": True, "media_pk": _media_pk(code), "result": self._first(d)}

    def unlike(self, code: str):
        d = self.op("usePolarisLikeMediaXIGUnlikeMutation", self._media_input(code, {"tracking_token": None}), write=True)
        return {"ok": True, "media_pk": _media_pk(code), "result": self._first(d)}

    def save(self, code: str):
        d = self.op("usePolarisSaveMediaSaveMutation", self._media_input(code, {"container_module": "single_post",
                                                                                "inventory_source": None,
                                                                                "logging_info_token": None}), write=True)
        return {"ok": True, "media_pk": _media_pk(code), "result": self._first(d)}

    def unsave(self, code: str):
        d = self.op("usePolarisSaveMediaUnsaveMutation", self._media_input(code), write=True)
        return {"ok": True, "media_pk": _media_pk(code), "result": self._first(d)}

    # ---------- relationships ----------
    def _rel(self, op, user, key="target_user_id", as_list=False, extra=None):
        uid = self.user_id(user)
        d = self.op(op, {key: [uid] if as_list else uid, **(extra or {})}, write=True)
        return {"ok": True, "user_pk": uid, "result": self._first(d)}

    def follow(self, user: str):
        return self._rel("usePolarisFollowMutation", user, extra={"container_module": "profile", "nav_chain": None})

    def unfollow(self, user: str):
        return self._rel("usePolarisUnfollowMutation", user, extra={"container_module": "profile", "nav_chain": None})

    def friendship(self, user: str):
        fs = (self.user_info(user) or {}).get("friendship_status") or {}
        keys = ("following", "followed_by", "blocking", "is_restricted", "muting", "is_muting_reel",
                "outgoing_request", "incoming_request", "is_bestie")
        return {"user_pk": self.user_id(user), **{k: fs.get(k) for k in keys if k in fs}}
