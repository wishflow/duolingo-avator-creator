#!/usr/bin/env python3
"""Access artboards and their state machines properly."""
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

        # Access artboard and explore its API
        e = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                if (!ab) return 'no default artboard';

                var abProto = Object.getOwnPropertyNames(Object.getPrototypeOf(ab));
                var abMethods = abProto.filter(function(k) { return typeof ab[k] === 'function'; });

                var smCount = -1;
                try { smCount = ab.stateMachineCount(); } catch(e) {}

                return JSON.stringify({
                    abName: ab.name,
                    abOwnKeys: Object.keys(ab).slice(0, 20),
                    abProtoMethods: abMethods.slice(0, 40),
                    smCount: smCount,
                }, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("Artboard API:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

        # Now enumerate state machines from artboard
        e2 = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                var smCount = ab.stateMachineCount();
                var sms = [];
                for (var i = 0; i < smCount; i++) {
                    var sm = ab.stateMachineByIndex(i);
                    var inputs = [];
                    for (var j = 0; j < sm.inputCount(); j++) {
                        var inp = sm.inputByIndex(j);
                        inputs.push({name: inp.name, type: inp.type});
                    }
                    sms.push({index: i, name: sm.name, inputCount: sm.inputCount(), inputs: inputs});
                }
                return JSON.stringify(sms, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nState machines:", resp.get("result",{}).get("result",{}).get("value","")[:8000])

asyncio.run(check())
