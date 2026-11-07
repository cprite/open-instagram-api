"""Launch an isolated headless Chromium (own profile, CDP on 127.0.0.1:9333) logged into IG via exported cookies."""
import asyncio, json, os, signal
from playwright.async_api import async_playwright
HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SS = {"no_restriction": "None", "lax": "Lax", "strict": "Strict"}
async def main():
    ck = json.load(open(f"{HOME}/cookies.json"))
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            f"{HOME}/tools/.profile", executable_path="/usr/bin/chromium", headless=True,
            args=["--remote-debugging-port=9333", "--remote-debugging-address=127.0.0.1"],
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36")
        await ctx.add_cookies([{k: v for k, v in {
            "name": c["name"], "value": c["value"], "domain": c["domain"], "path": c["path"],
            "secure": c["secure"], "httpOnly": c["httpOnly"], "expires": c.get("expirationDate", -1),
            "sameSite": SS.get(c["sameSite"])}.items() if v is not None} for c in ck])
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://www.instagram.com/direct/inbox/", wait_until="domcontentloaded")
        print("READY", page.url, flush=True)
        stop = asyncio.Event()
        for s in (signal.SIGINT, signal.SIGTERM): asyncio.get_running_loop().add_signal_handler(s, stop.set)
        await stop.wait()
asyncio.run(main())
