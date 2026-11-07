import asyncio, json, sys, urllib.request, websockets
async def main(tid, method, params):
    ws_url = [t for t in json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/list")) if t["id"] == tid][0]["webSocketDebuggerUrl"]
    async with websockets.connect(ws_url, max_size=None) as ws:
        await ws.send(json.dumps({"id": 1, "method": method, "params": params}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == 1: print(json.dumps(m.get("result", m))[:2000]); return
asyncio.run(main(sys.argv[1], sys.argv[2], json.loads(sys.argv[3] if len(sys.argv) > 3 else "{}")))
