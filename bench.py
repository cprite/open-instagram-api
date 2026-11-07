"""Send-latency benchmark.  usage: python3 bench.py <thread_fbid> [n]"""
import json, statistics, sys, time, requests
from igdm.client import IGDirect
TID, N = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 3
TOKEN = open("api_token").read().strip()
ig = IGDirect()
t = time.perf_counter(); ig.bootstrap(force=True); cold = time.perf_counter() - t
rows = []
orig_post = ig.s.post
def timed_post(*a, **kw):
    t0 = time.perf_counter(); r = orig_post(*a, **kw); timed_post.rtt = time.perf_counter() - t0
    try:
        body = r.text[9:] if r.text.startswith("for (;;);") else r.text
        sm = json.loads(body)["extensions"]["server_metadata"]; timed_post.srv = (sm["time_at_flush_ms"] - sm["request_start_time_ms"]) / 1000
    except Exception: timed_post.srv = None
    return r
ig.s.post = timed_post
for i in range(1, N + 1):
    if i > 1: time.sleep(3)
    # 1) through the HTTP API (what a caller sees)
    t0 = time.perf_counter()
    r = requests.post(f"http://127.0.0.1:8765/threads/{TID}/messages", headers={"Authorization": f"Bearer {TOKEN}"},
                      json={"text": f"⏱ latency test {i}/{N}"}, timeout=60)
    api_rtt = time.perf_counter() - t0
    mid, sent_ts = r.json()["message_id"], r.json()["timestamp_ms"]
    # 2) poll IG until the message is readable back from the thread
    t1 = time.perf_counter(); polls = 0
    while True:
        polls += 1
        th = ig.thread_raw(TID)
        if any(e["node"]["message_id"] == mid for e in th["slide_messages"]["edges"]): break
        if time.perf_counter() - t1 > 20: break
    visible = time.perf_counter() - t0
    rows.append({"i": i, "api_rtt_s": round(api_rtt, 3), "readback_s": round(visible, 3), "polls": polls})
    print(rows[-1], flush=True)
# 3) raw GraphQL send timing w/o the FastAPI hop (one more message)
time.sleep(3)
ig.send_text(TID, f"⏱ latency test {N+1}/{N+1} (direct client)")
print({"direct_gql_rtt_s": round(timed_post.rtt, 3), "ig_server_processing_s": timed_post.srv})
print({"cold_bootstrap_s": round(cold, 3),
       "api_rtt_median_s": round(statistics.median(r["api_rtt_s"] for r in rows), 3),
       "readback_median_s": round(statistics.median(r["readback_s"] for r in rows), 3)})
