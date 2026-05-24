#!/usr/bin/env python3
"""Explore state machine object API."""
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

        # Explore state machine object methods
        e = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                var sm = ab.stateMachineByIndex(0);

                var smProto = Object.getPrototypeOf(sm);
                var smMethods = Object.getOwnPropertyNames(smProto).filter(function(k) {
                    return typeof sm[k] === 'function';
                });
                var smOwnKeys = Object.keys(sm);

                return JSON.stringify({
                    smName: sm.name,
                    smOwnKeys: smOwnKeys,
                    smProtoMethods: smMethods,
                }, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("State Machine API:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
