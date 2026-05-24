#!/usr/bin/env python3
"""Explore the low-level file object's actual API."""
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

        e = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var runtime = riveInst.runtime;
                if (!file) return 'no file';

                // Check all properties
                var fileOwn = Object.keys(file).slice(0, 30);
                var fileProto = Object.getOwnPropertyNames(Object.getPrototypeOf(file)).slice(0, 40);

                // Try to find artboard-related methods
                var allMethods = fileProto.filter(function(k) { return typeof file[k] === 'function'; });

                var result = {
                    fileOwnKeys: fileOwn,
                    fileProtoMethods: allMethods,
                    runtimeOwnKeys: Object.keys(runtime).slice(0, 30),
                    runtimeProtoMethods: Object.getOwnPropertyNames(Object.getPrototypeOf(runtime))
                        .filter(function(k) { return typeof runtime[k] === 'function'; }).slice(0, 40),
                };

                // Try artboardCount directly on the file
                result.artboardCountDirect = typeof file.artboardCount;
                result.hasArtboardCount = 'artboardCount' in file;

                return JSON.stringify(result, null, 2);
            } catch(e) {
                return 'ERR: ' + e.message;
            }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print(resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
