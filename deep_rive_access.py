#!/usr/bin/env python3
"""
Access the Rive runtime through Duolingo's webpack module system.
The Rive file is already loaded by the page - we just need to find
the module that has the Rive instance and use it to enumerate/export.
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

async def recv(ws, expected_id=None, timeout=5.0):
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            msg = json.loads(raw)
            if "id" in msg and (expected_id is None or msg["id"] == expected_id):
                return msg
        except asyncio.TimeoutError:
            return None

async def main():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await send(ws, "Runtime.enable", {}, 1)
        await recv(ws, 1)

        # Strategy: Walk the webpack module cache to find Rive-related modules
        # Webpack stores all modules in __webpack_require__.c or similar
        script = """
        (function() {
            // Try to access webpack's module cache
            // In modern webpack, modules are stored in various places
            const results = {};

            // Find webpack public path and module cache
            if (window.webpackChunk) {
                // The chunk array is webpackChunk, and modules are stored
                // in a global that webpack creates
                results.webpackChunkType = typeof window.webpackChunk;
                results.webpackChunkArray = Array.isArray(window.webpackChunk);

                // Try to find the webpack require function
                // It's usually assigned to a variable like __webpack_require__
                const wpKeys = [];
                for (const key of Object.getOwnPropertyNames(window)) {
                    if (key.includes('webpack') || key.includes('__wp')) {
                        wpKeys.push(key);
                    }
                }
                results.webpackKeys = wpKeys;

                // The webpack runtime creates the require function
                // Let's try to find it in the chunk push handler
                if (window.webpackChunk.push !== Array.prototype.push) {
                    results.hasCustomPush = true;
                }
            }

            // Try another approach: find modules by their export patterns
            // Rive modules export things like 'Rive', 'StateMachine', 'Artboard', etc.
            results.webpackChunkSample = JSON.stringify(
                (window.webpackChunk || []).slice(0, 2)
            ).substring(0, 500);

            return JSON.stringify(results);
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script, "returnByValue": True}, 10)
        resp = await recv(ws, 10)
        r = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"Webpack exploration: {r[:3000]}")

        # Strategy 2: Search through all script tags for Rive-related code
        script2 = """
        (async function() {
            const scripts = Array.from(document.querySelectorAll('script[src]'));
            const jsScripts = scripts.filter(s => s.src.endsWith('.js') && s.src.includes('d35aaqx5ub95lt'));

            // Search each script for Rive-related keywords
            let found = [];
            for (const s of jsScripts.slice(0, 20)) {  // limit to 20
                try {
                    const resp = await fetch(s.src);
                    const text = await resp.text();
                    // Check for Rive-specific patterns
                    const hasRive = text.includes('@rive-app') ||
                                    text.includes('RiveCanvas') ||
                                    text.includes('StateMachineInstance') ||
                                    text.includes('rive.wasm');
                    const hasArtboard = text.includes('artboardByIndex') ||
                                       text.includes('stateMachineByIndex');
                    if (hasRive || hasArtboard) {
                        found.push({
                            file: s.src.split('/').pop(),
                            hasRive,
                            hasArtboard,
                            size: text.length,
                        });
                    }
                } catch(e) {}
            }
            return JSON.stringify(found);
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script2, "returnByValue": True, "awaitPromise": True}, 11)
        resp = await recv(ws, 11, timeout=60.0)
        r2 = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"\nRive script search: {r2[:3000]}")

asyncio.run(main())
