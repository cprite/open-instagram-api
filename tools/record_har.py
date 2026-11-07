"""Record a Chrome-DevTools-style HAR (incl. _webSocketMessages + bodies) from the CDP page target.
usage: record_har.py <targetId> <seconds> <out.har> [reload|url:<url>|none]"""
import asyncio, json, sys, time, base64, urllib.request, websockets, datetime
tid, secs, out, action = sys.argv[1], float(sys.argv[2]), sys.argv[3], (sys.argv[4] if len(sys.argv) > 4 else "reload")
async def main():
    ws_url = [t for t in json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/list")) if t["id"] == tid][0]["webSocketDebuggerUrl"]
    reqs, wss, pending, nid = {}, {}, {}, [0]
    async with websockets.connect(ws_url, max_size=None) as ws:
        async def call(method, params=None):
            nid[0] += 1; i = nid[0]; fut = asyncio.get_running_loop().create_future(); pending[i] = fut
            await ws.send(json.dumps({"id": i, "method": method, "params": params or {}})); return await fut
        async def reader():
            async for raw in ws:
                m = json.loads(raw)
                if "id" in m:
                    f = pending.pop(m["id"], None)
                    if f and not f.done(): f.set_result(m.get("result", {"error": m.get("error")}))
                    continue
                meth, p = m.get("method"), m.get("params", {})
                if meth == "Network.requestWillBeSent":
                    reqs[p["requestId"]] = {"req": p["request"], "t": p["wallTime"], "type": p.get("type")}
                elif meth == "Network.responseReceived" and p["requestId"] in reqs:
                    reqs[p["requestId"]]["resp"] = p["response"]
                elif meth == "Network.loadingFinished" and p["requestId"] in reqs:
                    reqs[p["requestId"]]["done"] = True
                elif meth == "Network.webSocketCreated":
                    wss[p["requestId"]] = {"url": p["url"], "msgs": [], "t": time.time()}
                elif meth in ("Network.webSocketFrameSent", "Network.webSocketFrameReceived") and p["requestId"] in wss:
                    f = p["response"]; wss[p["requestId"]]["msgs"].append({"type": "send" if meth.endswith("Sent") else "receive",
                        "time": p["timestamp"], "opcode": f["opcode"], "data": f["payloadData"]})
        rt = asyncio.create_task(reader())
        await call("Network.enable", {"maxPostDataSize": 1 << 20})
        if action == "reload": await call("Page.reload")
        elif action.startswith("url:"): await call("Page.navigate", {"url": action[4:]})
        await asyncio.sleep(secs)
        for rid, r in list(reqs.items()):
            if r.get("done") and r["type"] in ("XHR", "Fetch", "Document"):
                b = await call("Network.getResponseBody", {"requestId": rid})
                if "body" in b: r["body"] = b["body"] if not b.get("base64Encoded") else base64.b64decode(b["body"]).decode("utf-8", "replace")
        rt.cancel()
    iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()
    entries = []
    for rid, r in reqs.items():
        q, s = r["req"], r.get("resp", {})
        e = {"startedDateTime": iso(r["t"]), "time": 0, "_resourceType": (r["type"] or "").lower(),
             "request": {"method": q["method"], "url": q["url"], "httpVersion": "HTTP/1.1", "cookies": [], "queryString": [],
                         "headers": [{"name": k, "value": v} for k, v in q.get("headers", {}).items()], "headersSize": -1, "bodySize": -1},
             "response": {"status": s.get("status", 0), "statusText": s.get("statusText", ""), "httpVersion": "HTTP/1.1", "cookies": [],
                          "headers": [{"name": k, "value": v} for k, v in s.get("headers", {}).items()],
                          "content": {"size": len(r.get("body", "")), "mimeType": s.get("mimeType", ""), **({"text": r["body"]} if "body" in r else {})},
                          "redirectURL": "", "headersSize": -1, "bodySize": -1},
             "cache": {}, "timings": {"send": 0, "wait": 0, "receive": 0}}
        if q.get("postData"): e["request"]["postData"] = {"mimeType": q.get("headers", {}).get("Content-Type", ""), "text": q["postData"]}
        entries.append(e)
    for rid, w in wss.items():
        entries.append({"startedDateTime": iso(w["t"]), "time": 0, "_resourceType": "websocket", "_webSocketMessages": w["msgs"],
            "request": {"method": "GET", "url": w["url"], "httpVersion": "HTTP/1.1", "cookies": [], "queryString": [], "headers": [], "headersSize": -1, "bodySize": -1},
            "response": {"status": 101, "statusText": "Switching Protocols", "httpVersion": "HTTP/1.1", "cookies": [], "headers": [], "content": {"size": 0, "mimeType": ""}, "redirectURL": "", "headersSize": -1, "bodySize": -1},
            "cache": {}, "timings": {"send": 0, "wait": 0, "receive": 0}})
    json.dump({"log": {"version": "1.2", "creator": {"name": "ig-dm-api-recorder", "version": "1"}, "pages": [], "entries": entries}}, open(out, "w"))
    print(f"{len(entries)} entries, {len(wss)} websockets, {sum(len(w['msgs']) for w in wss.values())} ws frames")
asyncio.run(main())
