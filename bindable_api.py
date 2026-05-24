#!/usr/bin/env python3
"""Try bindable artboard and other API paths."""
import asyncio, json, websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/CB4837F1B122A360413A05FDD9AAB40B"

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

        # Try bindable artboard
        e = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var bab = file.bindableArtboardDefault();

                if (!bab) return 'no bindable artboard';

                // Get bindable artboard API
                var proto = Object.getPrototypeOf(bab);
                var methods = Object.getOwnPropertyNames(proto).filter(function(k) {
                    return typeof bab[k] === 'function';
                });

                return JSON.stringify({
                    babOwnKeys: Object.keys(bab).slice(0, 20),
                    babProtoMethods: methods.slice(0, 50),
                }, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("Bindable artboard:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

        # Try internalBindableArtboardFromArtboard
        e2 = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                var ibab = file.internalBindableArtboardFromArtboard(ab);

                if (!ibab) return 'no internal bindable artboard';

                var proto = Object.getPrototypeOf(ibab);
                var methods = Object.getOwnPropertyNames(proto).filter(function(k) {
                    return typeof ibab[k] === 'function';
                });

                return JSON.stringify({
                    ibabOwnKeys: Object.keys(ibab).slice(0, 20),
                    ibabProtoMethods: methods.slice(0, 50),
                }, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nInternal bindable artboard:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

        # Check window.rive exports
        e3 = """(function() {
            var rive = window.rive;
            var exports = {};
            for (var k in rive) {
                if (rive.hasOwnProperty(k)) {
                    exports[k] = typeof rive[k];
                }
            }
            return JSON.stringify(exports, null, 2);
        })()"""
        await ws.send(json.dumps({"id":12,"method":"Runtime.evaluate","params":{"expression":e3,"returnByValue":True}}))
        resp = await recv_response(ws, 12)
        print("\nwindow.rive exports:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
