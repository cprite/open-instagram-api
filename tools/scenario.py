"""Run one UI scenario in the capture browser while recording a HAR.

usage: scenario.py <name> <out.har> [arg]
Recorder (record_har.py, action "none") runs in parallel on the same CDP target.
"""
import asyncio
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
NAME, OUT = sys.argv[1], sys.argv[2]
ARG = sys.argv[3] if len(sys.argv) > 3 else ""
IG = "https://www.instagram.com"


async def dismiss(pg):
    for label in ("Not Now", "Not now", "Allow all cookies", "Decline optional cookies"):
        b = pg.get_by_role("button", name=label)
        if await b.count():
            try:
                await b.first.click(timeout=1500)
            except Exception:
                pass


async def scroll(pg, n=4):
    for _ in range(n):
        await pg.mouse.wheel(0, 2500)
        await asyncio.sleep(1.5)


async def post(pg):          # media info + comments + likers + replies
    await pg.goto(f"{IG}/p/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(6); await dismiss(pg)
    likes = pg.locator('a[href$="/liked_by/"], a[href*="liked_by"]')
    if await likes.count():
        await likes.first.click(); await asyncio.sleep(4); await scroll(pg, 2)
        await pg.keyboard.press("Escape"); await asyncio.sleep(1)
    rep = pg.get_by_text("View replies", exact=False)
    if await rep.count():
        await rep.first.click(); await asyncio.sleep(3)
    await scroll(pg, 2)


async def comments(pg):     # comment paging + replies on a post page
    import re as _re
    await pg.goto(f"{IG}/p/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(7); await dismiss(pg)
    for _ in range(6):           # scroll the comments column (the scrollable ancestor of the first comment)
        await pg.evaluate("""() => { const els=[...document.querySelectorAll('ul, div')].filter(e => e.scrollHeight > e.clientHeight + 50 && getComputedStyle(e).overflowY.match(/auto|scroll/));
                                     els.forEach(e => e.scrollTop = e.scrollHeight); }""")
        await asyncio.sleep(2)
        more = pg.locator('svg[aria-label="Load more comments"]')
        if await more.count():
            try: await more.first.click(timeout=1500)
            except Exception: pass
    rep = pg.get_by_text(_re.compile(r"View (all )?\d* ?repl", _re.I))
    if await rep.count():
        await rep.first.click(); await asyncio.sleep(4)


async def reel(pg):
    await pg.goto(f"{IG}/reel/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(8); await dismiss(pg)
    await scroll(pg, 2)


async def profile_scroll(pg):  # pagination of posts / reels tab
    await pg.goto(f"{IG}/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(6); await dismiss(pg)
    await scroll(pg, 5)
    await pg.goto(f"{IG}/{ARG}/reels/", wait_until="domcontentloaded"); await asyncio.sleep(5)
    await scroll(pg, 4)


async def story(pg):          # open first story in home tray, step through a few frames
    await pg.goto(f"{IG}/", wait_until="domcontentloaded"); await asyncio.sleep(6); await dismiss(pg)
    ring = pg.locator('[aria-label*="Story by"], [role="menuitem"] canvas, a[href^="/stories/"]')
    if await ring.count():
        await ring.first.click(); await asyncio.sleep(4)
        for _ in range(4):
            await pg.keyboard.press("ArrowRight"); await asyncio.sleep(2)


async def highlight(pg):
    await pg.goto(f"{IG}/stories/highlights/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(6); await dismiss(pg)
    v = pg.get_by_role("button", name="View story")
    if await v.count():
        await v.first.click(); await asyncio.sleep(4)
    for _ in range(3):
        await pg.keyboard.press("ArrowRight"); await asyncio.sleep(2)


async def search(pg):
    await pg.goto(f"{IG}/", wait_until="domcontentloaded"); await asyncio.sleep(6); await dismiss(pg)
    await pg.locator('svg[aria-label="Search"]').first.click(); await asyncio.sleep(3)
    box = pg.locator('input[aria-label="Search input"], input[placeholder="Search"], input[type="text"]')
    print("search inputs:", await box.count())
    await box.first.click(); await box.first.type(ARG or "london", delay=150); await asyncio.sleep(6)
    await box.first.fill(""); await box.first.type("instagram", delay=150); await asyncio.sleep(5)


async def location(pg):
    await pg.goto(f"{IG}/explore/locations/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(6); await dismiss(pg)
    await scroll(pg, 4)


async def explore(pg):
    await pg.goto(f"{IG}/explore/", wait_until="domcontentloaded"); await asyncio.sleep(6); await dismiss(pg)
    await scroll(pg, 4)


async def notifications(pg):
    await pg.goto(f"{IG}/", wait_until="domcontentloaded"); await asyncio.sleep(6); await dismiss(pg)
    n = pg.locator('svg[aria-label="Notifications"]')
    if await n.count():
        await n.first.click(); await asyncio.sleep(5)


async def main():
    import os
    tid = os.environ.get("IGDM_TARGET_ID") or [t for t in json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/list")) if t["type"] == "page"][0]["id"]
    rec = subprocess.Popen([sys.executable, str(HERE / "record_har.py"), tid, "45", OUT, "none"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    await asyncio.sleep(2)
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp("http://127.0.0.1:9333")
        pg = [x for x in b.contexts[0].pages if "instagram.com" in x.url][0]
        try:
            await asyncio.wait_for(globals()[NAME](pg), timeout=40)
        except Exception as e:
            print("scenario error:", type(e).__name__, str(e)[:160])
    print(rec.communicate()[0].strip().splitlines()[-1])


asyncio.run(main())
