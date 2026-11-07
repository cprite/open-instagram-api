"""Instagram web-DM client over the www.instagram.com GraphQL ("Slide" messaging) endpoints.

Reverse-engineered from captured web traffic (see docs/PROTOCOL.md). No browser at runtime:
cookies -> scrape fb_dtsg/lsd/etc. from /direct/inbox/ HTML -> POST /api/graphql with persisted doc_ids.
doc_ids are auto-discovered from the JS bundles (`<Name>_instagramRelayOperation` modules) and cached.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import random
import re
import threading
import time
import uuid
from pathlib import Path

import requests

HOME = Path(os.environ.get("IGDM_HOME", Path(__file__).resolve().parent.parent))
COOKIES = HOME / "cookies.json"
DOC_IDS = HOME / "doc_ids.json"
STATE = HOME / "state.json"

APP_ID = "936619743392459"
ASBD_ID = "359341"
UA = ("Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/142.0.0.0 Safari/537.36")
OPS = [
    "PolarisDirectInboxQuery", "PolarisDirectMessageRequestQuery", "IGDThreadDetailQuery",
    "IGDirectTextSendMutation", "useIGDMarkThreadAsReadMutation", "useIGDirectAcceptMessageRequestMutation",
]
WRITE_MIN_INTERVAL = 2.5   # seconds between write calls (ban-risk hygiene)
TOKEN_TTL = 30 * 60        # re-scrape page tokens every 30 min


class IGError(Exception):
    def __init__(self, msg, status=502, detail=None):
        super().__init__(msg)
        self.status, self.detail = status, detail


class SessionExpired(IGError):
    def __init__(self, detail=None):
        super().__init__("Instagram session is not logged in (re-export cookies)", 401, detail)


def _otid() -> str:
    """offline_threading_id as the web client makes it: (epoch_ms << 22) | 22 random bits."""
    return str((int(time.time() * 1000) << 22) | random.getrandbits(22))


class IGDirect:
    def __init__(self):
        self.lock = threading.RLock()
        self._last_write = 0.0
        self.tokens: dict = {}
        self.tokens_at = 0.0
        self.state = json.loads(STATE.read_text()) if STATE.exists() else {}
        if "device_id" not in self.state:
            self.state["device_id"] = str(uuid.uuid4())
            self._save_state()
        self.doc_ids = {k: v["doc_id"] if isinstance(v, dict) else v
                        for k, v in (json.loads(DOC_IDS.read_text()) if DOC_IDS.exists() else {}).items()}
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"})
        self._raw_cookies = json.loads(COOKIES.read_text())
        for c in self._raw_cookies:
            if c["name"] == "rur":   # escaped value confuses requests; server re-issues it
                continue
            self.s.cookies.set(c["name"], c["value"], domain=".instagram.com", path="/")

    # ---------- persistence ----------
    def _save_state(self):
        STATE.write_text(json.dumps(self.state, indent=1))
        os.chmod(STATE, 0o600)

    def _persist_cookies(self):
        """Write rotated cookie values back into cookies.json (same export format)."""
        jar = {c.name: c.value for c in self.s.cookies if c.domain.endswith("instagram.com")}
        changed = False
        for c in self._raw_cookies:
            if c["name"] in jar and jar[c["name"]] != c["value"] and c["name"] != "rur":
                c["value"], changed = jar[c["name"]], True
        if changed:
            tmp = COOKIES.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._raw_cookies))
            os.chmod(tmp, 0o600)
            tmp.replace(COOKIES)

    # ---------- bootstrap ----------
    def _html(self) -> str:
        r = self.s.get("https://www.instagram.com/direct/inbox/", timeout=30)
        if r.status_code != 200 or "not-logged-in" in r.text[:3000] or "/accounts/login" in r.url:
            raise SessionExpired(f"inbox page: HTTP {r.status_code} {r.url}")
        return r.text

    def bootstrap(self, force=False):
        with self.lock:
            if self.tokens and not force and time.time() - self.tokens_at < TOKEN_TTL:
                return
            html = self._html()
            pat = lambda p: (re.search(p, html) or [None, None])[1]
            t = {
                "fb_dtsg": pat(r'"DTSGInitialData",\[\],\{"token":"([^"]+)"') or pat(r'"dtsg":\{"token":"([^"]+)"'),
                "lsd": pat(r'"LSD",\[\],\{"token":"([^"]+)"'),
                "av": pat(r'"actorID":"(\d+)"'),
                "rev": pat(r'"server_revision":(\d+)'),
                "hs": pat(r'"haste_session":"([^"]+)"'),
                "hsi": pat(r'"hsi":"(\d+)"'),
                "spin_t": pat(r'"__spin_t":(\d+)'),
                "spin_b": pat(r'"__spin_b":"([^"]+)"') or "trunk",
            }
            missing = [k for k in ("fb_dtsg", "lsd", "av", "rev") if not t[k]]
            if missing:
                raise IGError(f"could not scrape page tokens {missing} (IG web changed?)")
            self.tokens, self.tokens_at, self._html_cache = t, time.time(), html
            if any(op not in self.doc_ids for op in OPS):
                self.refresh_doc_ids(html)
            self._persist_cookies()

    def refresh_doc_ids(self, html: str | None = None):
        """Scan the JS bundles referenced by the inbox page for `<Op>_instagramRelayOperation` doc_ids."""
        html = (html or self._html()).replace("\\/", "/")
        srcs = sorted(set(re.findall(r'(https://static\.cdninstagram\.com/rsrc\.php/[^"\\]+\.js[^"\\]*)', html)))
        found: dict[str, str] = {}
        rx = re.compile(r'__d\("(\w+)_instagramRelayOperation",\[\],\(function\(\w(?:,\w)*\)\{\w\.exports="(\d+)"')

        def fetch(u):
            try:
                return requests.get(u, timeout=20, headers={"User-Agent": UA}).text
            except requests.RequestException:
                return ""
        with cf.ThreadPoolExecutor(8) as ex:
            for js in ex.map(fetch, srcs):
                for m in rx.finditer(js):
                    found[m.group(1)] = m.group(2)
        if not found:
            raise IGError("doc_id discovery found nothing in bundles")
        self.doc_ids.update(found)
        DOC_IDS.write_text(json.dumps({k: self.doc_ids[k] for k in sorted(self.doc_ids)}, indent=0))
        return {op: self.doc_ids.get(op) for op in OPS}

    # ---------- transport ----------
    def gql(self, name: str, variables: dict, write=False, _retry=True):
        self.bootstrap()
        with self.lock:
            if write:
                wait = WRITE_MIN_INTERVAL - (time.time() - self._last_write)
                if wait > 0:
                    time.sleep(wait + random.uniform(0, 0.8))
            t, doc = self.tokens, self.doc_ids.get(name)
            if not doc:
                self.refresh_doc_ids()
                doc = self.doc_ids.get(name)
                if not doc:
                    raise IGError(f"no doc_id for {name}")
            data = {
                "av": t["av"], "__d": "www", "__user": "0", "__a": "1", "__req": format(random.randint(1, 60), "x"),
                "__hs": t["hs"], "dpr": "1", "__ccg": "EXCELLENT", "__rev": t["rev"], "__hsi": t["hsi"],
                "__comet_req": "7", "fb_dtsg": t["fb_dtsg"], "jazoest": "2" + str(sum(map(ord, t["fb_dtsg"]))),
                "lsd": t["lsd"], "__spin_r": t["rev"], "__spin_b": t["spin_b"], "__spin_t": t["spin_t"],
                "fb_api_caller_class": "RelayModern", "fb_api_req_friendly_name": name, "server_timestamps": "true",
                "variables": json.dumps(variables, separators=(",", ":"), ensure_ascii=False), "doc_id": doc,
            }
            csrf = self.s.cookies.get("csrftoken", domain=".instagram.com") or ""
            h = {"X-FB-Friendly-Name": name, "X-FB-LSD": t["lsd"], "X-CSRFToken": csrf, "X-IG-App-ID": APP_ID,
                 "X-ASBD-ID": ASBD_ID, "Origin": "https://www.instagram.com",
                 "Referer": "https://www.instagram.com/direct/inbox/", "Sec-Fetch-Site": "same-origin",
                 "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
            r = self.s.post("https://www.instagram.com/api/graphql", data=data, headers=h, timeout=30)
            if write:
                self._last_write = time.time()
        body = r.text
        if body.startswith("for (;;);"):
            body = body[9:]
        try:
            j = json.loads(body)
        except ValueError:
            raise IGError(f"{name}: non-JSON HTTP {r.status_code}", 502, body[:300])
        if "error" in j and "data" not in j:   # comet error envelope
            code = j.get("error")
            if _retry and code in (1357001, 1357004, 1357054, 1357055):
                self.bootstrap(force=True)
                if code == 1357054:
                    self.refresh_doc_ids()
                return self.gql(name, variables, write, _retry=False)
            if code == 1357001:
                raise SessionExpired(j.get("errorSummary"))
            raise IGError(f"{name}: IG error {code} {j.get('errorSummary')}", 502, j.get("errorDescription"))
        if j.get("errors") and not j.get("data"):
            msg = json.dumps(j["errors"])[:400]
            if _retry and ("doc_id" in msg.lower() or "persisted" in msg.lower()):
                self.refresh_doc_ids()
                return self.gql(name, variables, write, _retry=False)
            raise IGError(f"{name}: GraphQL errors", 502, j["errors"])
        self._persist_cookies()
        return j["data"]

    # ---------- normalisers ----------
    @staticmethod
    def _user(u):
        return {"username": u.get("username"), "full_name": u.get("full_name"), "ig_id": u.get("id") or u.get("pk"),
                "fbid": u.get("interop_messaging_user_fbid"), "profile_pic_url": u.get("profile_pic_url"),
                "is_verified": u.get("is_verified")}

    def _viewer_fbid(self, thread=None):
        v = (thread or {}).get("viewer") or {}
        if v.get("interop_messaging_user_fbid"):
            self.state["viewer_fbid"] = v["interop_messaging_user_fbid"]
            self._save_state()
        return self.state.get("viewer_fbid")

    @staticmethod
    def _classify(n, c):
        """-> (kind, share). kind: text | image | reel | post | story | profile | link | share | other.
        Shared content arrives as content_type MESSAGE_INLINE_SHARE / SlideMessageXMAContent; the XMA carries
        target_url (/reel/, /p/, /stories/ …) and preview_image_decoration_type ("REEL" for reels)."""
        ct = n.get("content_type") or ""
        xma = c.get("xma") if isinstance(c.get("xma"), dict) else None
        if xma is None and isinstance(c.get("xmas"), list) and c["xmas"]:
            xma = c["xmas"][0]
        if xma:
            url = xma.get("target_url") or ""
            deco = ((xma.get("preview_image") or xma.get("xmaPreviewImage") or {}).get("preview_image_decoration_type") or "")
            m = re.search(r"instagram\.com/(reels?|p|tv|stories)/([^/?]+)", url)
            path = m.group(1) if m else ""
            if path in ("reel", "reels", "tv") or deco.upper() == "REEL":
                kind = "reel"
            elif path == "p":
                kind = "post"
            elif path == "stories":
                kind = "story"
            elif re.search(r"instagram\.com/[A-Za-z0-9._]+/?$", url):
                kind = "profile"
            elif url:
                kind = "link"
            else:
                kind = "share"
            return kind, {"url": url or None, "shortcode": m.group(2) if m else None,
                          "author": xma.get("header_title_text") or xma.get("xmaHeaderTitle"),
                          "preview_url": (xma.get("preview_image") or {}).get("url"),
                          "caption": c.get("xma_text_body") or None}
        if ct == "TEXT":
            return "text", None
        if ct in ("IMAGES", "IMAGE", "PHOTO"):
            return "image", None
        if "VIDEO" in ct:
            return "video", None
        return "other", None

    def _message(self, n, viewer_fbid):
        c = n.get("content") or {}
        atts = [{"type": a.get("attachment_type"), "fbid": a.get("attachment_fbid"), "url": a.get("attachment_cdn_url"),
                 "preview_url": a.get("preview_cdn_url"), "width": a.get("preview_width"),
                 "height": a.get("preview_height")} for a in c.get("attachments") or []]
        sender = n.get("sender") or {}
        kind, share = self._classify(n, c)
        return {
            "id": n.get("message_id") or n.get("id"),
            "timestamp_ms": int(n.get("timestamp_ms") or 0),
            "kind": kind,
            "share": share,
            "type": n.get("content_type"),
            "content_typename": c.get("__typename"),
            "text": n.get("text_body") or c.get("text_body"),
            "attachments": atts,
            "sender_fbid": n.get("sender_fbid"),
            "sender_username": (sender.get("user_dict") or {}).get("username") or sender.get("name"),
            "is_from_me": bool(viewer_fbid) and n.get("sender_fbid") == viewer_fbid,
            "replied_to_message_id": n.get("replied_to_message_id"),
            "reactions": n.get("reactions") or n.get("msg_reactions") or [],
        }

    def _thread_summary(self, t):
        msgs = [e["node"] for e in (t.get("slide_messages") or {}).get("edges", [])]
        last = msgs[0] if msgs else None
        return {
            "thread_fbid": t.get("thread_fbid") or t.get("id"),
            "thread_id": t.get("thread_id"),
            "title": t.get("thread_title"),
            "is_group": t.get("is_group"),
            "folder": t.get("system_folder") or t.get("messaging_folder_tag"),
            "users": [self._user(u) for u in t.get("users") or []],
            "last_activity_ms": int(t.get("last_activity_timestamp_ms") or 0),
            "marked_as_unread": t.get("marked_as_unread"),
            "is_muted": t.get("is_muted"),
            "last_message": None if not last else {
                "id": last.get("id"), "timestamp_ms": int(last.get("timestamp_ms") or 0),
                "type": last.get("content_type"), "snippet": last.get("igd_snippet") or last.get("text_body"),
                "sender_fbid": last.get("sender_fbid")},
        }

    # ---------- operations ----------
    def _list_vars(self):
        return {"device_id_for_iris_subscription": self.state["device_id"],
                "__relay_internal__pv__IGDIsProfessionalAccountGKrelayprovider": False,
                "__relay_internal__pv__IGDPinnedThreadsRenderEnabledGKrelayprovider": True,
                "__relay_internal__pv__IGDMaxUnreadMessagesCountrelayprovider": 5,
                "__relay_internal__pv__IGDThreadListActionsEnabledGKrelayprovider": True}

    def list_threads(self, folder="inbox"):
        if folder == "requests":
            v = self._list_vars()
            v.pop("__relay_internal__pv__IGDIsProfessionalAccountGKrelayprovider")
            v["__relay_internal__pv__IGD30DayAgoTimestampMsrelayprovider"] = str(int(time.time() * 1000) - 30 * 86400000)
            d = self.gql("PolarisDirectMessageRequestQuery", v)
        else:
            d = self.gql("PolarisDirectInboxQuery", self._list_vars())
        mb = d.get("get_slide_mailbox_for_iris_subscription") or {}
        tbf = mb.get("threads_by_folder") or {}
        threads = [self._thread_summary(e["node"].get("as_ig_direct_thread") or e["node"]) for e in tbf.get("edges", [])]
        pinned = [p.get("thread_fbid") or p.get("id") for p in mb.get("pinned_threads_v2") or [] if isinstance(p, dict)]
        return {"folder": folder, "threads": threads, "pinned": pinned, "page_info": tbf.get("page_info")}

    def unread(self):
        """Threads whose newest message was NOT sent by me (i.e. awaiting a reply), across inbox + requests.
        (IG's useIGDSystemFolderUnreadThreadCountQuery turned out to list all folder threads, so it isn't used.)"""
        vf = self.state.get("viewer_fbid")
        if not vf:
            th = self.list_threads("inbox")["threads"]
            if th:
                self.thread(th[0]["thread_fbid"])
            vf = self.state.get("viewer_fbid")
        out = {}
        for folder in ("inbox", "requests"):
            out[folder] = [{"thread_fbid": t["thread_fbid"], "title": t["title"], "last_activity_ms": t["last_activity_ms"],
                            "snippet": (t["last_message"] or {}).get("snippet")}
                           for t in self.list_threads(folder)["threads"]
                           if t["last_message"] and t["last_message"]["sender_fbid"] != vf]
        return {"awaiting_reply_inbox": len(out["inbox"]), "awaiting_reply_requests": len(out["requests"]), **out}

    def thread_raw(self, thread_fbid: str):
        d = self.gql("IGDThreadDetailQuery", {
            "min_uq_seq_id": None, "thread_fbid": str(thread_fbid),
            "__relay_internal__pv__IGDEnableOffMsysChatThemesQErelayprovider": False,
            "__relay_internal__pv__IGDInitialMessagePageCountrelayprovider": 20})
        t = (d.get("get_slide_thread_nullable") or {}).get("as_ig_direct_thread")
        if not t:
            raise IGError(f"thread {thread_fbid} not found", 404)
        return t

    def thread(self, thread_fbid: str):
        t = self.thread_raw(thread_fbid)
        vf = self._viewer_fbid(t)
        msgs = [self._message(e["node"], vf) for e in (t.get("slide_messages") or {}).get("edges", [])]
        msgs.sort(key=lambda m: m["timestamp_ms"])
        return {**self._thread_summary(t), "messages": msgs, "page_info": (t.get("slide_messages") or {}).get("page_info"),
                "read_receipts": t.get("slide_read_receipts")}

    def send_text(self, thread_fbid: str, text: str, reply_to_message_id: str | None = None):
        if not text or not text.strip():
            raise IGError("empty text", 400)
        d = self.gql("IGDirectTextSendMutation", {
            "ig_thread_igid": str(thread_fbid), "offline_threading_id": _otid(), "recipient_igids": None,
            "replied_to_client_context": None, "replied_to_item_id": None, "reply_to_message_id": reply_to_message_id,
            "sampled": None, "text": {"sensitive_string_value": text}, "mentions": [], "mentioned_user_ids": [],
            "commands": None, "forwarded_from_thread_id": None, "is_forwarded_from_own_message": None,
            "send_attribution": "igd_web_chat_tab:in_thread"}, write=True)
        r = d.get("xig_direct_text_send_with_slide_messaging_response") or {}
        if not r.get("message_id"):
            raise IGError("send returned no message_id", 502, d)
        return {"message_id": r["message_id"], "timestamp_ms": int(r.get("timestamp_ms") or 0)}

    def mark_seen(self, thread_fbid: str, message_id: str | None = None):
        t = self.thread_raw(thread_fbid)
        if not message_id:
            edges = (t.get("slide_messages") or {}).get("edges", [])
            if not edges:
                raise IGError("thread has no messages", 400)
            message_id = max((e["node"] for e in edges), key=lambda n: int(n.get("timestamp_ms") or 0))["message_id"]
        d = self.gql("useIGDMarkThreadAsReadMutation", {
            "metadata": {"ig_thread_igid": t["thread_id"]}, "data": {"item_id": "", "message_id": message_id}}, write=True)
        r = d.get("xig_direct_item_seen_mutation_with_slide_messaging_response") or {}
        return {"message_id": message_id, "watermark_timestamp_ms": int(r.get("watermark_timestamp_ms") or 0)}

    def accept_request(self, thread_fbid: str):
        d = self.gql("useIGDirectAcceptMessageRequestMutation", {
            "thread_fbid": str(thread_fbid), "ig_inbox_folder": None, "offline_threading_id": _otid()}, write=True)
        r = d.get("ig_direct_accept_message_request") or {}
        return {"thread_fbid": r.get("id"), "system_folder": r.get("system_folder"), "folder": r.get("folder")}

    def updates(self, since_ms: int, include_requests=True):
        """New messages (not sent by me) since `since_ms`, by polling thread lists + changed threads."""
        threads = self.list_threads("inbox")["threads"]
        if include_requests:
            threads += self.list_threads("requests")["threads"]
        new, cursor = [], since_ms
        for t in threads:
            if t["last_activity_ms"] <= since_ms:
                continue
            full = self.thread(t["thread_fbid"])
            for m in full["messages"]:
                if m["timestamp_ms"] > since_ms and not m["is_from_me"]:
                    new.append({**m, "thread_fbid": t["thread_fbid"], "thread_title": t["title"], "folder": t["folder"]})
            cursor = max(cursor, t["last_activity_ms"])
        new.sort(key=lambda m: m["timestamp_ms"])
        return {"since_ms": since_ms, "next_since_ms": cursor, "messages": new}
