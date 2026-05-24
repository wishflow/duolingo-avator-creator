#!/usr/bin/env python3
"""Use the low-level Rive API to enumerate artboards and state machines."""
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

        # Access the low-level file through riveInst.riveFile.file
        e1 = """(function() {
            try {
                var file = riveInst.riveFile.file;
                if (!file) return 'no file on riveFile';
                var info = {
                    artboardCount: file.artboardCount(),
                    smCount: file.stateMachineCount(),
                    animCount: file.animationCount(),
                };
                var artboards = [];
                for (var i = 0; i < info.artboardCount; i++) {
                    var ab = file.artboardByIndex(i);
                    artboards.push({index: i, name: ab.name});
                }
                info.artboards = artboards;

                var sms = [];
                for (var i = 0; i < info.smCount; i++) {
                    var sm = file.stateMachineByIndex(i);
                    var inputs = [];
                    for (var j = 0; j < sm.inputCount(); j++) {
                        var inp = sm.inputByIndex(j);
                        inputs.push({name: inp.name, type: inp.type});
                    }
                    sms.push({index: i, name: sm.name, inputCount: sm.inputCount(), inputs: inputs.slice(0, 5)});
                }
                info.stateMachines = sms;

                return JSON.stringify(info, null, 2);
            } catch(e) {
                return 'ERR: ' + e.message;
            }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e1,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("Low-level file info:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
