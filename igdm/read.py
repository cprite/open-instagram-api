"""Phase A: read-only Instagram features (profiles, posts, reels, stories, highlights, comments,
likers, followers, feeds, explore, hashtags, locations, search, notifications, saved).

Every method returns a normalised dict; pass raw=True to get Instagram's response untouched.
Pagination: methods that page return {"items": [...], "next_cursor": str|None}; pass next_cursor back.
"""
from __future__ import annotations

import json
import re
import uuid

from .client import IGError

_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def shortcode_to_pk(code: str) -> str:
    n = 0
    for ch in code[:11]:
        n = n * 64 + _B64.index(ch)
    return str(n)


def pk_to_shortcode(pk) -> str:
    n, out = int(str(pk).split("_")[0]), ""
    while n:
        n, r = divmod(n, 64)
        out = _B64[r] + out
    return out


def _best(candidates):
    c = [x for x in candidates or [] if isinstance(x, dict) and x.get("url")]
    return max(c, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))["url"] if c else None


def user_brief(u: dict | None) -> dict | None:
    if not u:
        return None
    return {"pk": str(u.get("pk") or u.get("id") or "") or None, "username": u.get("username"),
            "full_name": u.get("full_name"), "is_private": u.get("is_private"), "is_verified": u.get("is_verified"),
            "profile_pic_url": u.get("profile_pic_url")}


def media(m: dict) -> dict:
    mt, pt = m.get("media_type"), m.get("product_type")
    kind = {1: "photo", 2: "video", 8: "carousel"}.get(mt, "other")
    if pt == "clips":
        kind = "reel"
    code = m.get("code")
    cap = m.get("caption") or {}
    loc = m.get("location") or None
    return {
        "pk": str(m.get("pk") or "").split("_")[0] or None, "id": m.get("id"), "code": code,
        "url": f"https://www.instagram.com/{'reel' if kind == 'reel' else 'p'}/{code}/" if code else None,
        "kind": kind, "taken_at": m.get("taken_at"),
        "caption": cap.get("text") if isinstance(cap, dict) else None,
        "like_count": m.get("like_count"), "comment_count": m.get("comment_count"),
        "play_count": m.get("play_count") or m.get("ig_play_count") or m.get("view_count"),
        "user": user_brief(m.get("user") or m.get("owner")),
        "image_url": _best((m.get("image_versions2") or {}).get("candidates")) or m.get("display_uri"),
        "video_url": _best(m.get("video_versions")),
        "carousel": [media(c) for c in m.get("carousel_media") or []] or None,
        "location": {"pk": str(loc.get("pk") or ""), "name": loc.get("name")} if isinstance(loc, dict) else None,
        "has_liked": m.get("has_liked"), "has_viewer_saved": m.get("has_viewer_saved"),
    }


def comment(n: dict) -> dict:
    return {"pk": str(n.get("pk") or n.get("id") or ""), "text": n.get("text"), "created_at": n.get("created_at"),
            "user": user_brief(n.get("user")), "like_count": n.get("comment_like_count"),
            "reply_count": n.get("child_comment_count"), "parent_pk": n.get("parent_comment_id"),
            "has_liked": n.get("has_liked_comment"), "is_pinned": n.get("is_pinned")}


def story_item(i: dict) -> dict:
    return {"pk": str(i.get("pk") or "").split("_")[0] or None, "id": i.get("id"), "taken_at": i.get("taken_at"),
            "expiring_at": i.get("expiring_at"), "kind": {1: "photo", 2: "video"}.get(i.get("media_type"), "other"),
            "image_url": _best((i.get("image_versions2") or {}).get("candidates")),
            "video_url": _best(i.get("video_versions")), "user": user_brief(i.get("user"))}


def _conn(c: dict | None, node_fn, key="node"):
    c = c or {}
    pi = c.get("page_info") or {}
    return {"items": [node_fn(e.get(key) or e) for e in c.get("edges") or []],
            "next_cursor": pi.get("end_cursor") if pi.get("has_next_page") else None}


class ReadMixin:
    # ---------- users ----------
    def search(self, query: str, raw=False):
        d = self.gql("PolarisSearchBoxRefetchableQuery", {
            "data": {"context": "blended", "include_reel": "true", "query": query, "rank_token": "",
                     "search_session_id": str(uuid.uuid4()), "search_surface": "web_top_search"}, "hasQuery": True})
        r = d.get("xdt_api__v1__fbsearch__topsearch_connection") or {}
        if raw:
            return r
        return {"users": [user_brief(x.get("user") or x) for x in r.get("users") or []],
                "hashtags": [{"name": (h.get("hashtag") or h).get("name"), "media_count": (h.get("hashtag") or h).get("media_count")}
                             for h in r.get("hashtags") or []],
                "places": [{"pk": str(((p.get("place") or p).get("location") or {}).get("pk") or ""),
                            "name": ((p.get("place") or p).get("location") or {}).get("name") or (p.get("place") or p).get("title")}
                           for p in r.get("places") or []]}

    def user_id(self, username_or_id: str) -> str:
        """Numeric user pk for a username (cached). Numeric input is returned as is."""
        s = str(username_or_id).lstrip("@")
        if s.isdigit():
            return s
        cache = self.state.setdefault("user_ids", {})
        if s.lower() in cache:
            return cache[s.lower()]
        for u in self.search(s)["users"]:
            if (u.get("username") or "").lower() == s.lower() and u.get("pk"):
                cache[s.lower()] = u["pk"]
                self._save_state()
                return u["pk"]
        raise IGError(f"user @{s} not found", 404)

    def user_info(self, user: str, raw=False):
        uid = self.user_id(user)
        d = self.op("PolarisProfilePageContentQuery", {"id": uid})
        u = d.get("user") or {}
        if raw:
            return d
        if not u:
            raise IGError(f"user {user} not found", 404)
        return {**user_brief(u), "biography": u.get("biography"), "external_url": u.get("external_url"),
                "bio_links": [{"title": b.get("title"), "url": b.get("url")} for b in u.get("bio_links") or []],
                "follower_count": u.get("follower_count"), "following_count": u.get("following_count"),
                "media_count": u.get("media_count"), "category": u.get("category"),
                "is_business": u.get("is_business"), "is_professional": u.get("is_professional_account"),
                "hd_profile_pic_url": (u.get("hd_profile_pic_url_info") or {}).get("url"),
                "mutual_followers_count": u.get("mutual_followers_count"),
                "has_story": bool(u.get("latest_reel_media")), "friendship_status": u.get("friendship_status")}

    def user_posts(self, user: str, cursor: str | None = None, count: int = 12, raw=False):
        username = user if not str(user).isdigit() else (self.user_info(user).get("username"))
        count = max(int(count), 6)   # Instagram returns an empty page for counts below ~6
        if cursor:
            d = self.op("PolarisProfilePostsTabContentQuery_connection",
                        {"username": username, "after": cursor, "first": count, "data": {"count": count}})
        else:
            d = self.op("PolarisProfilePostsQuery", {"username": username, "data": {"count": count}})
        c = d.get("xdt_api__v1__feed__user_timeline_graphql_connection")
        return d if raw else _conn(c, media)

    def user_reels(self, user: str, cursor: str | None = None, count: int = 12, raw=False):
        uid = self.user_id(user)
        if cursor:
            d = self.op("PolarisProfileReelsTabContentQuery_connection",
                        {"id": uid, "after": cursor, "first": count, "data": {"target_user_id": uid, "page_size": count}})
        else:
            d = self.op("PolarisProfileReelsTabContentQuery",
                        {"user_id": uid, "data": {"target_user_id": uid, "page_size": count}})
        c = (d.get("fetch__XDTUserDict") or {}).get("clips_connection") or d.get("xdt_api__v1__clips__user__connection_v2")
        return d if raw else _conn(c, lambda n: media(n.get("media") or n))

    def user_tagged(self, user: str, count: int = 12, raw=False):
        uid = self.user_id(user)
        d = self.op("PolarisProfileTaggedTabContentQuery", {"user_id": uid, "count": count})
        return d if raw else _conn(d.get("xdt_api__v1__usertags__user_id__feed_connection"), media)

    def user_highlights(self, user: str, raw=False):
        uid = self.user_id(user)
        d = self.op("PolarisProfileStoryHighlightsTrayContentQuery", {"user_id": uid})
        if raw:
            return d
        return {"items": [{"id": n.get("id", "").replace("highlight:", ""), "title": n.get("title"),
                           "cover_url": ((n.get("cover_media") or {}).get("cropped_image_version") or {}).get("url")}
                          for n in (e.get("node") or {} for e in (d.get("highlights") or {}).get("edges") or [])]}

    def highlight(self, highlight_id: str, raw=False):
        hid = f"highlight:{str(highlight_id).replace('highlight:', '')}"
        d = self.op("PolarisStoriesV3HighlightsPageQuery", {"initial_reel_id": hid, "reel_ids": [hid]})
        if raw:
            return d
        edges = (d.get("xdt_api__v1__feed__reels_media__connection") or {}).get("edges") or []
        reel = next((e["node"] for e in edges if (e.get("node") or {}).get("id") == hid), (edges[0]["node"] if edges else {}))
        return {"id": hid.split(":")[1], "title": reel.get("title"), "items": [story_item(i) for i in reel.get("items") or []]}

    def user_stories(self, user: str, raw=False):
        uid = self.user_id(user)
        d = self.op("PolarisStoriesV3ReelPageStandaloneQuery", {"reel_ids_arr": [uid]})
        if raw:
            return d
        reels = (d.get("xdt_api__v1__feed__reels_media") or {}).get("reels_media") or []
        return {"items": [story_item(i) for r in reels for i in r.get("items") or []]}

    def story_tray(self, raw=False):
        d = self.op("PolarisStoriesV3TrayContainerQuery")
        if raw:
            return d
        tray = (d.get("xdt_api__v1__feed__reels_tray") or {}).get("tray") or []
        return {"items": [{"user": user_brief(t.get("user")), "reel_id": str(t.get("id")),
                           "latest_reel_media": t.get("latest_reel_media"), "seen": t.get("seen"),
                           "has_besties_media": t.get("has_besties_media")} for t in tray]}

    def _friendships(self, kind: str, user: str, cursor: str | None, count: int, raw: bool):
        uid = self.user_id(user)
        p = {"count": count, "search_surface": "follow_list_page"}
        if cursor:
            p["max_id"] = cursor
        j = self.rest("GET", f"friendships/{uid}/{kind}/", p)
        if raw:
            return j
        # For other people's large accounts the web only serves the first page (Instagram policy):
        # should_limit_list_of_followers=true and no next_max_id, exactly as on instagram.com.
        return {"items": [user_brief(u) for u in j.get("users") or []], "next_cursor": j.get("next_max_id"),
                "limited": bool(j.get("should_limit_list_of_followers") or j.get("should_limit_list_of_followings"))
                           and not j.get("next_max_id")}

    def followers(self, user: str, cursor: str | None = None, count: int = 25, raw=False):
        return self._friendships("followers", user, cursor, count, raw)

    def following(self, user: str, cursor: str | None = None, count: int = 25, raw=False):
        return self._friendships("following", user, cursor, count, raw)

    # ---------- media ----------
    def media_info(self, code: str, raw=False):
        code = code if not str(code).isdigit() else pk_to_shortcode(code)
        try:
            d = self.op("PolarisPostRootQuery", {"shortcode": code})
        except IGError as e:
            if e.status == 502 and "GraphQL errors" in str(e):   # deleted / unavailable post
                raise IGError(f"post {code} not found", 404, e.detail)
            raise
        items = (d.get("xdt_api__v1__media__shortcode__web_info") or {}).get("items") or []
        if not items:
            raise IGError(f"post {code} not found", 404)
        return d if raw else media(items[0])

    def media_comments(self, code: str, cursor: str | None = None, count: int = 20, sort="popular", raw=False):
        mid = shortcode_to_pk(code) if not str(code).isdigit() else str(code)
        if cursor:
            d = self.op("PolarisPostCommentsPaginationQuery", {"media_id": mid, "after": cursor, "first": count, "sort_order": sort})
        else:
            d = self.op("PolarisPostCommentsContainerQuery", {"media_id": mid})
        c = (d.get("comments_media") or {}).get("comments_connection")
        return d if raw else _conn(c, comment)

    def comment_replies(self, comment_pk: str, cursor: str | None = None, raw=False):
        d = self.op("PolarisPostChildCommentsQuery", {"parent_comment_id": str(comment_pk), "after": cursor, "first": None})
        c = (d.get("fetch__XIGComment") or {}).get("parent_comment_connection") or \
            next((v for v in (d.get("fetch__XIGComment") or {}).values() if isinstance(v, dict) and "edges" in v), None)
        return d if raw else _conn(c, comment)

    def media_likers(self, code: str, raw=False):
        mid = shortcode_to_pk(code) if not str(code).isdigit() else str(code)
        j = self.rest("GET", f"media/{mid}/likers/")
        return j if raw else {"items": [user_brief(u) for u in j.get("users") or []], "count": j.get("user_count")}

    # ---------- feeds ----------
    def timeline(self, cursor: str | None = None, raw=False):
        j = self.rest("GET", "feed/timeline/", {"max_id": cursor} if cursor else None)
        if raw:
            return j
        items = []
        for x in j.get("feed_items") or []:
            suggested = "explore_story" in x
            m = (x.get("explore_story") or x).get("media_or_ad") or {}
            if m.get("code") and not m.get("injected"):      # skip ads (injected)
                items.append({**media(m), "suggested": suggested})
        return {"items": items, "next_cursor": j.get("next_max_id") if j.get("more_available") else None}

    def reels_feed(self, cursor: str | None = None, raw=False):
        d = self.op("PolarisClipsTabDesktopPaginationQuery", {"after": cursor})
        return d if raw else _conn(d.get("xdt_api__v1__clips__home__connection_v2"), lambda n: media(n.get("media") or n))

    def explore(self, cursor: str | None = None, raw=False):
        j = self.rest("GET", "discover/web/explore_grid/", {"max_id": cursor} if cursor else None)
        if raw:
            return j
        out = []
        for sec in j.get("sectional_items") or []:
            lc = sec.get("layout_content") or {}
            for f in ("medias", "fill_items", "one_by_two_item"):
                v = lc.get(f)
                for it in (v if isinstance(v, list) else [v] if v else []):
                    m = it.get("media") or (it.get("clips") or {}).get("items", [{}])[0].get("media") if isinstance(it, dict) else None
                    if m and m.get("code"):
                        out.append(media(m))
        return {"items": out, "next_cursor": j.get("next_max_id") if j.get("more_available") else None}

    def hashtag(self, tag: str, raw=False):
        d = self.op("PolarisKeywordSearchExplorePageRelayQuery",
                    {"query": f"#{tag.lstrip('#')}", "search_session_id": str(uuid.uuid4()), "serp_session_id": str(uuid.uuid4())})
        if raw:
            return d
        out = []
        for e in (d.get("xdt_fbsearch__top_serp_graphql") or {}).get("edges") or []:
            for it in ((e.get("node") or {}).get("items") or []):
                m = (it.get("media") or it) if isinstance(it, dict) else None
                if m and m.get("code"):
                    out.append(media(m))
        return {"tag": tag.lstrip("#"), "items": out}

    def location(self, location_id: str, tab: str = "ranked", cursor: str | None = None, raw=False):
        if cursor:
            d = self.op("PolarisLocationPageTabContentQuery_connection", {"location_id": str(location_id), "tab": tab, "after": cursor})
        else:
            d = self.op("PolarisLocationPageTabContentQuery", {"location_id": str(location_id), "tab": tab})
        c = d.get("xdt_location_get_web_info_tab") or {}
        if raw:
            return d
        out = []
        for e in c.get("edges") or []:
            n = e.get("node") or {}
            for m in [n] + [x.get("media") for x in n.get("medias") or [] if isinstance(x, dict)]:
                if isinstance(m, dict) and m.get("code"):
                    out.append(media(m))
        pi = c.get("page_info") or {}
        return {"items": out, "next_cursor": pi.get("end_cursor") if pi.get("has_next_page") else None}

    def notifications(self, raw=False):
        j = self.rest("GET", "news/inbox/")
        if raw:
            return j
        def story(s):
            a = s.get("args") or {}
            return {"type": s.get("story_type"), "text": a.get("rich_text") or a.get("text"), "timestamp": a.get("timestamp"),
                    "user": {"pk": str(a.get("profile_id") or ""), "username": a.get("profile_name")},
                    "media_code": ((a.get("media") or [{}])[0] or {}).get("shortcode") if a.get("media") else None}
        return {"counts": j.get("counts"), "new": [story(s) for s in j.get("new_stories") or []],
                "old": [story(s) for s in j.get("old_stories") or []]}

    def saved(self, count: int = 12, raw=False):
        d = self.op("PolarisProfileSavedTabContentQuery", {"first": count})
        if raw:
            return d
        c = ((d.get("viewer") or {}).get("collections_unified_with_auto_collections") or {})
        return {"collections": [{"id": n.get("collection_id") or n.get("id"), "name": n.get("collection_name") or n.get("name"),
                                 "type": n.get("collection_type"), "media_count": n.get("collection_media_count")}
                                for n in (e.get("node") or {} for e in c.get("edges") or [])]}
