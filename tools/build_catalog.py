"""Build ops_catalog.json from captured HARs: operation -> {doc_id, variables template, seen_in}.

Templates keep the full variable shape (incl. __relay_internal__pv__ provider flags) as last observed.
Values that identify an account/session (device ids, user ids, cursors…) are kept here because this
catalog stays private; tools/sanitize_catalog.py strips them before publishing.
usage: build_catalog.py <out.json> <har>...
"""
import json
import re
import sys
import urllib.parse

out, hars = sys.argv[1], sys.argv[2:]
try:
    cat = json.load(open(out))
except (OSError, ValueError):
    cat = {}


def put(name, doc_id, variables, src, kind):
    e = cat.setdefault(name, {"doc_id": doc_id, "variables": {}, "seen_in": [], "kind": kind})
    if doc_id:
        e["doc_id"] = doc_id
    if isinstance(variables, dict):
        e["variables"] = variables
    if src not in e["seen_in"]:
        e["seen_in"].append(src)


for fn in hars:
    src = fn.rsplit("/", 1)[-1].replace(".har", "")
    for e in json.load(open(fn))["log"]["entries"]:
        u = e["request"]["url"]
        if "/graphql" in u:
            f = urllib.parse.parse_qs(e["request"].get("postData", {}).get("text", ""))
            n = (f.get("fb_api_req_friendly_name") or [None])[0]
            if not n:
                continue
            try:
                v = json.loads((f.get("variables") or ["{}"])[0])
            except ValueError:
                v = None
            put(n, (f.get("doc_id") or [""])[0], v, src, "mutation" if "Mutation" in n else "query")
        elif e["_resourceType"] == "document":
            h = e["response"]["content"].get("text") or ""
            for m in re.finditer(r'"expectedPreloaders":', h):
                try:
                    arr, _ = json.JSONDecoder().raw_decode(h[m.end():])
                except ValueError:
                    continue
                for p in arr if isinstance(arr, list) else []:
                    if isinstance(p, dict) and p.get("queryName") and p.get("queryID"):
                        put(p["queryName"], p["queryID"], p.get("variables"), src + "(html)", "query")

json.dump(cat, open(out, "w"), indent=1, sort_keys=True)
print(f"{len(cat)} operations in catalog")
