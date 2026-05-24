#!/usr/bin/env python3
"""Final attempt: fix rendering by calling proper init sequence."""
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

        # Reload fresh
        await ws.send(json.dumps({"id":2,"method":"Page.reload"}))
        await asyncio.sleep(6)

        # Access the Rive internals to fix the StateMachine.advance method
        e = """(function() {
            try {
                // Monkey-patch the StateMachine prototype to fix the advance bug
                var am = riveInst.animator;
                var sm0 = am.stateMachines[0];
                var proto = Object.getPrototypeOf(sm0);

                // Fix: override advance to use instance instead of stateMachine
                proto.advance = function(elapsedTime) {
                    if (this.instance && this.instance.advanceAndApply) {
                        return this.instance.advanceAndApply(elapsedTime);
                    }
                    return false;
                };

                // Now set values via the high-level API
                var inputs = riveInst.stateMachineInputs('SMAvatar');
                var result = {};
                if (inputs) {
                    for (var i = 0; i < inputs.length; i++) {
                        var inp = inputs[i];
                        if (inp.name === 'BackgroundColor') { inp.value = 22; result.bg = 22; }
                        if (inp.name === 'SkinTone') { inp.value = 10; result.st = 10; }
                        if (inp.name === 'Body') { inp.value = 4; result.body = 4; }
                        if (inp.name === 'MainHair') { inp.value = 30; result.hair = 30; }
                        if (inp.name === 'Expression') { inp.value = 20; result.expr = 20; }
                    }
                }

                // Also set via low-level for backup
                var inst1 = am.stateMachines[1].instance; // SMAvatar
                var inst0 = am.stateMachines[0].instance; // SMButtons
                inst1.input(10).value = 10; // SkinTone
                inst1.input(13).value = 30; // MainHair
                inst1.input(26).value = 22; // BackgroundColor
                inst1.advanceAndApply(1.0);
                inst0.input(7).value = 10; // SkinTone
                inst0.input(10).value = 30; // MainHair
                inst0.input(23).value = 22; // BackgroundColor
                inst0.advanceAndApply(1.0);
                am.artboard.advance(1.0);

                result.patched = true;
                result.animatorSMs = am.stateMachines.length;
                return JSON.stringify(result);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":3,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 3)
        print("Fix:", resp.get("result",{}).get("result",{}).get("value",""))

        await asyncio.sleep(3)

        # Check canvas
        e2 = """(function() {
            var canvas = document.getElementById('riveCanvas');
            var ctx = canvas.getContext('2d');
            var samples = [];
            for (var x = 0; x < 500; x += 50) {
                for (var y = 0; y < 500; y += 50) {
                    var p = ctx.getImageData(x, y, 1, 1);
                    if (p.data[3] > 0) {
                        samples.push(x+','+y+':'+Array.from(p.data).join(','));
                    }
                }
            }
            return JSON.stringify({changed: samples.length > 3, samples: samples.slice(0, 10)});
        })()"""
        await ws.send(json.dumps({"id":4,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 4)
        print("Canvas:", resp.get("result",{}).get("result",{}).get("value","")[:2000])

asyncio.run(check())
