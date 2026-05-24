#!/usr/bin/env python3
"""Create StateMachineInstance via runtime and access inputs."""
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

        # Try to create StateMachineInstance via runtime
        e = """(function() {
            try {
                var runtime = riveInst.runtime;
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();

                // Check if runtime has StateMachineInstance
                var result = {};
                result.runtimeHasSMI = !!runtime.StateMachineInstance;
                result.runtimeType = typeof runtime;
                result.runtimeKeys = Object.keys(runtime).slice(0, 30);
                result.runtimeProtoKeys = Object.getOwnPropertyNames(Object.getPrototypeOf(runtime)).slice(0, 30);

                // Also check riveInst.riveFile for runtime
                if (riveInst.riveFile) {
                    result.riveFileKeys = Object.keys(riveInst.riveFile).slice(0, 20);
                    result.riveFileProtoKeys = Object.getOwnPropertyNames(Object.getPrototypeOf(riveInst.riveFile)).slice(0, 30);
                }

                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("Runtime SMI:", resp.get("result",{}).get("result",{}).get("value","")[:8000])

asyncio.run(check())
