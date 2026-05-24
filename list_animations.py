#!/usr/bin/env python3
"""List animations and explore state machine inputs via low-level API."""
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

        # List first 50 animation names
        e = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                var count = ab.animationCount();
                var anims = [];
                var limit = Math.min(count, 60);
                for (var i = 0; i < limit; i++) {
                    try {
                        var anim = ab.animationByIndex(i);
                        anims.push({index: i, name: anim.name});
                    } catch(e) {
                        anims.push({index: i, err: e.message});
                    }
                }
                return JSON.stringify({totalCount: count, animations: anims}, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("Animations:", resp.get("result",{}).get("result",{}).get("value","")[:8000])

        # Try to get state machine input count via different approach
        # Maybe inputs are on "instance" not the machine def
        e2 = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                var sm = ab.stateMachineByIndex(0);

                // Check all properties through the sm object directly
                // Maybe some methods require specific arguments
                var result = {};

                // Try to use sm as a constructor?
                result.smConstructor = sm.constructor.name;
                result.smConstructorProto = Object.getOwnPropertyNames(sm.constructor.prototype).slice(0, 30);

                // The sm.constructor might have input-related static methods
                var staticMethods = Object.getOwnPropertyNames(sm.constructor).slice(0, 20);
                result.smConstructorStatic = staticMethods;

                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nSM constructor:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

        # Also check: can we set riveInst.artboard to the low-level artboard object?
        e3 = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();

                // Store original
                var origArtboard = riveInst.artboard;
                result = {origArtboard: origArtboard, origType: typeof origArtboard};

                // Try setting to the low-level object
                try {
                    riveInst.artboard = ab;
                    result.setToObject = 'success';
                    // Now try stateMachineNames
                    try {
                        result.stateMachineNames = riveInst.stateMachineNames;
                    } catch(e) { result.smNamesErr = e.message; }
                    // Try stateMachineInputs
                    try {
                        var sms = riveInst.stateMachineNames;
                        if (sms && sms.length > 0) {
                            var inputs = riveInst.stateMachineInputs(sms[0]);
                            result.firstInputs = inputs ? inputs.length : 0;
                        }
                    } catch(e) { result.smInputsErr = e.message; }
                } catch(e) {
                    result.setToObjectErr = e.message;
                }

                // Restore
                riveInst.artboard = origArtboard;
                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":12,"method":"Runtime.evaluate","params":{"expression":e3,"returnByValue":True}}))
        resp = await recv_response(ws, 12)
        print("\nSet artboard to object:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
