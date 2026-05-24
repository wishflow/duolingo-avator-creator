#!/usr/bin/env python3
"""Get state machine inputs after fixing the artboard object."""
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

        # Fix artboard and get state machine inputs
        e = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();

                // Fix the artboard reference
                riveInst.artboard = ab;

                var smNames = riveInst.stateMachineNames;
                var result = {smNames: smNames, sms: []};

                for (var i = 0; i < smNames.length; i++) {
                    var name = smNames[i];
                    var smInfo = {name: name};
                    try {
                        var inputs = riveInst.stateMachineInputs(name);
                        smInfo.inputCount = inputs ? inputs.length : 0;
                        if (inputs && inputs.length > 0) {
                            smInfo.inputs = [];
                            for (var j = 0; j < inputs.length; j++) {
                                var inp = inputs[j];
                                smInfo.inputs.push({
                                    name: inp.name,
                                    type: inp.type,
                                    value: inp.value,
                                });
                            }
                        }
                    } catch(e) { smInfo.err = e.message; }
                    result.sms.push(smInfo);
                }

                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("State machine inputs:", resp.get("result",{}).get("result",{}).get("value","")[:8000])

        # Also try getting inputs directly from low-level artboard
        e2 = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();

                // Try to find all input-related things on the artboard
                // inputByPath seems to want 2 args
                // Let's try to get the actual state machine instance

                // Check what textByPath wants
                var result = {};
                try { result.textByPath_test = ab.textByPath('test', 'test2'); } catch(e) { result.textByPath_test = e.message; }

                // inputByPath with state machine name and empty
                for (var i = 0; i < 2; i++) {
                    var sm = ab.stateMachineByIndex(i);
                    var smName = sm.name;
                    result['sm_' + i + '_name'] = smName;

                    // Try inputByPath with (stateMachineName, '')
                    try {
                        var inp = ab.inputByPath(smName, '');
                        result['sm_' + i + '_inputByPath_name_'] = inp;
                    } catch(e) { result['sm_' + i + '_inputByPath_name_err'] = e.message; }

                    // Try with ('', stateMachineName)
                    try {
                        var inp = ab.inputByPath('', smName);
                        result['sm_' + i + '_inputByPath__name'] = inp;
                    } catch(e) { result['sm_' + i + '_inputByPath__name_err'] = e.message; }
                }

                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nLow-level inputByPath:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())
