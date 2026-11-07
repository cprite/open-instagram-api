"""Run one UI scenario in the capture browser while recording a HAR.

usage: scenario.py <name> <out.har> [arg]
Recorder (record_har.py, action "none") runs in parallel on the same CDP target.
"""
import asyncio
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
NAME, OUT = sys.argv[1], sys.argv[2]
ARG = sys.argv[3] if len(sys.argv) > 3 else ""
IG = "https://www.instagram.com"
_os = os
ME = _os.environ.get("IGDM_ME", "")          # your username (for DM scenarios)
PEER = _os.environ.get("IGDM_PEER", "")      # the other person in the DM thread
MEDIA = _os.environ.get("IGDM_MEDIA", ".")   # folder with test1.jpg / test2.jpg


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


async def click_svg(pg, label, nth=0, timeout=4000):
    """Click the button that wraps an icon with this aria-label."""
    el = pg.locator(f'svg[aria-label="{label}"]').nth(nth).locator("xpath=ancestor::*[@role='button' or self::button or self::a][1]")
    await el.click(timeout=timeout); await asyncio.sleep(2.5)


async def like_save(pg):    # like -> unlike, save -> unsave on a post
    await pg.goto(f"{IG}/p/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(7); await dismiss(pg)
    for a, b in (("Like", "Unlike"), ("Save", "Remove")):
        try:
            await click_svg(pg, a); await click_svg(pg, b)
            print("did", a, "->", b)
        except Exception as e:
            print("fail", a, type(e).__name__)


async def like(pg):         # post like/unlike (24px icon) + comment like/unlike (12px icon)
    await pg.goto(f"{IG}/p/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(7); await dismiss(pg)
    for size, tag in (("24", "post"), ("12", "comment")):
        for label in ("Like", "Unlike"):
            el = pg.locator(f'svg[aria-label="{label}"][height="{size}"]').first.locator("xpath=ancestor::*[@role='button' or self::button][1]")
            try:
                await el.click(timeout=4000); await asyncio.sleep(3); print(tag, label, "ok")
            except Exception as e:
                print(tag, label, "fail", type(e).__name__)


async def menu_action(pg, item, confirm=None):
    await pg.locator('svg[aria-label="Options"]').first.locator("xpath=ancestor::*[@role='button' or self::button][1]").click(timeout=5000)
    await asyncio.sleep(2)
    btn = pg.locator("[role=dialog]").get_by_text(item, exact=True)
    if not await btn.count():
        btn = pg.get_by_role("button", name=item, exact=True)
    await btn.first.click(timeout=5000); await asyncio.sleep(2.5)
    if confirm:
        await pg.get_by_role("button", name=confirm, exact=True).last.click(timeout=5000); await asyncio.sleep(3)
    await dismiss(pg)
    for close in ("Dismiss", "Close", "OK"):
        b = pg.get_by_role("button", name=close, exact=True)
        if await b.count():
            try: await b.first.click(timeout=1500)
            except Exception: pass
    await asyncio.sleep(1.5)


async def block(pg):        # block -> unblock, restrict -> unrestrict a public account
    await pg.goto(f"{IG}/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(7); await dismiss(pg)
    for item, conf in (("Block", "Block"), ("Unblock", "Unblock"), ("Restrict", None), ("Unrestrict", None)):
        try:
            await menu_action(pg, item, conf); print(item, "ok")
            if item in ("Block", "Unblock"):
                await pg.reload(wait_until="domcontentloaded"); await asyncio.sleep(5)
        except Exception as e:
            print(item, "fail", type(e).__name__, str(e)[:100])


async def restrict(pg):
    await pg.goto(f"{IG}/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(7); await dismiss(pg)
    for item, conf in (("Restrict", "Restrict Account"), ("Unrestrict", None)):
        try:
            await menu_action(pg, item, conf); print(item, "ok")
            await pg.reload(wait_until="domcontentloaded"); await asyncio.sleep(5)
        except Exception as e:
            print(item, "fail", type(e).__name__, str(e)[:100])


async def unrestrict(pg):
    await pg.goto(f"{IG}/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(7); await dismiss(pg)
    try:
        await menu_action(pg, "Unrestrict"); print("Unrestrict ok")
    except Exception as e:
        print("Unrestrict fail", type(e).__name__, str(e)[:100])


async def publish(pg):      # create a post: ARG = comma-separated files; caption = "API test post"
    files = ARG.split(",")
    await pg.goto(f"{IG}/", wait_until="domcontentloaded"); await asyncio.sleep(6); await dismiss(pg)
    await click_svg(pg, "New post")
    p_item = pg.get_by_role("link", name="Post")
    if await p_item.count():
        await p_item.first.click(); await asyncio.sleep(2)
    else:
        b = pg.get_by_text("Post", exact=True)
        if await b.count():
            await b.first.click(); await asyncio.sleep(2)
    await pg.locator('input[type="file"]').first.set_input_files(files); await asyncio.sleep(5)
    ok = pg.locator("[role=dialog]").get_by_role("button", name="OK")     # "Video posts are now shared as reels"
    if await ok.count():
        await ok.first.click(); await asyncio.sleep(2)
    for _ in range(2):
        await pg.locator("[role=dialog]").get_by_role("button", name="Next").first.click(timeout=8000); await asyncio.sleep(3)
    box = pg.locator('[role=dialog] [aria-label="Write a caption..."], [role=dialog] div[contenteditable="true"]')
    await box.first.click(); await box.first.type("API test post (open-instagram-api), will be deleted", delay=30)
    await pg.locator("[role=dialog]").get_by_role("button", name="Share").first.click(timeout=8000)
    for _ in range(20):
        await asyncio.sleep(2)
        if await pg.get_by_text("Your post has been shared", exact=False).count() or await pg.get_by_text("Post shared", exact=False).count():
            print("shared"); break
    else:
        print("no shared confirmation")


async def post_manage(pg):  # on own post ARG: comment -> like comment -> delete comment -> edit caption -> delete post
    async def step(name, coro):
        try:
            await coro; print(name, "ok")
        except Exception as e:
            print(name, "fail", type(e).__name__, str(e)[:90])
    await pg.goto(f"{IG}/p/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(7); await dismiss(pg)
    async def comment():
        box = pg.locator('textarea[aria-label="Add a comment…"], textarea[placeholder="Add a comment…"]')
        await box.first.click(); await box.first.type("API test comment", delay=40)
        await pg.get_by_role("button", name="Post", exact=True).first.click(); await asyncio.sleep(5)
    await step("comment", comment())
    async def like_comment():
        await pg.locator('svg[aria-label="Like"][height="12"], svg[aria-label="Like"][height="16"]').first.locator(
            "xpath=ancestor::*[@role='button' or self::button][1]").click(timeout=5000); await asyncio.sleep(4)
    await step("like_comment", like_comment())
    async def delete_comment():
        c = pg.get_by_text("API test comment", exact=True).first
        await c.hover(); await asyncio.sleep(1)
        await pg.locator('svg[aria-label="Comment options"]').first.locator("xpath=ancestor::*[@role='button' or self::button][1]").click(timeout=5000)
        await asyncio.sleep(2); await pg.locator("[role=dialog]").get_by_text("Delete", exact=True).first.click(timeout=5000); await asyncio.sleep(4)
    await step("delete_comment", delete_comment())
    async def edit():
        await click_svg(pg, "More Options")
        await pg.locator("[role=dialog]").get_by_text("Edit", exact=True).first.click(timeout=5000); await asyncio.sleep(3)
        box = pg.locator('[role=dialog] div[contenteditable="true"]').first
        await box.click(); await pg.keyboard.press("End"); await box.type(" (edited)", delay=40)
        await pg.locator("[role=dialog]").get_by_role("button", name="Done").first.click(timeout=5000); await asyncio.sleep(5)
    await step("edit_caption", edit())
    async def delete():
        await pg.reload(wait_until="domcontentloaded"); await asyncio.sleep(6)
        await click_svg(pg, "More Options")
        await pg.locator("[role=dialog]").get_by_text("Delete", exact=True).first.click(timeout=5000); await asyncio.sleep(2)
        await pg.locator("[role=dialog]").get_by_text("Delete", exact=True).last.click(timeout=5000); await asyncio.sleep(5)
    await step("delete_post", delete())


async def edit_delete(pg):  # own post ARG: edit caption, then delete the post
    global ARG
    await pg.goto(f"{IG}/p/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(7); await dismiss(pg)
    try:
        await click_svg(pg, "More Options")
        await pg.locator("[role=dialog]").get_by_text("Edit", exact=True).first.click(timeout=5000); await asyncio.sleep(3)
        box = pg.locator('[role=dialog] div[contenteditable="true"]').first
        await box.click(); await pg.keyboard.press("End"); await box.type(" (edited)", delay=40)
        await pg.locator("[role=dialog]").get_by_role("button", name="Done").first.click(timeout=5000); await asyncio.sleep(5)
        print("edit ok")
    except Exception as e:
        print("edit fail", type(e).__name__, str(e)[:90])
    try:
        await pg.reload(wait_until="domcontentloaded"); await asyncio.sleep(6)
        await click_svg(pg, "More Options")
        await pg.locator("[role=dialog]").get_by_text("Delete", exact=True).first.click(timeout=5000); await asyncio.sleep(2)
        await pg.locator("[role=dialog]").get_by_text("Delete", exact=True).last.click(timeout=5000); await asyncio.sleep(5)
        print("delete ok")
    except Exception as e:
        print("delete fail", type(e).__name__, str(e)[:90])


async def delete_only(pg):  # cleanup: delete own post ARG via the post's More Options menu
    await pg.goto(f"{IG}/p/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(7); await dismiss(pg)
    try:
        await click_svg(pg, "More Options")
        await pg.locator("[role=dialog]").get_by_text("Delete", exact=True).first.click(timeout=5000); await asyncio.sleep(2)
        await pg.locator("[role=dialog]").get_by_text("Delete", exact=True).last.click(timeout=5000); await asyncio.sleep(5)
        print("deleted", ARG)
    except Exception as e:
        print("delete fail", ARG, type(e).__name__, str(e)[:90])


async def dm_actions(pg):   # ARG = thread_fbid. text->edit->unsend, react->unreact, photo, mute->unmute
    me = ME
    async def step(name, coro):
        try:
            await coro; print(name, "ok")
        except Exception as e:
            print(name, "fail", type(e).__name__, str(e)[:100])
        await asyncio.sleep(6)
    async def btn(label, nth=-1):
        loc = pg.locator(f'svg[aria-label="{label}"]')
        el = (loc.last if nth == -1 else loc.nth(nth)).locator("xpath=ancestor::*[@role='button' or self::button or self::a][1]")
        await el.click(timeout=6000); await asyncio.sleep(2)
    await pg.goto(f"{IG}/direct/t/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(8); await dismiss(pg)
    box = pg.locator('div[role="textbox"][contenteditable="true"]').first
    async def send_edit_unsend():
        await box.click(); await box.type("API test message (will be edited, then unsent)", delay=25); await pg.keyboard.press("Enter")
        await asyncio.sleep(5)
        await pg.get_by_text("API test message (will be edited, then unsent)", exact=True).last.hover(); await asyncio.sleep(1)
        await btn(f"See more options for message from {me}")
        await pg.get_by_text("Edit", exact=True).last.click(timeout=5000); await asyncio.sleep(2)
        await pg.keyboard.press("End"); await pg.keyboard.type(" [edited]", delay=30); await pg.keyboard.press("Enter"); await asyncio.sleep(5)
        print("  edited")
        await pg.get_by_text("[edited]", exact=False).last.hover(); await asyncio.sleep(1)
        await btn(f"See more options for message from {me}")
        await pg.get_by_text("Unsend", exact=True).last.click(timeout=5000); await asyncio.sleep(2)
        u = pg.get_by_role("button", name="Unsend")
        if await u.count(): await u.last.click(timeout=5000)
        await asyncio.sleep(4)
    await step("send+edit+unsend", send_edit_unsend())
    async def react():
        rows = pg.locator(f'svg[aria-label="React to message from {PEER}"]')
        await rows.last.locator("xpath=ancestor::*[@role='button' or self::button][1]").click(timeout=6000, force=True); await asyncio.sleep(2)
        emo = pg.locator('[role="dialog"] [role="button"], [role="menu"] [role="button"]').filter(has_text="❤")
        if not await emo.count():
            emo = pg.get_by_text("❤️", exact=True)
        await emo.first.click(timeout=5000); await asyncio.sleep(5); print("  reacted")
        r = pg.get_by_text("❤️", exact=True).last          # click own reaction -> remove
        await r.click(timeout=5000); await asyncio.sleep(2)
        rm = pg.get_by_text("Tap to remove", exact=False)
        if not await rm.count(): rm = pg.get_by_text("Remove", exact=False)
        await rm.first.click(timeout=5000); await asyncio.sleep(4)
    await step("react+unreact", react())
    async def photo():
        await pg.locator('input[type="file"]').first.set_input_files(f"{MEDIA}/test2.jpg"); await asyncio.sleep(4)
        send = pg.get_by_role("button", name="Send")
        if await send.count(): await send.last.click(timeout=5000)
        else: await pg.keyboard.press("Enter")
        await asyncio.sleep(8)
    await step("send photo", photo())
    async def mute():
        await btn("Conversation information"); await asyncio.sleep(2)
        for _ in range(2):
            t = pg.get_by_text("Mute messages", exact=False).first
            await t.click(timeout=5000); await asyncio.sleep(3)
            ok = pg.get_by_role("button", name="Mute")       # possible duration dialog
            if await ok.count(): await ok.last.click(); await asyncio.sleep(3)
    await step("mute+unmute", mute())


async def dm_unsend_react(pg):   # ARG = thread_fbid
    await pg.goto(f"{IG}/direct/t/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(8); await dismiss(pg)
    try:
        await pg.get_by_text("API test message (will be edited, then unsent)", exact=True).last.hover(); await asyncio.sleep(1.5)
        await pg.locator(f'svg[aria-label="See more options for message from {ME}"]:visible').first.click(); await asyncio.sleep(2)
        await pg.locator("[role=dialog], [role=menu]").get_by_text("Unsend", exact=True).first.click(timeout=5000); await asyncio.sleep(2)
        c = pg.get_by_role("button", name="Unsend")
        if await c.count(): await c.last.click(timeout=5000)
        await asyncio.sleep(6); print("unsend ok")
    except Exception as e:
        print("unsend fail", type(e).__name__, str(e)[:100])
    await asyncio.sleep(8)
    try:
        msgs = pg.locator('div[role="row"], div[data-scope="messages_table"] > div')
        await pg.locator(f'svg[aria-label="React to message from {PEER}"]').last.locator("xpath=ancestor::*[2]").hover(); await asyncio.sleep(1)
        await pg.locator(f'svg[aria-label="React to message from {PEER}"]:visible').first.click(timeout=5000, force=True); await asyncio.sleep(2.5)
        picks = pg.locator('[role=dialog] [role=button], [role=dialog] button, [role=menu] [role=button]')
        print("picker buttons:", await picks.count())
        await picks.first.click(timeout=5000); await asyncio.sleep(6); print("react ok")
    except Exception as e:
        print("react fail", type(e).__name__, str(e)[:100])


async def dm_react_share(pg):   # ARG = thread_fbid
    await pg.goto(f"{IG}/direct/t/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(8); await dismiss(pg)
    try:
        await pg.locator(f'svg[aria-label="React to message from {PEER}"]').last.locator("xpath=ancestor::*[4]").hover(); await asyncio.sleep(1.5)
        await pg.locator(f'svg[aria-label="React to message from {PEER}"]:visible').first.click(timeout=5000); await asyncio.sleep(3)
        heart = pg.get_by_text("❤", exact=False)
        print("heart candidates:", await heart.count())
        await heart.last.click(timeout=5000); await asyncio.sleep(6); print("react ok")
    except Exception as e:
        print("react fail", type(e).__name__, str(e)[:100])
    try:
        await pg.goto(f"{IG}/p/{_os.environ.get('IGDM_SHARE_CODE', '')}/", wait_until="domcontentloaded"); await asyncio.sleep(7); await dismiss(pg)
        await click_svg(pg, "Share")
        box = pg.locator('[role=dialog] input[placeholder="Search"], [role=dialog] input[name="queryBox"], [role=dialog] input')
        await box.first.type(PEER, delay=80); await asyncio.sleep(4)
        await pg.locator("[role=dialog]").get_by_text(PEER, exact=True).first.click(timeout=5000); await asyncio.sleep(2)
        await pg.locator("[role=dialog]").get_by_role("button", name="Send").first.click(timeout=5000); await asyncio.sleep(6)
        print("share ok")
    except Exception as e:
        print("share fail", type(e).__name__, str(e)[:100])


async def dm_history(pg):   # ARG = thread_fbid: scroll the message list up to load older messages
    await pg.goto(f"{IG}/direct/t/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(8); await dismiss(pg)
    await pg.mouse.move(870, 450)
    for _ in range(12):
        await pg.mouse.wheel(0, -2500); await asyncio.sleep(2.5)
    print("scrolled")


async def settings(pg):    # bio edit -> revert; private -> public
    await pg.goto(f"{IG}/accounts/edit/", wait_until="domcontentloaded"); await asyncio.sleep(7); await dismiss(pg)
    try:
        bio = pg.locator('textarea#pepBio, textarea[name="biography"], textarea').first
        orig = await bio.input_value()
        for val in (orig + " [API test]", orig):
            await bio.fill(val); await asyncio.sleep(1)
            await pg.get_by_role("button", name="Submit").first.click(timeout=5000); await asyncio.sleep(5)
        print("bio edit+revert ok (orig len", len(orig), ")")
    except Exception as e:
        print("bio fail", type(e).__name__, str(e)[:100])
    try:
        await pg.goto(f"{IG}/accounts/privacy_setting/", wait_until="domcontentloaded"); await asyncio.sleep(7)
        for _ in range(2):
            await pg.get_by_role("checkbox").first.click(timeout=5000, force=True); await asyncio.sleep(2.5)
            for lbl in ("Switch to private", "Switch to public"):
                b = pg.get_by_role("button", name=lbl)
                if await b.count():
                    await b.first.click(timeout=5000); break
            await asyncio.sleep(5)
        print("privacy toggle x2 ok")
    except Exception as e:
        print("privacy fail", type(e).__name__, str(e)[:100])


async def privacy(pg):     # private -> public on /accounts/settings/v2/account_privacy/
    await pg.goto(f"{IG}/accounts/settings/v2/account_privacy/", wait_until="domcontentloaded"); await asyncio.sleep(8)
    for i in range(2):
        try:
            await pg.get_by_role("switch", name="Private account").first.click(timeout=6000); await asyncio.sleep(3)
            for lbl in ("Switch to private", "Switch to public", "Switch to Private", "Switch to Public"):
                b = pg.get_by_role("button", name=lbl)
                if await b.count():
                    await b.first.click(timeout=5000); break
            await asyncio.sleep(6); print("toggle", i + 1, "ok")
        except Exception as e:
            print("toggle", i + 1, "fail", type(e).__name__, str(e)[:100])


async def follow(pg):       # follow -> unfollow a public account
    await pg.goto(f"{IG}/{ARG}/", wait_until="domcontentloaded"); await asyncio.sleep(7); await dismiss(pg)
    try:
        await pg.get_by_role("button", name="Follow", exact=True).first.click(); await asyncio.sleep(4); print("followed")
        await pg.get_by_role("button", name="Following").first.click(); await asyncio.sleep(2)
        await pg.get_by_role("button", name="Unfollow").first.click(); await asyncio.sleep(4); print("unfollowed")
    except Exception as e:
        print("follow fail", type(e).__name__, str(e)[:120])


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
    rec = subprocess.Popen([sys.executable, str(HERE / "record_har.py"), tid, os.environ.get("REC_SECONDS", "45"), OUT, "none"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    await asyncio.sleep(2)
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp("http://127.0.0.1:9333")
        pg = [x for x in b.contexts[0].pages if "instagram.com" in x.url][0]
        try:
            await asyncio.wait_for(globals()[NAME](pg), timeout=int(os.environ.get('SCENARIO_TIMEOUT', 40)))
        except Exception as e:
            print("scenario error:", type(e).__name__, str(e)[:160])
    print(rec.communicate()[0].strip().splitlines()[-1])


asyncio.run(main())
