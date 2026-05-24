#!/usr/bin/env python3
"""Test setting input values and rendering via low-level API."""
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

        # Create instance, set input values, and test rendering
        e = """(function() {
            try {
                var runtime = riveInst.runtime;
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                var SMInst = runtime.StateMachineInstance;

                var sm = ab.stateMachineByIndex(1); // SMAvatar
                var instance = new SMInst(sm, ab);
                var ic = instance.inputCount();

                // Check instance methods
                var proto = Object.getPrototypeOf(instance);
                var allProtoKeys = Object.getOwnPropertyNames(proto);
                var result = {
                    smName: sm.name,
                    inputCount: ic,
                    instanceProtoKeys: allProtoKeys.slice(0, 40),
                };

                // Try to get a specific input and modify its value
                var skinToneInp = instance.input(10); // SkinTone on SMAvatar
                result.skinToneInput = {
                    name: skinToneInp.name,
                    type: skinToneInp.type,
                    value: skinToneInp.value,
                };

                // Try setting value
                try {
                    skinToneInp.value = 5;
                    result.setValueTest = 'success, new value=' + skinToneInp.value;
                } catch(e) { result.setValueErr = e.message; }

                // Check if input has setValue or other methods
                var inpProto = Object.getPrototypeOf(skinToneInp);
                var inpProtoKeys = Object.getOwnPropertyNames(inpProto).slice(0, 20);
                result.inputProtoKeys = inpProtoKeys;

                // Check SMIInput type
                result.smiType = typeof skinToneInp;

                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("Input value set test:", resp.get("result",{}).get("result",{}).get("value","")[:8000])

        # Now try to advance the instance and artboard, then draw
        e2 = """(function() {
            try {
                var runtime = riveInst.runtime;
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                var SMInst = runtime.StateMachineInstance;

                var sm = ab.stateMachineByIndex(1); // SMAvatar
                var instance = new SMInst(sm, ab);

                // Set some values
                instance.input(10).value = 5;  // SkinTone
                instance.input(11).value = 4;  // Body
                instance.input(13).value = 30; // MainHair
                instance.input(15).value = 20; // Expression
                instance.input(26).value = 8;  // BackgroundColor

                // Try instance methods
                var result = {};

                // Check if instance has advance, advanceAndApply, apply
                var methodsToCheck = ['advance', 'advanceAndApply', 'apply', 'applyCubicInterpolation',
                    'needsAdvance', 'pointerDown', 'pointerMove', 'pointerUp',
                    'inputCount', 'input', 'stateMachine', 'artboard'];
                for (var i = 0; i < methodsToCheck.length; i++) {
                    var m = methodsToCheck[i];
                    result[m] = typeof instance[m];
                }

                // Try to advance the instance
                if (typeof instance.advance === 'function') {
                    try {
                        instance.advance(0.016); // ~60fps
                        result.advanceTest = 'success';
                    } catch(e) { result.advanceErr = e.message; }
                }

                // Try to advance and apply
                if (typeof instance.advanceAndApply === 'function') {
                    try {
                        instance.advanceAndApply(0.016);
                        result.advanceAndApplyTest = 'success';
                    } catch(e) { result.advanceAndApplyErr = e.message; }
                }

                // Advance artboard
                try {
                    ab.advance(0.016);
                    result.abAdvance = 'success';
                } catch(e) { result.abAdvanceErr = e.message; }

                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nInstance methods:", resp.get("result",{}).get("result",{}).get("value","")[:8000])

asyncio.run(check())
