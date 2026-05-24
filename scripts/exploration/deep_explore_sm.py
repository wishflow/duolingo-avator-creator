#!/usr/bin/env python3
"""Deep explore state machine - check all properties including non-enumerable."""
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

        # Deep explore: try everything on state machine
        e = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                var sm = ab.stateMachineByIndex(0);

                // Try to get ALL properties (including inherited)
                var result = { name: sm.name };

                // Check common property names
                var propsToCheck = ['inputCount', 'inputs', 'data', 'instance', 'ptr'];
                var found = {};
                for (var i = 0; i < propsToCheck.length; i++) {
                    var p = propsToCheck[i];
                    try {
                        var v = sm[p];
                        found[p] = typeof v + (typeof v === 'function' ? ' (fn)' : typeof v === 'number' ? ' = ' + v : '');
                    } catch(e) { found[p] = 'ERR: ' + e.message; }
                }
                result.propCheck = found;

                // Try calling inputCount without ()
                try { result.inputCountProp = sm.inputCount; } catch(e) { result.inputCountErr = e.message; }

                // Also check the high-level riveInst for internal state machine refs
                // riveInst might have internal low-level refs
                var hiKeys = Object.keys(riveInst).slice(0, 30);
                result.riveInstKeys = hiKeys;

                // Check if riveInst has access to low-level things
                result.hasFile = !!riveInst.riveFile;
                result.hasRuntime = !!riveInst.runtime;
                result.hasFileProp = !!riveInst.file;

                // Also enumerate all properties of sm's constructor prototype chain
                var proto = Object.getPrototypeOf(sm);
                var depth = 0;
                var chain = [];
                while (proto && depth < 5) {
                    var methods = Object.getOwnPropertyNames(proto).filter(function(k) {
                        return typeof proto[k] === 'function';
                    });
                    chain.push({depth: depth, methods: methods});
                    proto = Object.getPrototypeOf(proto);
                    depth++;
                }
                result.protoChain = chain;

                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("Deep SM explore:", resp.get("result",{}).get("result",{}).get("value","")[:8000])

        # Now try to understand how riveInst internally uses state machines
        # Maybe the inputs are obtained through a different path
        e2 = """(function() {
            try {
                // Check if the artboard's low-level object has input-related methods
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();

                // Look for any "input" related methods on artboard
                var abProto = Object.getPrototypeOf(ab);
                var abAll = Object.getOwnPropertyNames(abProto);
                var inputMethods = abAll.filter(function(k) {
                    return k.toLowerCase().indexOf('input') >= 0 ||
                           k.toLowerCase().indexOf('sm') >= 0 ||
                           k.toLowerCase().indexOf('state') >= 0 ||
                           k.toLowerCase().indexOf('machine') >= 0;
                });

                // Try calling inputByPath on the artboard
                var inputByPathResult = null;
                try { inputByPathResult = ab.inputByPath(''); } catch(e) { inputByPathResult = 'ERR: '+e.message; }

                return JSON.stringify({
                    inputMethods: inputMethods,
                    inputByPathEmpty: inputByPathResult,
                }, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nArtboard input methods:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
