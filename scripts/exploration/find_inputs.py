#!/usr/bin/env python3
"""Find inputs via low-level artboard and state machine objects."""
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

        # Get ALL property descriptors (including getters) from state machine
        e = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                var sm = ab.stateMachineByIndex(0);

                // Get all property descriptors from proto chain
                var proto = Object.getPrototypeOf(sm);
                var descriptors = {};
                while (proto && proto !== Object.prototype) {
                    var propNames = Object.getOwnPropertyNames(proto);
                    for (var i = 0; i < propNames.length; i++) {
                        var p = propNames[i];
                        if (p === 'constructor') continue;
                        var desc = Object.getOwnPropertyDescriptor(proto, p);
                        descriptors[p] = {
                            type: desc.get ? 'getter' : desc.value !== undefined ? 'value' : 'other',
                            hasGetter: !!desc.get,
                            hasSetter: !!desc.set,
                            hasValue: desc.value !== undefined,
                            configurable: desc.configurable,
                            enumerable: desc.enumerable,
                        };
                    }
                    proto = Object.getPrototypeOf(proto);
                }
                return JSON.stringify(descriptors, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("SM property descriptors:", resp.get("result",{}).get("result",{}).get("value","")[:8000])

        # Try artboard.inputByPath with the state machine name as first arg
        e2 = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();

                // inputByPath expects 2 args - what are they?
                // Try with "SMButtons" as path and various combos
                var tests = {};
                try { tests['SMButtons,empty'] = ab.inputByPath('SMButtons', ''); } catch(e) { tests['SMButtons,empty'] = e.message; }
                try { tests['SMAvatar,empty'] = ab.inputByPath('SMAvatar', ''); } catch(e) { tests['SMAvatar,empty'] = e.message; }
                try { tests['SMButtons,SMAvatar'] = ab.inputByPath('SMButtons', 'SMAvatar'); } catch(e) { tests['SMButtons,SMAvatar'] = e.message; }
                try { tests['empty,SMButtons'] = ab.inputByPath('', 'SMButtons'); } catch(e) { tests['empty,SMButtons'] = e.message; }

                // Also try textByPath
                try { tests['textByPath_empty'] = ab.textByPath(''); } catch(e) { tests['textByPath_empty'] = e.message; }

                return JSON.stringify(tests, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\ninputByPath tests:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

        # Try to enumerate the artboard's entire tree structure
        e3 = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();

                // Try to find any objects that have input-related properties
                // Enumerate all objects in the artboard
                var info = {
                    artboardName: ab.name,
                    animationCount: ab.animationCount(),
                    textValueRunCount: ab.textValueRunCount(),
                    eventCount: ab.eventCount(),
                };

                // Try textValueRun to find text elements
                var texts = [];
                for (var i = 0; i < info.textValueRunCount; i++) {
                    try {
                        texts.push({index: i});
                    } catch(e) { texts.push({index: i, err: e.message}); }
                }
                info.textValueRuns = texts;

                // Try events
                var events = [];
                for (var i = 0; i < info.eventCount; i++) {
                    try {
                        var ev = ab.eventByIndex(i);
                        events.push({index: i});
                    } catch(e) { events.push({index: i, err: e.message}); }
                }
                info.events = events;

                return JSON.stringify(info, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":12,"method":"Runtime.evaluate","params":{"expression":e3,"returnByValue":True}}))
        resp = await recv_response(ws, 12)
        print("\nArtboard info:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
