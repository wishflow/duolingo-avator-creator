#!/usr/bin/env python3
"""Inspect the Rive API to understand how to use it."""
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

        # Test 1: Check Rive class details
        e1 = """(function() {
            var R = window.rive.Rive;
            return JSON.stringify({
                isFunction: typeof R === 'function',
                toString: String(R).substring(0, 300),
            });
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e1,"returnByValue":True}}))
        resp = await recv_response(ws,10)
        print("Test 1 (Rive type):", resp.get("result",{}).get("result",{}).get("value","")[:500])

        # Test 2: Try calling Rive with canvas
        e2 = """(function() {
            try {
                var canvas = document.getElementById('riveCanvas');
                var r = new window.rive.Rive({canvas: canvas});
                return 'OK: ' + Object.keys(r).slice(0,15).join(', ');
            } catch(e) {
                return 'ERR: ' + e.message;
            }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws,11)
        print("Test 2 (new Rive):", resp.get("result",{}).get("result",{}).get("value","")[:500])

        # Test 3: Try Rive.load static method
        e3 = """(function() {
            try {
                var hasStaticLoad = typeof window.rive.Rive.load === 'function';
                return 'static load: ' + hasStaticLoad;
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":12,"method":"Runtime.evaluate","params":{"expression":e3,"returnByValue":True}}))
        resp = await recv_response(ws,12)
        print("Test 3 (static load):", resp.get("result",{}).get("result",{}).get("value","")[:500])

        # Test 4: Try low-level approach with RuntimeLoader
        e4 = """(async function() {
            try {
                var rl = window.rive.RuntimeLoader;
                if (rl && typeof rl === 'function') {
                    var instance = new rl();
                    return 'RuntimeLoader OK: ' + Object.keys(instance).slice(0,10).join(', ');
                }
                return 'RuntimeLoader not a constructor';
            } catch(e) { return 'ERR: ' + e.message + ' stack:' + (e.stack||'').substring(0,200); }
        })()"""
        await ws.send(json.dumps({"id":13,"method":"Runtime.evaluate","params":{"expression":e4,"returnByValue":True,"awaitPromise":True}}))
        resp = await recv_response(ws,13)
        print("Test 4 (RuntimeLoader):", resp.get("result",{}).get("result",{}).get("value","")[:500])

asyncio.run(main())
