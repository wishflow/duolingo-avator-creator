#!/usr/bin/env python3
"""Create StateMachineInstance and enumerate all inputs."""
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

        # Create StateMachineInstance and get inputs
        e = """(function() {
            try {
                var runtime = riveInst.runtime;
                var file = riveInst.riveFile.file;
                var ab = file.defaultArtboard();
                var SMInst = runtime.StateMachineInstance;

                var result = {};
                var smCount = ab.stateMachineCount();

                for (var i = 0; i < smCount; i++) {
                    var sm = ab.stateMachineByIndex(i);
                    var smName = sm.name;
                    var smInfo = {name: smName};

                    try {
                        var instance = new SMInst(sm, ab);
                        smInfo.instanceCreated = true;

                        // Check input count
                        try { smInfo.inputCount = instance.inputCount(); } catch(e) { smInfo.inputCountErr = e.message; }

                        // Enumerate inputs
                        if (smInfo.inputCount > 0) {
                            smInfo.inputs = [];
                            for (var j = 0; j < smInfo.inputCount; j++) {
                                try {
                                    var inp = instance.input(j);
                                    if (inp) {
                                        smInfo.inputs.push({
                                            index: j,
                                            name: inp.name,
                                            type: inp.type,
                                            value: inp.value,
                                        });
                                    }
                                } catch(e) {
                                    smInfo.inputs.push({index: j, err: e.message});
                                }
                            }
                        }

                        // Also try getBool, getNumber, getTrigger with known names
                        smInfo.testGetters = {};
                        var testNames = ['SkinTone', 'Body', 'Expression', 'BackgroundColor', 'MainHair'];
                        for (var k = 0; k < testNames.length; k++) {
                            var name = testNames[k];
                            try {
                                var boolInp = instance.getBool(name);
                                smInfo.testGetters['getBool_' + name] = boolInp ? ('name:' + boolInp.name + ' value:' + boolInp.value) : 'null';
                            } catch(e) { smInfo.testGetters['getBool_' + name] = 'ERR: ' + e.message; }
                            try {
                                var numInp = instance.getNumber(name);
                                smInfo.testGetters['getNumber_' + name] = numInp ? ('name:' + numInp.name + ' value:' + numInp.value) : 'null';
                            } catch(e) { smInfo.testGetters['getNumber_' + name] = 'ERR: ' + e.message; }
                            try {
                                var trigInp = instance.getTrigger(name);
                                smInfo.testGetters['getTrigger_' + name] = trigInp ? ('name:' + trigInp.name) : 'null';
                            } catch(e) { smInfo.testGetters['getTrigger_' + name] = 'ERR: ' + e.message; }
                        }

                    } catch(e) { smInfo.instanceErr = e.message; }

                    result['sm_' + i] = smInfo;
                }

                return JSON.stringify(result, null, 2);
            } catch(e) { return 'ERR: ' + e.message; }
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print("StateMachineInstance inputs:", resp.get("result",{}).get("result",{}).get("value","")[:15000])

asyncio.run(check())
