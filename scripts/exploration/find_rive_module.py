#!/usr/bin/env python3
"""Find Rive runtime in webpack bundles and explore Rive file structure."""
import asyncio, json
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

async def main():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await send(ws, "Runtime.enable", {}, 1)
        await recv(ws, 1)

        # Find rive in webpack modules via React fiber + require
        script = """
        (async function() {
            // Strategy 1: Look through webpack chunks for rive
            const scripts = Array.from(document.querySelectorAll('script[src]'));
            const urls = scripts.map(s => s.src);

            // Find which chunk has 'rive' in it by fetching and searching
            let riveChunks = [];
            for (const url of urls) {
                if (url.includes('d35aaqx5ub95lt') && url.endsWith('.js')) {
                    try {
                        const resp = await fetch(url);
                        const text = await resp.text();
                        if (text.includes('rive') || text.includes('Rive') || text.includes('@rive-app')) {
                            riveChunks.push(url.split('/').pop());
                        }
                    } catch(e) {}
                }
            }

            // Strategy 2: Try to access webpack require
            let webpackInfo = {};
            try {
                if (window.webpackChunk) {
                    webpackInfo.hasWebpackChunk = true;
                }
                // Check if __webpack_require__ is available
                const keys = Object.keys(window).filter(k => k.includes('webpack'));
                webpackInfo.webpackKeys = keys;
            } catch(e) {}

            // Strategy 3: Look at loaded performance entries for rive-related files
            const perfEntries = performance.getEntriesByType('resource');
            const riveEntries = perfEntries.filter(e =>
                e.name.toLowerCase().includes('rive') ||
                e.name.toLowerCase().includes('.riv')
            );
            webpackInfo.riveResourceEntries = riveEntries.map(e => e.name);

            // Strategy 4: Check for React components related to avatar/character
            // and trace their imports
            const root = document.getElementById('root');
            if (root) {
                const fiberKey = Object.keys(root).find(k => k.startsWith('__reactFiber'));
                if (fiberKey) {
                    webpackInfo.hasReactFiber = true;
                }
            }

            return JSON.stringify({
                riveChunks: riveChunks,
                webpackInfo: webpackInfo,
            });
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script, "returnByValue": True, "awaitPromise": True}, 10)
        resp = await recv(ws, 10)
        r = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"=== Webpack/Rive search ===")
        print(r[:5000])

        # Try a different approach - use WebAssembly to load the Rive file
        # since the page already uses the Rive runtime internally
        script2 = """
        (async function() {
            // Try to find Rive through the avatar editor's React component tree
            const root = document.getElementById('root');
            if (!root) return 'no root element';

            const fiberKey = Object.keys(root).find(k => k.startsWith('__reactFiber'));
            if (!fiberKey) return 'no fiber key';

            // Walk the fiber tree to find components that use Rive
            let found = [];
            function walkFiber(fiber, depth) {
                if (!fiber || depth > 100) return;

                // Check for Rive-related props or state
                if (fiber.memoizedProps) {
                    const props = fiber.memoizedProps;
                    const propKeys = Object.keys(props);
                    const riveKeys = propKeys.filter(k =>
                        k.toLowerCase().includes('rive') || k.toLowerCase().includes('artboard')
                    );
                    if (riveKeys.length > 0) {
                        found.push({
                            depth: depth,
                            type: fiber.type?.name || fiber.type?.displayName || String(fiber.type).substring(0, 100),
                            riveKeys: riveKeys,
                        });
                    }
                }

                // Check memoizedState for Rive instances
                let state = fiber.memoizedState;
                while (state) {
                    if (state.queue?.lastRenderedState) {
                        const s = state.queue.lastRenderedState;
                        if (s && typeof s === 'object') {
                            const keys = Object.keys(s).filter(k => k.toLowerCase().includes('rive'));
                            if (keys.length > 0) {
                                found.push({
                                    depth: depth,
                                    stateKeys: keys,
                                    sampleState: JSON.stringify(s).substring(0, 200),
                                });
                            }
                        }
                    }
                    state = state.next;
                }

                walkFiber(fiber.child, depth + 1);
                walkFiber(fiber.sibling, depth);
            }

            walkFiber(root[fiberKey], 0);
            return JSON.stringify(found.slice(0, 20));
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script2, "returnByValue": True, "awaitPromise": True}, 11)
        resp = await recv(ws, 11)
        r2 = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"\n=== Rive in React tree ===")
        print(r2[:5000])

asyncio.run(main())
