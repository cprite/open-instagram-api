"""List GraphQL ops (friendly name, doc_id, vars keys, response top path) and REST /api/v1 calls in HAR files."""
import json, sys, urllib.parse, collections
NOISE = {"PolarisViewerSettingsQuery","QuickPromotionSupportIGSchemaBatchFetchQuery","PolarisAPIGetFrCookieQuery",
         "IGDBadgeCountOffMsysQuery","useIGDSystemFolderUnreadThreadCountQuery","PolarisAutomaticPreviewsDisabledContextProviderQuery",
         "IGPresenceUnifiedSetupQuery","useFeatureLimitsOffMsysQuery","PolarisStoriesV3TrayContainerQuery"}
for fn in sys.argv[1:]:
    print("#####", fn.rsplit("/", 1)[-1])
    seen = collections.OrderedDict()
    for e in json.load(open(fn))["log"]["entries"]:
        u = e["request"]["url"]; m = e["request"]["method"]
        if e["_resourceType"] not in ("xhr", "fetch"): continue
        body = e["response"]["content"].get("text", "") or ""
        if "/graphql" in u:
            f = urllib.parse.parse_qs(e["request"].get("postData", {}).get("text", ""))
            n = (f.get("fb_api_req_friendly_name") or ["?"])[0]
            if n in NOISE: continue
            try: v = list(json.loads((f.get("variables") or ["{}"])[0]).keys())
            except Exception: v = []
            try:
                d = json.loads(body.split("\n")[0]).get("data") or {}; top = list(d.keys())[:3]
            except Exception: top = ["?"]
            seen.setdefault(("GQL", n), (f.get("doc_id") or [""])[0], )
            seen[("GQL", n)] = f"doc={(f.get('doc_id') or [''])[0]} vars={[k for k in v if not k.startswith('__relay')][:8]} -> {top}"
        elif "/api/v1/" in u and "fxcal" not in u and "/web/logging" not in u:
            path = urllib.parse.urlparse(u).path
            seen.setdefault(("REST", f"{m} {path}"), f"{e['response']['status']} {len(body)}B")
    for (k, n), v in seen.items(): print(f"  {k:4} {n:60} {v}")
