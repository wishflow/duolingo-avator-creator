#!/usr/bin/env python3
"""
Capture Duolingo avatar element renderings by using CDP to control the page.
Strategy: The avatar is rendered via Rive animation in a canvas element.
We can screenshot the canvas for each avatar configuration state.
But first, let's find where and how the avatar is rendered, and whether
individual elements can be captured.
"""
import asyncio, json, base64, os
from pathlib import Path
import websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/CFC155B356ADF58BA85035F269DEA082"
ASSETS_DIR = Path(__file__).parent / "assets"

async def send(ws, method, params=None, msg_id=1):
    cmd = {"id": msg_id, "method": method}
    if params:
        cmd["params"] = params
    await ws.send(json.dumps(cmd))

async def recv(ws, expected_id=None):
    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        if "id" in msg and (expected_id is None or msg["id"] == expected_id):
            return msg
        # Discard events

async def main():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await send(ws, "Runtime.enable", {}, 1)
        await recv(ws, 1)

        # Find the canvas element that renders the avatar
        # and understand the DOM structure
        script = """
        (function() {
            const info = {};

            // Find canvas elements
            const canvases = document.querySelectorAll('canvas');
            info.canvasCount = canvases.length;
            info.canvases = Array.from(canvases).map((c, i) => ({
                index: i,
                width: c.width,
                height: c.height,
                id: c.id,
                className: c.className,
                parentTag: c.parentElement?.tagName,
                parentClass: c.parentElement?.className,
            }));

            // Find elements with "avatar" in class/id
            const avatarElements = document.querySelectorAll('[class*="avatar"],[id*="avatar"],[class*="character"],[id*="character"],[class*="rive"],[id*="rive"]');
            info.avatarElements = Array.from(avatarElements).map(el => ({
                tag: el.tagName,
                id: el.id,
                className: el.className,
                text: el.textContent?.substring(0, 100),
            }));

            // Look for any data attributes with state info
            const allElements = document.querySelectorAll('[data-state],[data-testid]');
            info.dataElements = Array.from(allElements).slice(0, 30).map(el => ({
                tag: el.tagName,
                dataset: JSON.stringify(el.dataset),
                className: el.className?.substring(0, 80),
            }));

            return JSON.stringify(info);
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script, "returnByValue": True}, 10)
        resp = await recv(ws, 10)
        r = resp.get("result", {}).get("result", {}).get("value", "")
        print("=== DOM exploration ===")
        print(r[:8000])

        # Check if there are any image URLs being generated for avatar parts
        script2 = """
        (function() {
            // Check all background images in the page
            const all = document.querySelectorAll('*');
            const bgImages = [];
            all.forEach(el => {
                const bg = getComputedStyle(el).backgroundImage;
                if (bg && bg !== 'none' && bg.includes('url')) {
                    const match = bg.match(/url\\(["']?([^"')]+)["']?\\)/);
                    if (match && match[1].includes('avatar')) {
                        bgImages.push({
                            url: match[1],
                            className: el.className?.substring(0, 80),
                        });
                    }
                }
            });
            return JSON.stringify(bgImages);
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script2, "returnByValue": True}, 11)
        resp = await recv(ws, 11)
        r2 = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"\n=== Avatar background images ===")
        print(r2[:5000])

asyncio.run(main())
