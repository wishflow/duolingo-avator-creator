#!/usr/bin/env python3
"""Inspect the structure of window.rive to understand the API."""
import asyncio, json, websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/F3E73A8FFF299A8B46D098136D059C6A"

async def recv_response(ws, expected_id, timeout=10):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("id") == expected_id:
            return msg

async def main():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
        await recv_response(ws, 1)

        # Inspect window.rive
        script = """
        (function() {
            var r = window.rive;
            if (!r) return 'window.rive is undefined';
            var info = {type: typeof r};
            // Get all keys (both own and prototype)
            info.ownKeys = Object.keys(r).slice(0, 30);
            info.allKeys = [];
            for (var k in r) {
                if (info.allKeys.length < 30) info.allKeys.push(k);
            }
            // Check constructor
            info.constructor = String(r.constructor).substring(0, 100);
            // Check for default export
            info.hasDefault = 'default' in r;
            info.defaultType = typeof r.default;
            // Check if any key is a function
            info.functionKeys = Object.keys(r).filter(function(k){return typeof r[k] === 'function'}).slice(0, 20);
            // Check symbol keys
            try {
                info.symbolKeys = Object.getOwnPropertySymbols(r).map(function(s){return s.toString()});
            } catch(e) {}
            return JSON.stringify(info, null, 2);
        })()
        """
        await ws.send(json.dumps({"id":2,"method":"Runtime.evaluate",
                                   "params":{"expression":script,"returnByValue":True}}))
        resp = await recv_response(ws, 2)
        print(resp.get("result",{}).get("result",{}).get("value",""))

asyncio.run(main())
