#!/usr/bin/env python3
"""Explore riveInst internals to find how state machines work."""
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

        # Look at riveInst internal properties
        e = """(function() {
            try {
                // Enumerate all keys and proto methods of riveInst
                var ownKeys = Object.keys(riveInst);
                var proto = Object.getPrototypeOf(riveInst);
                var protoKeys = Object.getOwnPropertyNames(proto);

                // Check specific state-machine related props
                var smProps = {};
                ['stateMachine', 'stateMachines', 'stateMachineNames', 'stateMachineInputs',
                 '_stateMachine', '_stateMachineInstances', '_artboard',
                 '__lowLevelArtboard', '__lowLevelStateMachine'].forEach(function(k) {
                    try {
                        smProps[k] = typeof riveInst[k];
                        if (typeof riveInst[k] === 'string') smProps[k] += ' = ' + JSON.stringify(riveInst[k]);
                        if (typeof riveInst[k] === 'object' && riveInst[k]) {
                            smProps[k] += ' keys: ' + JSON.stringify(Object.keys(riveInst[k]).slice(0,10));
                        }
                    } catch(e) { smProps[k] = 'ERR: ' + e.message; }
                });

                return JSON.stringify({
                    riveInstOwnKeys: ownKeys.slice(0, 30),
                    riveInstProtoKeys: protoKeys.slice(0, 40),
                    smProps: smProps,
                }, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("riveInst internals:", resp.get("result",{}).get("result",{}).get("value","")[:8000])

        # Try to access stateMachineInputs differently - maybe through the internal WASM
        e2 = """(function() {
            try {
                // Try to use riveInst.stateMachineInputs with different approaches
                var names = riveInst.stateMachineNames;
                if (!names || names.length === 0) {
                    // Manual enumeration via low-level
                    var file = riveInst.riveFile.file;
                    var ab = file.defaultArtboard();
                    var smCount = ab.stateMachineCount();
                    var manualNames = [];
                    for (var i = 0; i < smCount; i++) {
                        // Use try/catch because name getter may fail
                        try {
                            var sm = ab.stateMachineByIndex(i);
                            manualNames.push('sm_' + i);
                        } catch(e) {
                            manualNames.push('sm_' + i + '_err: ' + e.message);
                        }
                    }
                    names = manualNames;
                }
                return JSON.stringify({stateMachineNames: names, count: names.length}, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nSM names:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
