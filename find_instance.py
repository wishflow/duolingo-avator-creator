#!/usr/bin/env python3
"""Find how to create/access StateMachineInstance."""
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

        # Check if stateMachineByIndex returns a definition or instance
        # Also try all methods on the state machine including those not on prototype
        e = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                var sm = ab.stateMachineByIndex(0);

                // Try all common input-related method names directly
                var tests = {};
                var methodNames = [
                    'inputCount', 'input', 'inputs',
                    'getBool', 'getNumber', 'getTrigger',
                    'inputByIndex', 'inputByName',
                    'instanceInputCount', 'numInputs',
                    'inputSize', 'size',
                    'advance', 'advanceAndApply',
                    'pointerDown', 'pointerMove', 'pointerUp',
                    'pointers', 'setInput', 'setBool', 'setNumber', 'fireTrigger',
                    'findInput', 'getInput', 'getInputValue', 'setInputValue',
                ];
                for (var i = 0; i < methodNames.length; i++) {
                    var m = methodNames[i];
                    try {
                        var val = sm[m];
                        tests[m] = typeof val;
                    } catch(e) { tests[m] = 'ERR: ' + e.message; }
                }

                return JSON.stringify({
                    smName: sm.name,
                    tests: tests,
                }, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("SM method tests:", resp.get("result",{}).get("result",{}).get("value","")[:8000])

        # Check if artboard has createInstance/instance-related methods
        e2 = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();

                // Try all possible instance-related methods on artboard
                var tests = {};
                var methodNames = [
                    'createStateMachineInstance', 'stateMachineInstance',
                    'instanceAtStateMachine', 'stateMachineInstanceByIndex',
                    'stateMachineInstanceByName', 'makeInstance',
                    'newInstance', 'createInstance',
                    'createStateMachine', 'instantiateStateMachine',
                    'stateMachineAt',
                ];
                for (var i = 0; i < methodNames.length; i++) {
                    var m = methodNames[i];
                    try {
                        var val = ab[m];
                        tests[m] = typeof val;
                    } catch(e) { tests[m] = 'ERR: ' + e.message; }
                }

                return JSON.stringify(tests, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":11,"method":"Runtime.evaluate","params":{"expression":e2,"returnByValue":True}}))
        resp = await recv_response(ws, 11)
        print("\nArtboard instance methods:", resp.get("result",{}).get("result",{}).get("value","")[:5000])

        # Also check the state machine constructor - can we new it?
        e3 = """(function() {
            try {
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                var sm = ab.stateMachineByIndex(0);

                // Check constructor
                var ctor = sm.constructor;
                var result = {
                    ctorName: ctor.name,
                    ctorLength: ctor.length,
                };

                // Try to create a new instance using the constructor
                try {
                    var instance = new ctor(ab, sm);
                    result.newInstance = 'success';
                    result.instanceName = instance.name;
                    // Check methods on instance
                    result.instanceMethods = {};
                    var testMethods = ['inputCount', 'input', 'getBool', 'getNumber', 'getTrigger', 'advance'];
                    for (var i = 0; i < testMethods.length; i++) {
                        var m = testMethods[i];
                        try {
                            result.instanceMethods[m] = typeof instance[m];
                        } catch(e) { result.instanceMethods[m] = 'ERR: ' + e.message; }
                    }
                } catch(e) { result.newInstanceErr = e.message; }

                // Also try with just the artboard
                try {
                    var instance2 = new ctor(ab);
                    result.newInstanceAbOnly = 'success';
                    result.instance2Methods = {};
                    var testMethods = ['inputCount', 'input', 'getBool', 'getNumber', 'getTrigger', 'advance'];
                    for (var i = 0; i < testMethods.length; i++) {
                        var m = testMethods[i];
                        try {
                            result.instance2Methods[m] = typeof instance2[m];
                        } catch(e) { result.instance2Methods[m] = 'ERR: ' + e.message; }
                    }
                } catch(e) { result.newInstanceAbOnlyErr = e.message; }

                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":12,"method":"Runtime.evaluate","params":{"expression":e3,"returnByValue":True}}))
        resp = await recv_response(ws, 12)
        print("\nConstructor tests:", resp.get("result",{}).get("result",{}).get("value","")[:8000])

asyncio.run(check())
