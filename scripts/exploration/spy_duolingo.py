#!/usr/bin/env python3
"""Explore how Duolingo's own code controls the Rive avatar."""
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

        # Find rive-related variables in the global scope
        e = """(function() {
            var results = [];
            // Check common variable names
            var names = ['rive', 'Rive', 'riveInst', 'r', 'canvas', '_rive', '__rive',
                        'avatar', 'avatarState', 'avatarMachine', 'avatarSM',
                        'stateMachine', 'riveFile', 'riveCanvas'];
            for (var i = 0; i < names.length; i++) {
                try {
                    var v = window[names[i]];
                    if (v !== undefined) {
                        results.push(names[i] + ': ' + typeof v + (typeof v === 'object' ? ' keys=' + JSON.stringify(Object.keys(v || {}).slice(0,10)) : ''));
                    }
                } catch(e) {}
            }
            return JSON.stringify(results, null, 2);
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("Global rive vars:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

        # Search for rive instances in the page's JS heap
        e2 = """(function() {
            // Look for any canvas elements that might have rive instances
            var canvases = document.querySelectorAll('canvas');
            var info = [];
            for (var i = 0; i < canvases.length; i++) {
                var c = canvases[i];
                info.push({
                    id: c.id,
                    width: c.width,
                    height: c.height,
                    class: c.className,
                    parentId: c.parentElement ? c.parentElement.id : '',
                    dataAttrs: Object.keys(c.dataset || {}),
                });
            }
            return JSON.stringify({canvasCount: canvases.length, canvases: info}, null, 2);
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nCanvas elements:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
