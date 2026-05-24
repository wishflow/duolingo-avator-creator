#!/usr/bin/env python3
"""Explore the riveInst object structure after loading."""
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

        # Check all properties of riveInst
        e = """(function() {
            var keys = Object.keys(riveInst);
            var proto = Object.getOwnPropertyNames(Object.getPrototypeOf(riveInst));
            return JSON.stringify({
                ownKeys: keys,
                protoKeys: proto.slice(0, 50),
                hasArtboard: !!riveInst.artboard,
                artboardType: typeof riveInst.artboard,
                hasStateMachine: !!riveInst.stateMachine,
                hasStateMachineInputs: typeof riveInst.stateMachineInputs,
                loaded: riveInst.loaded,
            }, null, 2);
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("riveInst structure:")
        print(resp.get("result",{}).get("result",{}).get("value","")[:3000])

        # Check artboard details
        e2 = """(function() {
            try {
                var ab = riveInst.artboard;
                if (!ab) return 'no artboard';
                return JSON.stringify({
                    name: ab.name,
                    ownKeys: Object.keys(ab).slice(0, 20),
                    protoKeys: Object.getOwnPropertyNames(Object.getPrototypeOf(ab)).slice(0, 30),
                });
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nArtboard details:")
        print(resp.get("result",{}).get("result",{}).get("value","")[:2000])

        # Check how to get state machines
        e3 = """(function() {
            try {
                var sm = riveInst.stateMachine;
                var sms = riveInst.stateMachines;
                return JSON.stringify({
                    stateMachineType: typeof sm,
                    stateMachineName: sm && sm.name,
                    stateMachinesType: typeof sms,
                    stateMachinesLength: sms ? sms.length : -1,
                    layout: riveInst.layout ? typeof riveInst.layout : 'none',
                    source: typeof riveInst.source,
                });
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":12,"method":"Runtime.evaluate","params":{"expression":e3,"returnByValue":True}}))
        resp = await recv_response(ws, 12)
        print("\nState machine check:")
        print(resp.get("result",{}).get("result",{}).get("value","")[:2000])

asyncio.run(check())
