#!/usr/bin/env python3
"""Find how Duolingo's JavaScript controls the Rive avatar."""
import asyncio, json, websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/CFC155B356ADF58BA85035F269DEA082"

async def recv_response(ws, expected_id, timeout=10):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("id") == expected_id:
            return msg

async def check():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
        await recv_response(ws, 1)

        # Search for Rive-related code in the page's JavaScript
        # First, find all script sources
        e = """(function() {
            var scripts = document.querySelectorAll('script[src]');
            var sources = [];
            for (var i = 0; i < scripts.length; i++) {
                var src = scripts[i].src;
                // Only include rive-related or avatar-related scripts
                if (src.indexOf('rive') >= 0 || src.indexOf('avatar') >= 0 || src.indexOf('Rive') >= 0) {
                    sources.push(src);
                }
            }
            return JSON.stringify({riveScripts: sources, totalScripts: scripts.length}, null, 2);
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("Script sources:", resp.get("result",{}).get("result",{}).get("value","")[:3000])

        # Search for webpack modules that contain 'rive' or 'stateMachine'
        # Look at React fiber tree for the avatar canvas
        e2 = """(function() {
            try {
                // Find canvas elements that might have rive instances
                var canvases = document.querySelectorAll('canvas');
                var result = [];
                for (var i = 0; i < canvases.length; i++) {
                    var c = canvases[i];
                    // Check if there's a React fiber/internal instance
                    var fiberKey = Object.keys(c).find(function(k) {
                        return k.startsWith('__react') || k.startsWith('__reactFiber');
                    });
                    if (fiberKey) {
                        result.push({canvas: i, fiberKey: fiberKey});
                        // Trace up the fiber tree looking for Rive references
                        var fiber = c[fiberKey];
                        var depth = 0;
                        while (fiber && depth < 15) {
                            if (fiber.memoizedState || fiber.stateNode) {
                                // Check for rive-related state
                                try {
                                    var state = fiber.memoizedState;
                                    while (state) {
                                        var val = state.queue;
                                        depth++;
                                        state = state.next;
                                    }
                                } catch(e) {}
                            }
                            fiber = fiber.return;
                            depth++;
                        }
                    } else {
                        result.push({canvas: i, noFiber: true});
                    }
                }
                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nCanvas fiber:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
