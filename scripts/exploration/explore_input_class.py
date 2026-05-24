#!/usr/bin/env python3
"""Explore StateMachineInput class and RiveFile."""
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

        # Explore StateMachineInput
        e = """(function() {
            var SMI = window.rive.StateMachineInput;
            var proto = Object.getPrototypeOf(SMI.prototype || SMI);
            var keys = Object.getOwnPropertyNames(proto);
            var methods = keys.filter(function(k) { return typeof proto[k] === 'function'; });
            var props = keys.filter(function(k) { return typeof proto[k] !== 'function'; });

            var descs = {};
            keys.forEach(function(k) {
                try {
                    var d = Object.getOwnPropertyDescriptor(proto, k);
                    descs[k] = {type: (d.get || d.set) ? 'accessor' : typeof d.value};
                } catch(e) { descs[k] = 'ERR'; }
            });

            return JSON.stringify({
                SMI_typeof: typeof SMI,
                SMI_prototype_typeof: typeof SMI.prototype,
                protoKeys: keys,
                methods: methods,
                props: props,
                descriptors: descs,
                SMIType: window.rive.StateMachineInputType,
            }, null, 2);
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("StateMachineInput:", resp.get("result",{}).get("result",{}).get("value","")[:8000])

        # Try RiveFile to load the file
        e2 = """(function() {
            try {
                var RiveFile = window.rive.RiveFile;
                var proto = Object.getPrototypeOf(RiveFile.prototype || RiveFile);
                var keys = Object.getOwnPropertyNames(proto);
                var methods = keys.filter(function(k) { return typeof proto[k] === 'function'; });

                return JSON.stringify({
                    RiveFile_typeof: typeof RiveFile,
                    RiveFile_prototype_typeof: typeof RiveFile.prototype,
                    protoKeys: keys.slice(0, 30),
                    methods: methods.slice(0, 30),
                }, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nRiveFile:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

        # Try ViewModel-related classes
        e3 = """(function() {
            var VM = window.rive.ViewModel;
            var VMI = window.rive.ViewModelInstance;
            var proto = Object.getPrototypeOf(VM.prototype || VM);
            var instProto = Object.getPrototypeOf(VMI.prototype || VMI);
            return JSON.stringify({
                ViewModel_methods: Object.getOwnPropertyNames(proto).filter(function(k) { return typeof proto[k] === 'function'; }),
                ViewModelInstance_methods: Object.getOwnPropertyNames(instProto).filter(function(k) { return typeof instProto[k] === 'function'; }),
            }, null, 2);
        })()"""
        await ws.send(json.dumps({"id":12,"method":"Runtime.evaluate","params":{"expression":e3,"returnByValue":True}}))
        resp = await recv_response(ws, 12)
        print("\nViewModel classes:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
