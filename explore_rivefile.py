#!/usr/bin/env python3
"""Explore riveFile and enumerate artboards/state machines properly."""
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

        # Explore riveFile
        e1 = """(function() {
            var f = riveInst.riveFile || riveInst.file;
            if (!f) return 'no riveFile';
            return JSON.stringify({
                hasRiveFile: true,
                type: typeof f,
                ownKeys: Object.keys(f).slice(0, 20),
                protoKeys: Object.getOwnPropertyNames(Object.getPrototypeOf(f)).slice(0, 40),
            });
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e1,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("riveFile:", resp.get("result",{}).get("result",{}).get("value","")[:2000])

        # Use stateMachineInputs method
        e2 = """(function() {
            try {
                // stateMachineInputs needs a name; get names first
                var names = riveInst.stateMachineNames;
                var inputs1 = riveInst.stateMachineInputs('State Machine 1');
                return JSON.stringify({
                    smNames: names,
                    inputs1Type: typeof inputs1,
                    inputs1Length: inputs1 ? inputs1.length : -1,
                    inputs1: inputs1 ? inputs1.slice(0, 5).map(function(inp) {
                        return {name: inp.name, type: inp.type, value: inp.value};
                    }) : [],
                });
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nState machine inputs:", resp.get("result",{}).get("result",{}).get("value","")[:3000])

asyncio.run(check())
