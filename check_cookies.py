"""Check an exported cookie file without printing any values.
usage: python3 check_cookies.py <file>   -> account it logs in as, or what's wrong"""
import json, os, shutil, sys, tempfile
p = sys.argv[1]
try:
    ck = json.load(open(p))
except Exception as e:
    sys.exit(f"not a JSON cookie export: {type(e).__name__}")
vals = {c.get("name"): c.get("value") or "" for c in ck if isinstance(c, dict)}
for n in ("sessionid", "csrftoken", "ds_user_id"):
    if not vals.get(n):
        sys.exit(f"missing or EMPTY cookie: {n} (export while logged in, include HttpOnly cookies)")
d = tempfile.mkdtemp(); shutil.copy(p, os.path.join(d, "cookies.json")); os.chmod(os.path.join(d, "cookies.json"), 0o600)
os.environ["IGDM_HOME"] = d
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from igdm.instagram import Instagram
ig = Instagram()
r = ig.s.get("https://www.instagram.com/api/v1/accounts/edit/web_form_data/",
             headers={"X-IG-App-ID": "936619743392459", "X-Requested-With": "XMLHttpRequest"}, timeout=30, allow_redirects=False)
shutil.rmtree(d)
if r.ok and "json" in r.headers.get("content-type", ""):
    print("OK, logs in as @" + r.json()["form_data"]["username"])
else:
    sys.exit(f"session not valid on Instagram (HTTP {r.status_code}) — re-export while logged in")
