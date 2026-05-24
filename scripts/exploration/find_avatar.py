#!/usr/bin/env python3
"""Find avatar assets by monitoring network and exploring the page state."""
import asyncio, json, sys
import websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/CFC155B356ADF58BA85035F269DEA082"

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
        if "method" in msg:
            method = msg.get("method", "")
            p = msg.get("params", {})
            if method == "Network.responseReceived":
                url = p.get("response", {}).get("url", "")
                if "avatar" in url.lower() or "character" in url.lower():
                    print(f"  [NET] {url}")
            elif method == "Network.requestWillBeSent":
                url = p.get("request", {}).get("url", "")
                if any(k in url.lower() for k in ["svg", ".png", ".webp"]) and ("d35aaqx5ub95lt" in url):
                    print(f"  [REQ] {url}")
            elif method == "Runtime.consoleAPICalled":
                for arg in p.get("args", []):
                    val = arg.get("value", "")
                    if val and "AVATAR" in str(val):
                        print(f"  [CONSOLE] {val[:500]}")

async def main():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        # Enable Network and Runtime
        await send(ws, "Network.enable", {}, 1)
        await send(ws, "Runtime.enable", {}, 2)
        await recv(ws, 1)
        await recv(ws, 2)
        print("[*] Domains enabled")

        # Step 1: Find all avatar/character related URLs in performance API
        script1 = """
        (function() {
            const entries = performance.getEntriesByType('resource');
            const avatar = entries.filter(e =>
                e.name.toLowerCase().includes('avatar') ||
                e.name.toLowerCase().includes('character')
            );
            return JSON.stringify(avatar.map(e => e.name));
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script1, "returnByValue": True}, 10)
        resp = await recv(ws, 10)
        r = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"\n=== Avatar/Character resources ===")
        print(r[:3000])

        # Step 2: Look for the avatar configuration / manifest
        script2 = """
        (function() {
            const entries = performance.getEntriesByType('resource');
            const config = entries.filter(e =>
                e.name.includes('manifest') ||
                e.name.includes('config') ||
                e.name.includes('asset') ||
                e.name.includes('collection')
            );
            return JSON.stringify(config.map(e => ({url: e.name, type: e.initiatorType})));
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script2, "returnByValue": True}, 11)
        resp = await recv(ws, 11)
        r = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"\n=== Config/Manifest resources ===")
        print(r[:3000])

        # Step 3: Check all SVG/PNG resources loaded from Duolingo CDN
        script3 = """
        (function() {
            const entries = performance.getEntriesByType('resource');
            const images = entries.filter(e =>
                (e.name.endsWith('.svg') || e.name.endsWith('.png') || e.name.endsWith('.webp')) &&
                e.name.includes('d35aaqx5ub95lt')
            );
            return JSON.stringify(images.map(e => e.name));
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script3, "returnByValue": True}, 12)
        resp = await recv(ws, 12)
        r = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"\n=== SVG/PNG images from CDN ===")
        print(r[:5000])

        # Step 4: Try to find state with avatar data
        script4 = """
        (function() {
            const results = [];

            // Check Redux store
            if (window.__REDUX_DEVTOOLS_EXTENSION__) {
                results.push('Redux devtools found');
            }

            // Search for React internal state
            function searchReactTree(fiber, depth) {
                if (!fiber || depth > 50) return;
                if (fiber.memoizedState) {
                    let state = fiber.memoizedState;
                    while (state) {
                        if (state.queue && state.queue.lastRenderedState) {
                            const s = state.queue.lastRenderedState;
                            if (typeof s === 'object' && s) {
                                const keys = Object.keys(s);
                                if (keys.some(k => k.toLowerCase().includes('avatar') || k.toLowerCase().includes('character'))) {
                                    results.push(JSON.stringify(s).substring(0, 500));
                                }
                            }
                        }
                        state = state.next;
                    }
                }
                searchReactTree(fiber.child, depth + 1);
                searchReactTree(fiber.sibling, depth + 1);
            }

            const root = document.getElementById('root');
            if (root) {
                const fiberKey = Object.keys(root).find(k => k.startsWith('__reactFiber'));
                if (fiberKey) {
                    searchReactTree(root[fiberKey], 0);
                }
            }

            return JSON.stringify(results);
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script4, "returnByValue": True}, 13)
        resp = await recv(ws, 13)
        r = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"\n=== React state with avatar data ===")
        print(r[:3000])

asyncio.run(main())
