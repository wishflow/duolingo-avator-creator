#!/usr/bin/env python3
"""Test path-based API for state machine control."""
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

        # Fix artboard and try path-based API
        e = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                riveInst.artboard = ab;

                var result = {};

                // Try retrieveInputAtPath with various path formats
                var testPaths = [
                    'SkinTone',
                    'SMButtons/SkinTone',
                    'SMAvatar/SkinTone',
                    'MainAvatar/SkinTone',
                    'MainAvatar/SMButtons/SkinTone',
                ];
                for (var i = 0; i < testPaths.length; i++) {
                    var p = testPaths[i];
                    try {
                        var inp = riveInst.retrieveInputAtPath(p);
                        result['retrieve_' + p] = inp ? ('type:' + inp.type + ' name:' + inp.name + ' value:' + inp.value) : null;
                    } catch(e) { result['retrieve_' + p] = 'ERR: ' + e.message; }
                }

                // Also try the low-level artboard.inputByPath with actual state machine name
                // inputByPath takes (stateMachineName, inputName)
                var sm = ab.stateMachineByIndex(0);
                var smName = sm.name;
                try {
                    var inp = ab.inputByPath(smName, 'SkinTone');
                    result['lowLevel_sm_inputByPath'] = inp ? ('found:' + typeof inp) : 'null';
                } catch(e) { result['lowLevel_sm_inputByPath'] = 'ERR: ' + e.message; }

                // Try with empty first arg
                try {
                    var inp = ab.inputByPath(smName, '');
                    result['lowLevel_sm_inputByPath_empty'] = inp ? ('found:' + typeof inp) : 'null';
                } catch(e) { result['lowLevel_sm_inputByPath_empty'] = 'ERR: ' + e.message; }

                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("Path API tests:", resp.get("result",{}).get("result",{}).get("value","")[:8000])

        # Also try setNumberStateAtPath
        e2 = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                riveInst.artboard = ab;

                var result = {};
                var testPaths = ['SkinTone', 'SMButtons/SkinTone', 'SMAvatar/SkinTone'];

                for (var i = 0; i < testPaths.length; i++) {
                    var p = testPaths[i];
                    try {
                        riveInst.setNumberStateAtPath(p, 0);
                        result['setNum_' + p] = 'success';
                    } catch(e) { result['setNum_' + p] = 'ERR: ' + e.message; }

                    try {
                        riveInst.setBooleanStateAtPath(p, true);
                        result['setBool_' + p] = 'success';
                    } catch(e) { result['setBool_' + p] = 'ERR: ' + e.message; }

                    try {
                        riveInst.fireStateAtPath(p);
                        result['fire_' + p] = 'success';
                    } catch(e) { result['fire_' + p] = 'ERR: ' + e.message; }
                }

                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nSet/Fire API tests:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
