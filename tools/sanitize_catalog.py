"""Strip account/session identifiers from ops_catalog.json for publishing.

Keeps: doc_id, variable keys, booleans, null, small ints (counts/page sizes), short lower_snake enums
("ranked", "web_top_search", "ALL_MEDIA_AUTO_COLLECTION"), and lists of such enums.
Blanks: ids, cursors, uuids, usernames, shortcodes, queries, timestamps, large ints -> "" / None.
usage: sanitize_catalog.py <in.json> <out.json>
"""
import json
import re
import sys

ENUM = re.compile(r"^([a-z_]{1,48}|[A-Z_]{1,48})$")


def clean(v, key=""):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v if v < 1000 else None
    if isinstance(v, float):
        return None
    if isinstance(v, str):
        if key in ("query", "username", "text", "tag_name", "shortcode"):
            return ""
        return v if ENUM.match(v) and not re.search(r"\d", v) else ""
    if isinstance(v, list):
        out = [clean(x, key) for x in v]
        return [x for x in out if x not in ("", None)]
    if isinstance(v, dict):
        return {k: clean(x, k) for k, x in v.items()}
    return None


src, dst = sys.argv[1], sys.argv[2]
cat = json.load(open(src))
pub = {name: {"doc_id": e.get("doc_id"), "kind": e.get("kind"), "variables": clean(e.get("variables") or {})}
       for name, e in sorted(cat.items())}
json.dump(pub, open(dst, "w"), indent=1, sort_keys=True)
print(f"{len(pub)} operations written to {dst}")
