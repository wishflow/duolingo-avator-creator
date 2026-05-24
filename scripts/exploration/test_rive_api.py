#!/usr/bin/env python3
"""Test the proper Rive API for loading a file."""
import asyncio, json, websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/16650AEAB28ECB206070EDDB717BD9D8"

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

        # Test loading from URL
        e1 = """(async function() {
            try {
                var canvas = document.getElementById('riveCanvas');
                var r = new window.rive.Rive({
                    canvas: canvas,
                    src: 'avatar_builder_25_sept2025.riv',
                    autoplay: false,
                });
                return 'OK: src loading started';
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e1,"returnByValue":True,"awaitPromise":True}}))
        resp = await recv_response(ws,10)
        print("Test src loading:", resp.get("result",{}).get("result",{}).get("value","")[:500])

        # Check Rive instance structure after loading (wait a bit)
        await asyncio.sleep(5)
        e2 = """(function() {
            // Check if any Rive instance exists on window
            var keys = Object.keys(window).filter(function(k) {
                try { return window[k] && typeof window[k] === 'object' && window[k].riveRuntime; } catch(e) {}
            });
            return JSON.stringify({riveInstanceKeys: keys});
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws,11)
        print("Rive instances:", resp.get("result",{}).get("result",{}).get("value","")[:500])

asyncio.run(main())
