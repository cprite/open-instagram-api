"""Realtime DM events over Instagram's "lightspeed" gateway WebSocket (what instagram.com itself listens on).

Protocol (captured from the web client, see docs/PROTOCOL.md):
  connect  wss://gateway.instagram.com/ws/lightspeed?x-dgw-appid=…&x-dgw-uuid=<actor id>&x-dgw-deviceid=<uuid>…
           with the session cookies and Origin https://www.instagram.com
  frame    [type:1][0x00 0x00][len:uint16 LE][0x00][payload:len]
           0x0f open stream ("{}"), 0x0d data, 0x0c ack (payload [seq, 0]), 0x09 ping / 0x0a pong
  data     payload = [seq][0x80] + JSON {"request_id", "payload": base64(protobuf)}; the protobuf wraps JSON
           GraphQL responses whose data.slide_delta_processor[] lists deltas, e.g. SlideUQPPNewMessage.
  subscribe  one 0x0f "{}" frame + one 0x0d frame with a sync request (database 223, user_agent "WMI Web").

Usage:
    async for ev in Realtime(ig).events():   # ev = {"type": "message", "message": {...}, "raw": {...}}
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
import urllib.parse

import websockets

from .client import APP_ID, UA

GATEWAY = "wss://gateway.instagram.com/ws/lightspeed"
SYNC_DOC_ID = "28290309580642466"     # prevalidated_graphql_doc_id the web client sends with the sync request
PING_EVERY = 10


def _frame(ftype: int, payload: bytes) -> bytes:
    return bytes([ftype, 0, 0]) + len(payload).to_bytes(2, "little") + b"\x00" + payload


def _parse(buf: bytes):
    """Split a WebSocket message into DGW frames -> [(type, payload)]. Single-byte frames are ping/pong."""
    out, i = [], 0
    while i < len(buf):
        t = buf[i]
        if t in (0x09, 0x0A) and len(buf) - i < 6:
            out.append((t, b"")); i += 1; continue
        n = int.from_bytes(buf[i + 3:i + 5], "little")
        out.append((t, buf[i + 6:i + 6 + n])); i += 6 + n
    return out


def _pb_strings(b: bytes, depth=0):
    """Yield every length-delimited protobuf field (recursively) — the JSON lives in one of them."""
    i = 0
    while i < len(b) and depth < 6:
        key = 0; shift = 0
        while i < len(b):
            x = b[i]; i += 1; key |= (x & 0x7F) << shift; shift += 7
            if x < 0x80: break
        wt = key & 7
        if wt == 0:
            while i < len(b) and b[i] & 0x80: i += 1
            i += 1
        elif wt == 2:
            n = 0; shift = 0
            while i < len(b):
                x = b[i]; i += 1; n |= (x & 0x7F) << shift; shift += 7
                if x < 0x80: break
            chunk = b[i:i + n]; i += n
            yield chunk
            yield from _pb_strings(chunk, depth + 1)
        elif wt == 1:
            i += 8
        elif wt == 5:
            i += 4
        else:
            return


def _deltas(data_payload: bytes):
    """[seq][0x80]{json} -> list of slide_delta_processor items."""
    j = json.loads(data_payload[data_payload.index(b"{"):].decode("utf-8", "replace"))
    pb = base64.b64decode(j.get("payload") or "")
    out = []
    for s in _pb_strings(pb):
        if s[:1] not in (b"[", b"{"):
            continue
        try:
            doc = json.loads(s.decode("utf-8"))
        except ValueError:
            continue
        for resp in doc if isinstance(doc, list) else [doc]:
            out += ((resp or {}).get("data") or {}).get("slide_delta_processor") or []
    return out


def _error_name(data_payload: bytes):
    j = json.loads(data_payload[data_payload.index(b"{"):].decode("utf-8", "replace"))
    pb = base64.b64decode(j.get("payload") or "")
    for s in _pb_strings(pb):
        if s.endswith(b"Exception") and s.isascii():
            return s.decode()
    return None


class Realtime:
    def __init__(self, ig):
        self.ig = ig
        self.connected_at = None

    def _url(self):
        q = {"x-dgw-appid": APP_ID, "x-dgw-appversion": "0", "x-dgw-authtype": "6:0", "x-dgw-version": "5",
             "x-dgw-uuid": self.ig.tokens["av"], "x-dgw-tier": "prod", "x-dgw-deviceid": self.ig.state["device_id"]}
        return GATEWAY + "?" + urllib.parse.urlencode(q, safe=":")

    def _subscribe(self, seq_id=0):
        payload = {"database": 223, "epoch_id": 0, "failure_count": 0,
                   "last_applied_cursor": json.dumps({"seq_id": seq_id}, separators=(",", ":")),
                   "sync_params": json.dumps({"user_agent": "WMI Web", "snapshot_at_ms": int(time.time() * 1000),
                                              "prevalidated_graphql_doc_id": SYNC_DOC_ID}, separators=(",", ":")),
                   "version": -3}
        body = {"app_id": APP_ID, "device_id": self.ig.state["device_id"],
                "payload": json.dumps(payload, separators=(",", ":")), "request_id": 4, "type": 2}
        return _frame(0x0F, b"{}") + _frame(0x0D, b"\x00\x80" + json.dumps(body, separators=(",", ":")).encode())

    def _register(self) -> int:
        """Run the inbox query with our device id: it registers the device for an iris subscription and returns the
        sequence id to resume from (without it the gateway answers MDCoreIrisOverflowDeviceNotFoundException)."""
        d = self.ig.gql("PolarisDirectInboxQuery", self.ig._list_vars())
        mb = d.get("get_slide_mailbox_for_iris_subscription") or {}
        return int(mb.get("iris_inactive_subscription_uq_seq_id") or 0)

    async def _session(self):
        await asyncio.to_thread(self.ig.bootstrap)
        seq = await asyncio.to_thread(self._register)
        cookie = "; ".join(f"{c.name}={c.value}" for c in self.ig.s.cookies if c.domain.endswith("instagram.com"))
        headers = {"Cookie": cookie, "Origin": "https://www.instagram.com", "User-Agent": UA}
        async with websockets.connect(self._url(), additional_headers=headers, max_size=None,
                                      ping_interval=None, open_timeout=20) as ws:
            await ws.send(self._subscribe(seq))
            self.connected_at = time.time()
            yield {"type": "connected"}
            last_ping = time.time()
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2)
                except asyncio.TimeoutError:
                    msg = None
                if time.time() - last_ping >= PING_EVERY:
                    await ws.send(bytes([0x09])); last_ping = time.time()
                if msg is None:
                    continue
                buf = msg if isinstance(msg, bytes) else msg.encode()
                for ftype, payload in _parse(buf):
                    if ftype == 0x0F and payload and b'"code"' in payload and b"200" not in payload:
                        raise ConnectionError(f"gateway refused subscribe: {payload[:120]!r}")
                    if ftype != 0x0D or not payload:
                        continue
                    await ws.send(_frame(0x0C, bytes([payload[0], 0])))      # ack
                    if b"Exception" in payload[:400]:
                        err = _error_name(payload)
                        if err:
                            raise ConnectionError(f"gateway sync error: {err}")
                    for d in _deltas(payload):
                        yield self._event(d)

    def _event(self, d: dict):
        t = d.get("__typename") or ""
        if t == "SlideUQPPNewMessage":
            node = d.get("message") or d.get("slide_message") or d
            vf = self.ig.state.get("viewer_fbid")
            m = self.ig._message(node, vf)
            m["thread_fbid"] = node.get("thread_fbid") or d.get("thread_fbid")
            return {"type": "message", "message": m, "raw": d}
        return {"type": "delta", "delta_type": t, "raw": d}

    async def events(self, reconnect=True):
        """Yield events forever; reconnects with backoff. Raises only if reconnect=False."""
        backoff = 2
        while True:
            try:
                async for ev in self._session():
                    backoff = 2
                    yield ev
            except Exception as e:
                if not reconnect:
                    raise
                yield {"type": "disconnected", "error": f"{type(e).__name__}: {str(e)[:160]}"}
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 120)
                await asyncio.to_thread(self.ig.bootstrap, True)


class Hub:
    """One gateway connection shared by any number of subscribers (each gets its own asyncio.Queue)."""
    def __init__(self, ig):
        self.rt = Realtime(ig)
        self.subs: set[asyncio.Queue] = set()
        self.task = None
        self.status = {"state": "idle"}

    async def _pump(self):
        async for ev in self.rt.events():
            if ev["type"] in ("connected", "disconnected"):
                self.status = {"state": ev["type"], "at_ms": int(time.time() * 1000), **({"error": ev["error"]} if ev.get("error") else {})}
            for q in list(self.subs):
                if q.qsize() < 1000:
                    q.put_nowait(ev)

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        if self.status.get("state") == "connected":      # late joiner: tell it the stream is already up
            q.put_nowait({"type": "connected"})
        self.subs.add(q)
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._pump())
        return q

    def unsubscribe(self, q):
        self.subs.discard(q)
