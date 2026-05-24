#!/usr/bin/env python3
"""Find state machine names and get inputs properly."""
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

        # Get state machine names, animations, etc.
        e1 = """(function() {
            return JSON.stringify({
                smNames: riveInst.stateMachineNames,
                animNames: riveInst.animationNames,
                artboardName: riveInst.artboard,
                isPlaying: riveInst.isPlaying,
                isPaused: riveInst.isPaused,
                isStopped: riveInst.isStopped,
            });
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e1,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("Names:", resp.get("result",{}).get("result",{}).get("value",""))

        # Try stateMachineInputs with the actual name
        e2 = """(function() {
            try {
                var names = riveInst.stateMachineNames || [];
                var result = [];
                for (var i = 0; i < names.length; i++) {
                    try {
                        var inputs = riveInst.stateMachineInputs(names[i]);
                        result.push({
                            name: names[i],
                            inputCount: inputs ? inputs.length : 0,
                            sampleInputs: inputs ? inputs.slice(0, 3).map(function(inp) {
                                return {name: inp.name, type: inp.type, value: inp.value};
                            }) : [],
                        });
                    } catch(e) {
                        result.push({name: names[i], error: e.message});
                    }
                }
                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nState machines:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
