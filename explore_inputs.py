#!/usr/bin/env python3
"""Explore input paths and state machine control APIs."""
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

        # Get state machine names via low-level API, being careful with getters
        e = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                var smCount = ab.stateMachineCount();
                var sms = [];
                for (var i = 0; i < smCount; i++) {
                    var info = { index: i };
                    try {
                        var sm = ab.stateMachineByIndex(i);
                        // Try different ways to get name
                        try { info.name = sm.name; } catch(e) { info.nameErr = e.message; }
                        // Try inputCount property (not function)
                        try { info.inputCountProp = sm.inputCount; } catch(e) { info.inputCountPropErr = e.message; }
                        // Try inputCount as function
                        try { info.inputCountFn = sm.inputCount(); } catch(e) { info.inputCountFnErr = e.message; }
                    } catch(e) {
                        info.smErr = e.message;
                    }
                    sms.push(info);
                }
                return JSON.stringify({smCount: smCount, sms: sms}, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("State machines via low-level:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

        # Now try the path-based API on riveInst
        e2 = """(function() {
            try {
                // Try retrieveInputAtPath with various paths
                var paths = ['', 'MainAvatar', 'MainAvatar/', 'SMButtons', 'State Machine 1'];
                var pathResults = {};
                paths.forEach(function(p) {
                    try {
                        pathResults[p] = JSON.stringify(riveInst.retrieveInputAtPath(p));
                    } catch(e) { pathResults[p] = 'ERR: ' + e.message; }
                });
                return JSON.stringify(pathResults, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nretrieveInputAtPath:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

        # Try source property
        e3 = """(function() {
            try {
                var src = riveInst.source;
                return typeof src + ' = ' + JSON.stringify(src);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":12,"method":"Runtime.evaluate","params":{"expression":e3,"returnByValue":True}}))
        resp = await recv_response(ws, 12)
        print("\nsource:", resp.get("result",{}).get("result",{}).get("value","")[:2000])

        # Try activeArtboard
        e4 = """(function() {
            try {
                var aa = riveInst.activeArtboard;
                return typeof aa + (aa ? ' name=' + aa.name : '');
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":13,"method":"Runtime.evaluate","params":{"expression":e4,"returnByValue":True}}))
        resp = await recv_response(ws, 13)
        print("\nactiveArtboard:", resp.get("result",{}).get("result",{}).get("value","")[:2000])

asyncio.run(check())
