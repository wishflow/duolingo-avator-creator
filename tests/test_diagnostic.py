#!/usr/bin/env python3
"""Deep diagnostic: why are all thumbnails identical?"""
import asyncio, json, sys, os, subprocess, base64, time, hashlib
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_DIR / "assets"
HTTP_PORT = 8770
DEBUG_PORT = 9224

sys.path.insert(0, str(PROJECT_DIR / "tests"))
from test_avatar_explorer import CDPClient, Colors, ok, fail, info, warn

async def main():
    # Start HTTP server
    info("Starting HTTP server...")
    http_proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(HTTP_PORT)],
        cwd=str(ASSETS_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    await asyncio.sleep(0.5)

    # Kill old chrome
    subprocess.run(["pkill", "-f", f"remote-debugging-port={DEBUG_PORT}"], capture_output=True)
    await asyncio.sleep(0.3)

    # Launch Chrome
    info("Launching Chrome...")
    os.makedirs("/tmp/chrome-test-profile", exist_ok=True)
    chrome_proc = subprocess.Popen(
        ["google-chrome", f"--remote-debugging-port={DEBUG_PORT}",
         "--user-data-dir=/tmp/chrome-test-profile", "--no-first-run",
         "--no-default-browser-check", "--headless=new", "--window-size=1440,900",
         f"http://127.0.0.1:{HTTP_PORT}/avatar_explorer.html"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # Get WS URL
    import urllib.request
    ws_url = None
    for _ in range(20):
        await asyncio.sleep(0.5)
        try:
            req = urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=2)
            for p in json.loads(req.read()):
                if "avatar_explorer" in p.get("url", ""):
                    ws_url = p["webSocketDebuggerUrl"]
        except Exception: pass
        if ws_url: break

    cdp = CDPClient(ws_url)
    await cdp.connect()
    await cdp.send("Runtime.enable")
    await cdp.send("Page.enable")

    # Wait for app load
    for _ in range(30):
        ready = await cdp.evaluate("typeof riveInst !== 'undefined' && typeof thumbRive !== 'undefined' && thumbReady")
        if ready: break
        await asyncio.sleep(1)

    ok("App loaded")

    print(f"\n{'='*60}")
    print("DIAGNOSTIC 1: Check thumbnail canvas rendering")
    print(f"{'='*60}")

    # 1. Check if the thumbnail canvas has any content at all
    # Force a single thumbnail capture and check its data URL
    result = await cdp.evaluate("""
        (function() {
            // Get the first feature button from the first tab
            var tabs = builderConfig.avatarBuilderConfig.stateChooserTabs;
            var fb = null;
            for (var t of tabs) {
                for (var s of t.sections) {
                    if (s.buttonType === 'FEATURE' && s.featureButtons.length > 0) {
                        fb = s.featureButtons[0];
                        break;
                    }
                }
                if (fb) break;
            }
            if (!fb) return 'no feature button found';

            // Capture a thumbnail synchronously
            var inputs = thumbRive.stateMachineInputs('SMAvatar');
            var data = {};
            data.inputCount = inputs ? inputs.length : 0;

            if (inputs) {
                // Set current values
                for (var inp of inputs) {
                    if (inp.type === 56 && currentInputValues[inp.name] !== undefined) {
                        inp.value = currentInputValues[inp.name];
                    }
                }

                // Log what values were set
                data.beforeOverride = {};
                for (var inp of inputs) {
                    if (inp.type === 56 && (inp.name === 'Body' || inp.name === 'MainHair' || inp.name === 'Expression')) {
                        data.beforeOverride[inp.name] = inp.value;
                    }
                }

                // Override with fb values
                data.primaryState = fb.state;
                data.statesToOverride = fb.statesToOverride;
                for (var key in fb.statesToOverride) {
                    var val = fb.statesToOverride[key];
                    if (val === 0 && key !== fb.state) continue;
                    var inp = inputs.find(function(i) { return i.name === key; });
                    if (inp && inp.type === 56) {
                        data['set_' + key] = val;
                        inp.value = val;
                    }
                }

                data.afterOverride = {};
                for (var inp of inputs) {
                    if (inp.type === 56 && (inp.name === 'Body' || inp.name === 'MainHair' || inp.name === 'Expression')) {
                        data.afterOverride[inp.name] = inp.value;
                    }
                }

                // Fire trigger
                var trig = inputs.find(function(i) { return i.name === 'bounce_trig'; });
                if (trig) { trig.fire(); data.triggerFired = true; }
                else { data.triggerFired = false; }
            }

            return JSON.stringify(data, null, 2);
        })()
    """)
    print(f"First capture diagnostics:\n{result}")

    # 2. Now try capturing two different thumbnails and compare
    print(f"\n{'='*60}")
    print("DIAGNOSTIC 2: Compare two different feature button captures")
    print(f"{'='*60}")

    result2 = await cdp.evaluate("""
        (function() {
            var tabs = builderConfig.avatarBuilderConfig.stateChooserTabs;
            var buttons = [];
            for (var t of tabs) {
                for (var s of t.sections) {
                    if (s.buttonType === 'FEATURE') {
                        buttons = s.featureButtons;
                        break;
                    }
                }
                if (buttons.length > 1) break;
            }

            if (buttons.length < 2) return 'need 2+ buttons';

            var data = {};
            data.button0 = {state: buttons[0].state, value: buttons[0].value, statesToOverride: JSON.stringify(buttons[0].statesToOverride)};
            data.button1 = {state: buttons[1].state, value: buttons[1].value, statesToOverride: JSON.stringify(buttons[1].statesToOverride)};

            // Check if statesToOverride differs between buttons
            data.sameOverride = JSON.stringify(buttons[0].statesToOverride) === JSON.stringify(buttons[1].statesToOverride);

            // Also show ALL keys in statesToOverride that have non-zero values
            var nonZero0 = {};
            var nonZero1 = {};
            for (var k in buttons[0].statesToOverride) {
                if (buttons[0].statesToOverride[k] !== 0) nonZero0[k] = buttons[0].statesToOverride[k];
            }
            for (var k in buttons[1].statesToOverride) {
                if (buttons[1].statesToOverride[k] !== 0) nonZero1[k] = buttons[1].statesToOverride[k];
            }
            data.nonZeroValues0 = JSON.stringify(nonZero0);
            data.nonZeroValues1 = JSON.stringify(nonZero1);

            return JSON.stringify(data, null, 2);
        })()
    """)
    print(f"Two buttons comparison:\n{result2}")

    # 3. The REAL test: capture two thumbnails sequentially using our async function
    print(f"\n{'='*60}")
    print("DIAGNOSTIC 3: Sequential thumbnail captures via CDP")
    print(f"{'='*60}")

    result3 = await cdp.evaluate("""
        (async function() {
            var tabs = builderConfig.avatarBuilderConfig.stateChooserTabs;
            var buttons = [];
            for (var t of tabs) {
                for (var s of t.sections) {
                    if (s.buttonType === 'FEATURE') {
                        buttons = s.featureButtons;
                        break;
                    }
                }
                if (buttons.length > 1) break;
            }

            // Capture two thumbnails using our actual captureThumbFor
            var uri1 = await captureThumbFor(buttons[0]);
            var uri2 = await captureThumbFor(buttons[1]);

            var data = {};
            data.uri1_len = uri1 ? uri1.length : 0;
            data.uri2_len = uri2 ? uri2.length : 0;
            data.same = (uri1 === uri2);
            data.uri1_preview = uri1 ? uri1.substring(0, 100) : 'null';
            data.uri2_preview = uri2 ? uri2.substring(0, 100) : 'null';
            data.cache_keys = Object.keys(thumbCache).slice(0, 5);

            // Also check current state
            data.Body = currentInputValues['Body'];
            data.MainHair = currentInputValues['MainHair'];
            data.Expression = currentInputValues['Expression'];

            // Check what the two feature buttons override
            data.fb0 = {state: buttons[0].state, value: buttons[0].value};
            data.fb1 = {state: buttons[1].state, value: buttons[1].value};

            return JSON.stringify(data, null, 2);
        })()
    """)
    print(f"Sequential capture results:\n{result3}")

    # 4. Check if the thumbnail canvas itself has valid WebGL content
    print(f"\n{'='*60}")
    print("DIAGNOSTIC 4: Check if thumbCanvas actually renders")
    print(f"{'='*60}")

    result4 = await cdp.evaluate("""
        (function() {
            // Make thumbCanvas visible temporarily to check
            var tc = document.getElementById('thumbCanvas');
            var data = {};
            data.width = tc.width;
            data.height = tc.height;
            data.style = tc.style.display;

            // Try to get the WebGL context
            var gl = tc.getContext('webgl2') || tc.getContext('webgl');
            data.hasWebGL = !!gl;

            if (gl) {
                // Read a pixel from the center
                var pixel = new Uint8Array(4);
                gl.readPixels(tc.width/2, tc.height/2, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
                data.centerPixel = Array.from(pixel);

                // Check if canvas is all same color
                var samples = [];
                for (var i = 0; i < 5; i++) {
                    var x = Math.floor(Math.random() * tc.width);
                    var y = Math.floor(Math.random() * tc.height);
                    gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
                    samples.push(Array.from(pixel).join(','));
                }
                data.samplePixels = samples;
                data.allSameSamples = new Set(samples).size === 1;
            }

            return JSON.stringify(data, null, 2);
        })()
    """)
    print(f"ThumbCanvas state:\n{result4}")

    # 5. Check what the initial thumbnail Rive state looks like
    print(f"\n{'='*60}")
    print("DIAGNOSTIC 5: Thumbnail Rive state machine current values")
    print(f"{'='*60}")

    result5 = await cdp.evaluate("""
        (function() {
            var inputs = thumbRive.stateMachineInputs('SMAvatar');
            if (!inputs) return 'no inputs';
            var data = {};
            for (var inp of inputs) {
                if (inp.type === 56 && inp.value !== 0) {
                    data[inp.name] = inp.value;
                }
            }
            return JSON.stringify(data, null, 2);
        })()
    """)
    print(f"Thumbnail Rive non-zero values:\n{result5}")

    # 6. FIXED TEST: Force different values and check
    print(f"\n{'='*60}")
    print("DIAGNOSTIC 6: Force different Body values, capture, compare")
    print(f"{'='*60}")

    result6 = await cdp.evaluate("""
        (async function() {
            var inputs = thumbRive.stateMachineInputs('SMAvatar');
            if (!inputs) return 'no inputs';

            var nameMap = {};
            for (var inp of inputs) {
                nameMap[inp.name] = inp;
                if (inp.type === 56 && currentInputValues[inp.name] !== undefined) {
                    inp.value = currentInputValues[inp.name];
                }
            }

            // Fire trigger to apply current values
            if (nameMap['bounce_trig']) nameMap['bounce_trig'].fire();

            // Wait for render
            await new Promise(function(r) { requestAnimationFrame(function() { requestAnimationFrame(r); }); });

            // Capture 1: Body=1
            nameMap['Body'].value = 1;
            if (nameMap['bounce_trig']) nameMap['bounce_trig'].fire();
            await new Promise(function(r) { requestAnimationFrame(function() { requestAnimationFrame(r); }); });
            var uri1 = document.getElementById('thumbCanvas').toDataURL('image/png');

            // Capture 2: Body=6
            nameMap['Body'].value = 6;
            if (nameMap['bounce_trig']) nameMap['bounce_trig'].fire();
            await new Promise(function(r) { requestAnimationFrame(function() { requestAnimationFrame(r); }); });
            var uri2 = document.getElementById('thumbCanvas').toDataURL('image/png');

            var data = {};
            data.same = (uri1 === uri2);
            data.len1 = uri1.length;
            data.len2 = uri2.length;

            // Compare first 500 chars
            data.head1 = uri1.substring(0, 200);
            data.head2 = uri2.substring(0, 200);
            data.headSame = data.head1 === data.head2;

            return JSON.stringify(data, null, 2);
        })()
    """)
    print(f"Force-different captures:\n{result6}")

    # Cleanup
    await cdp.close()
    chrome_proc.terminate()
    try: chrome_proc.wait(timeout=5)
    except: chrome_proc.kill()
    http_proc.terminate()
    try: http_proc.wait(timeout=3)
    except: http_proc.kill()

asyncio.run(main())
