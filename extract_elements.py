#!/usr/bin/env python3
"""
Extract individual avatar element variations by controlling
the Duolingo avatar editor via CDP and capturing canvas screenshots.

Strategy:
1. Find the avatar canvas element
2. Use CDP Page.captureScreenshot or canvas.toDataURL to capture
3. Cycle through each state machine input value
4. Save each unique rendering
"""
import asyncio, json, base64, os
from pathlib import Path
import websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/CFC155B356ADF58BA85035F269DEA082"
ASSETS_DIR = Path(__file__).parent / "assets"
ELEMENTS_DIR = ASSETS_DIR / "elements"

async def send(ws, method, params=None, msg_id=1):
    cmd = {"id": msg_id, "method": method}
    if params:
        cmd["params"] = params
    await ws.send(json.dumps(cmd))

async def recv(ws, expected_id=None, timeout=None):
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout or 5.0)
            msg = json.loads(raw)
            if "id" in msg and (expected_id is None or msg["id"] == expected_id):
                return msg
        except asyncio.TimeoutError:
            return None

async def main():
    ELEMENTS_DIR.mkdir(parents=True, exist_ok=True)

    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await send(ws, "Runtime.enable", {}, 1)
        await send(ws, "Page.enable", {}, 2)
        await recv(ws, 1)
        await recv(ws, 2)
        print("[*] Connected to CDP")

        # Step 1: Find the avatar canvas and inject our Rive exploration code
        # The page already has the Rive file loaded. Let's tap into it.
        script = """
        (async function() {
            // Find the main avatar canvas (usually the large one)
            const canvases = document.querySelectorAll('canvas');
            let mainCanvas = null;
            for (const c of canvases) {
                if (c.width > 400 && c.height > 400) {
                    mainCanvas = c;
                    break;
                }
            }
            if (!mainCanvas) {
                return JSON.stringify({error: 'no large canvas found', canvasCount: canvases.length});
            }

            // Store reference for later
            window.__avatarCanvas = mainCanvas;

            return JSON.stringify({
                found: true,
                width: mainCanvas.width,
                height: mainCanvas.height,
                id: mainCanvas.id,
                className: mainCanvas.className,
            });
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script, "returnByValue": True, "awaitPromise": True}, 10)
        resp = await recv(ws, 10)
        r = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"Canvas info: {r}")

        # Step 2: Try to access the Rive file through the page's webpack modules
        # Look for Rive-related variables in the component tree
        script2 = """
        (function() {
            // Search ALL objects on window for anything Rive-related
            const results = [];

            // Check for React internal state
            const root = document.getElementById('root') || document.body;
            const allKeys = Object.keys(root);
            results.push({rootKeys: allKeys.filter(k => k.startsWith('__react'))});

            // Try to get the Rive instance via canvas webgl context
            const largeCanvas = window.__avatarCanvas;
            if (largeCanvas) {
                const ctx = largeCanvas.getContext('2d');
                results.push({canvasContext: ctx ? '2d' : 'none'});
            }

            // Look for DataTransfer or state in the DOM
            const dataElements = document.querySelectorAll('[class*="avatar"]');
            results.push({avatarClassElements: dataElements.length});

            return JSON.stringify(results);
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script2, "returnByValue": True}, 11)
        resp = await recv(ws, 11)
        print(f"Rive search: {resp.get('result', {}).get('result', {}).get('value', '')[:2000]}")

        # Step 3: Use the existing Duolingo app state to cycle through options
        # We can dispatch Redux actions to change the avatar state
        script3 = """
        (async function() {
            // Try to find the Redux store
            // Duolingo typically exposes it on window or through React context
            const result = {};

            // Check for __REDUX_DEVTOOLS_EXTENSION__
            if (window.__REDUX_DEVTOOLS_EXTENSION__) {
                result.hasReduxDevTools = true;
            }

            // Try common patterns for finding the store
            const possibleStores = [];
            for (const key of Object.keys(window)) {
                try {
                    const val = window[key];
                    if (val && typeof val === 'object' && (val.getState || val.dispatch)) {
                        possibleStores.push(key);
                    }
                } catch(e) {}
            }
            result.possibleStores = possibleStores;

            // Try looking for avatar state in common Redux selectors
            result.hasWebpackChunk = !!window.webpackChunk;

            return JSON.stringify(result);
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script3, "returnByValue": True}, 12)
        resp = await recv(ws, 12)
        print(f"Redux/store search: {resp.get('result', {}).get('result', {}).get('value', '')}")

        # Step 4: As a fallback, let's directly capture screenshots
        # of the avatar area by using Page.captureScreenshot with clip
        print("\n[*] Capturing avatar area screenshots...")
        for i in range(5):
            try:
                result = await send(ws, "Page.captureScreenshot", {
                    "format": "png",
                    "clip": {
                        "x": 0,
                        "y": 0,
                        "width": 500,
                        "height": 500,
                        "scale": 2
                    },
                    "captureBeyondViewport": True,
                }, msg_id=100 + i)
                resp = await recv(ws, 100 + i)
                if resp and "result" in resp:
                    data = resp["result"].get("data", "")
                    if data:
                        filepath = ELEMENTS_DIR / f"screenshot_{i}.png"
                        with open(filepath, "wb") as f:
                            f.write(base64.b64decode(data))
                        print(f"  Saved: {filepath}")
            except Exception as e:
                print(f"  Screenshot {i} failed: {e}")

        print("\n[DONE]")

asyncio.run(main())
