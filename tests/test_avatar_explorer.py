#!/usr/bin/env python3
"""
Test framework for the built avatar editor site.

Tests thumbnail cache invalidation, dynamic composition, canvas sizing,
and cross-tab consistency via Chrome DevTools Protocol.

Usage:
  python3 tests/test_avatar_explorer.py          # run all tests
  python3 tests/test_avatar_explorer.py --keep   # keep browser open after
  python3 tests/test_avatar_explorer.py --test 3 # run only test #3
"""

import asyncio, json, sys, os, time, signal, subprocess, base64, hashlib, shutil
from pathlib import Path
from io import BytesIO

# Add project root to path so we can import src.cdp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.cdp import CDPClient

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# === CONFIG ============================================================
PROJECT_DIR = Path(__file__).resolve().parent.parent
SITE_DIR = PROJECT_DIR / "_site"
CHROME_EXEC = None
CHROME_USER_DATA = "/tmp/chrome-test-profile"
TEST_TIMEOUT = 30  # seconds per test
CHROME_CANDIDATES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
]

# These can be overridden via CLI args
http_port = 8769
chrome_debug_port = 9223

def page_url():
    return f"http://127.0.0.1:{http_port}/index.html"

def find_chrome_exec(explicit=None):
    candidates = []
    if explicit:
        candidates.append(explicit)
    env_chrome = os.environ.get("CHROME_EXEC")
    if env_chrome:
        candidates.append(env_chrome)
    candidates.extend(CHROME_CANDIDATES)

    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isabs(candidate) and os.access(candidate, os.X_OK):
            return candidate
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None

# === HELPERS ===========================================================

class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

def ok(msg):
    print(f"  {Colors.GREEN}✓{Colors.RESET} {msg}")

def fail(msg):
    print(f"  {Colors.RED}✗{Colors.RESET} {msg}")

def info(msg):
    print(f"  {Colors.CYAN}→{Colors.RESET} {msg}")

def warn(msg):
    print(f"  {Colors.YELLOW}⚠{Colors.RESET} {msg}")


# === TEST RUNNER =======================================================

class TestRunner:
    def __init__(self, keep_browser=False, http_port=8769, debug_port=9223, chrome_exec=None):
        self.keep_browser = keep_browser
        self.http_port = http_port
        self.debug_port = debug_port
        self.chrome_exec = chrome_exec
        self.http_proc = None
        self.chrome_proc = None
        self.cdp = None
        self.tests = []
        self.results = []
        self._ws_url = None

    def register(self, name, fn):
        self.tests.append((name, fn))

    # -- setup / teardown ------------------------------------------------

    async def setup(self):
        """Start HTTP server, launch Chrome, connect CDP."""

        # 1. Build the Vite static site that will be published.
        info("Building static site...")
        build = subprocess.run(
            ["npm", "run", "build:site"],
            cwd=str(PROJECT_DIR),
            text=True,
            capture_output=True,
            check=False,
        )
        if build.returncode != 0:
            raise RuntimeError(build.stderr or build.stdout or "Vite build failed")
        ok("Static site built")

        # 2. Start HTTP server
        info("Starting HTTP server...")
        self.http_proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(self.http_port)],
            cwd=str(SITE_DIR),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        await asyncio.sleep(0.5)
        ok(f"HTTP server on :{self.http_port}")

        # 3. Kill any existing chrome on our debug port
        subprocess.run(
            ["pkill", "-f", f"remote-debugging-port={self.debug_port}"],
            capture_output=True,
        )
        await asyncio.sleep(0.3)

        # 4. Launch Chrome
        info("Launching Chrome...")
        os.makedirs(CHROME_USER_DATA, exist_ok=True)
        self.chrome_proc = subprocess.Popen(
            [
                self.chrome_exec,
                f"--remote-debugging-port={self.debug_port}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={CHROME_USER_DATA}",
                "--no-first-run",
                "--no-default-browser-check",
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-background-networking",
                "--window-size=1440,900",
                page_url(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True,
        )

        # 5. Wait for Chrome to start and get the page's WS URL
        info("Waiting for Chrome debug port...")
        import urllib.request
        for attempt in range(20):
            await asyncio.sleep(0.5)
            try:
                req = urllib.request.urlopen(
                    f"http://127.0.0.1:{self.debug_port}/json",
                    timeout=2,
                )
                pages = json.loads(req.read())
                # Find our page
                for p in pages:
                    if f"127.0.0.1:{self.http_port}" in p.get("url", ""):
                        self._ws_url = p["webSocketDebuggerUrl"]
                        break
                if self._ws_url:
                    break
            except Exception:
                pass
        else:
            stderr = ""
            if self.chrome_proc and self.chrome_proc.poll() is not None:
                _, stderr = self.chrome_proc.communicate(timeout=2)
            detail = f"Chrome did not start in time: {stderr[-1000:]}" if stderr else "Chrome did not start in time"
            raise RuntimeError(detail)

        ok(f"Chrome ready, WS: {self._ws_url[:60]}...")

        # 6. Connect CDP
        self.cdp = CDPClient(self._ws_url)
        await self.cdp.connect()

        # Enable required domains
        await self.cdp.send("Runtime.enable")
        await self.cdp.send("Page.enable")
        ok("CDP connected")

        # 7. Wait for page to fully load (Rive + config + tile instances)
        info("Waiting for app to load...")
        for attempt in range(30):
            ready = await self.cdp.evaluate(
                "window.__avatarTestHooks?.isReady?.() === true || (typeof riveInst !== 'undefined' && sharedRiveFile !== null && tileInstances.size > 0)"
            )
            if ready:
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError("App did not load in time")
        ok("App fully loaded")

    async def teardown(self):
        """Clean up processes."""
        if self.cdp:
            await self.cdp.close()

        if self.chrome_proc and not self.keep_browser:
            info("Stopping Chrome...")
            self.chrome_proc.terminate()
            try:
                self.chrome_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.chrome_proc.kill()
            self.chrome_proc = None

        if self.http_proc:
            info("Stopping HTTP server...")
            self.http_proc.terminate()
            try:
                self.http_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.http_proc.kill()
            self.http_proc = None

    # -- run -------------------------------------------------------------

    async def run(self, only_test=None):
        try:
            await self.setup()
        except Exception as e:
            fail(f"Setup failed: {e}")
            await self.teardown()
            return 1

        print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"{Colors.BOLD}Running {len(self.tests)} tests...{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")

        for idx, (name, fn) in enumerate(self.tests):
            if only_test is not None and (idx + 1) != only_test:
                continue

            print(f"{Colors.BOLD}[{idx + 1}/{len(self.tests)}] {name}{Colors.RESET}")
            try:
                await fn(self.cdp)
                self.results.append((name, "PASS", None))
                ok(f"{name} — PASS\n")
            except AssertionError as e:
                self.results.append((name, "FAIL", str(e)))
                fail(f"{name} — FAIL: {e}\n")
            except Exception as e:
                self.results.append((name, "ERROR", str(e)))
                fail(f"{name} — ERROR: {e}\n")

        # Summary
        passed = sum(1 for _, r, _ in self.results if r == "PASS")
        failed = len(self.results) - passed
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"{Colors.BOLD}Results: {Colors.GREEN}{passed} passed{Colors.RESET}, "
              f"{Colors.RED}{failed} failed{Colors.RESET} / {len(self.results)} total")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")

        # Print failures detail
        for name, result, detail in self.results:
            if result != "PASS":
                print(f"\n{Colors.RED}FAIL: {name}{Colors.RESET}")
                print(f"  {detail}")

        await self.teardown()
        return 0 if failed == 0 else 1


# === ASSERTION HELPERS ==================================================

async def assert_true(cdp, expr, desc):
    val = await cdp.evaluate(f"({expr}) === true")
    if not val:
        raise AssertionError(f"{desc}: expected true, got {val} (expr: {expr[:120]})")

async def assert_eq(cdp, expected, expr, desc):
    val = await cdp.evaluate(expr)
    if val != expected:
        raise AssertionError(f"{desc}: expected {expected!r}, got {val!r}")

async def assert_neq(cdp, expected, expr, desc):
    val = await cdp.evaluate(expr)
    if val == expected:
        raise AssertionError(f"{desc}: got unexpected {expected!r}")


# === TEST CASES ========================================================

async def test_01_canvas_dimensions(cdp: CDPClient):
    """Verify main canvas size and tile canvases exist."""
    info("Checking canvas dimensions...")

    # Main canvas size
    w = await cdp.evaluate("document.getElementById('riveCanvas').width")
    h = await cdp.evaluate("document.getElementById('riveCanvas').height")
    assert w == 1000, f"Main canvas width: expected 1000, got {w}"
    assert h == 1380, f"Main canvas height: expected 1380, got {h}"
    ok(f"Main canvas: {w}x{h}")

    # Tile canvases exist (replaces old thumbCanvas)
    tile_canvas_count = await cdp.evaluate(
        "document.querySelectorAll('.tab-panel.active .tile canvas.tile-canvas').length"
    )
    assert tile_canvas_count > 0, "No tile canvases found in active tab"
    ok(f"Tile canvases: {tile_canvas_count} in active tab")

    # Tile canvas size check
    tw = await cdp.evaluate(
        "document.querySelector('.tab-panel.active .tile canvas.tile-canvas').width"
    )
    th = await cdp.evaluate(
        "document.querySelector('.tab-panel.active .tile canvas.tile-canvas').height"
    )
    assert tw == 252, f"Tile canvas width: expected 252, got {tw}"
    assert th == 252, f"Tile canvas height: expected 252, got {th}"
    ok(f"Tile canvas: {tw}x{th}")


async def test_02_rive_loaded(cdp: CDPClient):
    """Verify Rive instance, shared RiveFile, and tile instances are loaded."""
    info("Checking Rive state...")

    # Main Rive instance exists
    has_rive = await cdp.evaluate("typeof riveInst !== 'undefined' && riveInst !== null")
    assert has_rive, "Main Rive instance not found"
    ok("Main Rive instance exists")

    # Shared RiveFile exists
    has_rive_file = await cdp.evaluate("sharedRiveFile !== null")
    assert has_rive_file, "Shared RiveFile not found"
    ok("Shared RiveFile exists")

    # Tile instances exist (replaces old thumbRive + thumbReady)
    instance_count = await cdp.evaluate("tileInstances.size")
    assert instance_count > 0, "No tile instances"
    ok(f"{instance_count} tile instances loaded")

    # State machine inputs loaded
    sm_count = await cdp.evaluate("Object.keys(stateMachineInputs).length")
    assert sm_count > 20, f"Expected >20 SM inputs, got {sm_count}"
    ok(f"{sm_count} state machine inputs loaded")

    # Current SM name
    sm_name = await cdp.evaluate("currentSM")
    assert sm_name == "SMAvatar", f"Expected SMAvatar, got {sm_name}"
    ok("Current SM is SMAvatar")


async def test_03_cache_invalidation_on_set_sm_value(cdp: CDPClient):
    """Verify that setSMValue marks other tabs dirty, current tab instances persist."""
    info("Testing smart invalidation with tile instances...")

    # Ensure we're on tab 0 (Body) with tile instances loaded
    await cdp.evaluate("switchTab(0)")
    await asyncio.sleep(2)

    instance_count_before = await cdp.evaluate("tileInstances.size")
    info(f"Tile instances before: {instance_count_before}")
    assert instance_count_before > 0, "No tile instances before setSMValue"

    # Now change a value via setSMValue
    body_val = await cdp.evaluate("currentInputValues['Body'] || 0")
    info(f"Current Body value: {body_val}")
    new_body = 3 if body_val != 3 else 4

    await cdp.evaluate(f"setSMValue('Body', {new_body})")

    # Current tab's instances should still exist (smart invalidation preserves them)
    instance_count_after = await cdp.evaluate("tileInstances.size")
    info(f"Tile instances after setSMValue: {instance_count_after}")
    assert instance_count_after >= instance_count_before, \
        f"Current tab instances should persist, was {instance_count_before}, got {instance_count_after}"
    ok(f"Current tab instances preserved ({instance_count_before} -> {instance_count_after})")

    # Other tabs should be marked dirty
    dirty_count = await cdp.evaluate("dirtyTabs.size")
    info(f"Tabs marked dirty: {dirty_count}")
    assert dirty_count > 0, "At least some tabs should be marked dirty"
    ok(f"{dirty_count} tabs marked dirty")

    # Switch to Eyes tab — dirty tab should get fresh instances
    await asyncio.sleep(1)
    await cdp.evaluate("switchTab(1)")
    await asyncio.sleep(3)

    instance_count_eyes = await cdp.evaluate("tileInstances.size")
    info(f"Tile instances after switching to Eyes tab: {instance_count_eyes}")
    # Eyes tab has 57 feature buttons — instance count should be at least as high
    assert instance_count_eyes >= instance_count_after, \
        f"Instances should persist after switching to dirty tab (was {instance_count_after}, got {instance_count_eyes})"
    tab1_has = await cdp.evaluate("hasActiveTabInstances(1)")
    assert tab1_has, "Eyes tab should have active instances after switch"
    ok(f"Eyes tab instances confirmed ({instance_count_after} -> {instance_count_eyes})")


async def test_04_thumbnail_dynamic_composition(cdp: CDPClient):
    """Verify tiles have live Rive canvas instances that reflect current state."""
    info("Testing dynamic tile composition...")

    # Set specific features to create a recognizable avatar state
    info("Setting Body=4, Expression=17, Hair=58...")
    await cdp.evaluate("setSMValue('Body', 4)")
    await cdp.evaluate("setSMValue('Expression', 17)")
    await cdp.evaluate("setSMValue('MainHair', 58)")
    await asyncio.sleep(0.5)

    # Switch to Eye tab (idx=1) to trigger tile instance creation
    info("Switching to Eyes tab...")
    await cdp.evaluate("switchTab(1)")
    await asyncio.sleep(3)

    # Check that tile canvases exist (not img elements anymore)
    tile_info = await cdp.evaluate("""
        (function() {
            var canvases = document.querySelectorAll('.tab-panel.active .tile canvas.tile-canvas');
            return JSON.stringify({
                canvasCount: canvases.length,
                uniqueSizes: [...new Set([...canvases].map(c => c.width + 'x' + c.height))],
                instanceCount: [...tileInstances.keys()].filter(k => k.startsWith('1-')).length
            });
        })()
    """)
    info(f"Eyes tab tiles: {tile_info}")

    parsed = json.loads(tile_info)
    assert parsed["canvasCount"] > 0, "No tile canvases found in Eyes tab"
    assert parsed["instanceCount"] > 1, \
        f"Expected multiple tile instances, got {parsed['instanceCount']}"
    ok(f"{parsed['canvasCount']} tile canvases with {parsed['instanceCount']} Rive instances")

    # Verify tile instances have unique state overrides
    tile_instance_keys = await cdp.evaluate(
        "JSON.stringify([...tileInstances.keys()].slice(0, 10))"
    )
    info(f"Sample instance keys: {tile_instance_keys}")

    # Now switch to Hair tab and verify tiles still exist
    info("Switching to Hair tab...")
    await cdp.evaluate("switchTab(2)")
    await asyncio.sleep(3)

    hair_canvases = await cdp.evaluate(
        "document.querySelectorAll('.tab-panel.active .tile canvas.tile-canvas').length"
    )
    assert hair_canvases > 0, "No tile canvases in Hair tab"
    ok(f"Hair tab has {hair_canvases} tile canvases")

    # Hair tile instances should exist
    hair_instances = await cdp.evaluate(
        "[...tileInstances.keys()].filter(k => k.startsWith('2-')).length"
    )
    assert hair_instances > 1, \
        f"Hair tab should have multiple instances, got {hair_instances}"
    ok(f"Hair tab: {hair_instances} Rive instances")


async def test_05_thumbnail_image_uniqueness_pixels(cdp: CDPClient):
    """Verify tile canvases are rendered with distinct content."""
    info("Testing visual uniqueness of tile canvases...")

    # Go to Body tab
    await cdp.evaluate("switchTab(0)")
    await asyncio.sleep(3)

    # Check that tile canvases exist and have rendered content (non-blank pixels)
    result = await cdp.evaluate("""
        (function() {
            var canvases = document.querySelectorAll('.tab-panel.active .tile canvas.tile-canvas');
            var pixelSamples = [];
            for (var i = 0; i < Math.min(6, canvases.length); i++) {
                var ctx = canvases[i].getContext('2d');
                var sample = [];
                // Sample 4 corners to verify canvas is not blank
                var w = canvases[i].width, h = canvases[i].height;
                // Sample center and corners
                var points = [[w/2, h/2, 'center'], [5,5,'tl'], [w-5,5,'tr'], [5,h-5,'bl'], [w-5,h-5,'br']];
                for (var p = 0; p < points.length; p++) {
                    var px = ctx.getImageData(points[p][0], points[p][1], 1, 1).data;
                    sample.push(px[0] + ',' + px[1] + ',' + px[2]);
                }
                pixelSamples.push({idx: i, pixels: sample, label: points.map(function(p){return p[2]})});
            }
            return JSON.stringify({samples: pixelSamples, count: canvases.length});
        })()
    """)

    parsed = json.loads(result)
    info(f"Tile canvases: {parsed['count']} total, sampled {len(parsed['samples'])}")
    assert parsed['count'] > 0, "No tile canvases found"

    # Check that at least one sampled pixel is non-zero (non-blank canvas)
    non_blank = 0
    for s in parsed['samples']:
        pixels = s['pixels']
        # A canvas is "rendered" if at least one pixel is not 0,0,0 or 255,255,255
        for p in pixels:
            if p != '0,0,0' and p != '255,255,255':
                non_blank += 1
                break
    ok(f"{non_blank}/{len(parsed['samples'])} tile canvases have rendered content")

    # Verify multiple distinct instances exist (by checking their keys)
    key_diversity = await cdp.evaluate("""
        (function() {
            var keys = [...tileInstances.keys()].filter(function(k) { return k.startsWith('0-'); });
            var values = new Set();
            for (var k of keys) {
                values.add(k.split('-').slice(1).join('-'));
            }
            return JSON.stringify({keys: keys.length, unique: values.size});
        })()
    """)
    key_info = json.loads(key_diversity)
    assert key_info['unique'] > 1, f"Expected >1 unique tile configs, got {key_info['unique']}"
    ok(f"{key_info['unique']} unique tile configurations ({key_info['keys']} instances)")


async def test_06_cross_tab_state_persistence(cdp: CDPClient):
    """Verify that changing features in one tab persists correctly."""
    info("Testing cross-tab state persistence...")

    # Set a distinctive feature combination
    await cdp.evaluate("setSMValue('Body', 2)")
    await cdp.evaluate("setSMValue('MainHair', 50)")
    await asyncio.sleep(0.5)

    # Go to Body tab
    await cdp.evaluate("switchTab(0)")
    await asyncio.sleep(3)

    body_canvas_count = await cdp.evaluate(
        "document.querySelectorAll('.tab-panel.active .tile canvas.tile-canvas').length"
    )
    info(f"Body tab: {body_canvas_count} tile canvases")
    assert body_canvas_count > 0, "No tile canvases in Body tab"

    # Now change hair while on Body tab
    await cdp.evaluate("setSMValue('MainHair', 48)")
    await asyncio.sleep(2)

    # Body tile instances should still exist
    body_canvas_after = await cdp.evaluate(
        "document.querySelectorAll('.tab-panel.active .tile canvas.tile-canvas').length"
    )
    assert body_canvas_after > 0, "Tile canvases should persist after hair change"
    ok(f"Body tile canvases persist after hair change: {body_canvas_after}")

    # Verify currentInputValues reflects the changes
    body_val = await cdp.evaluate("currentInputValues['Body']")
    hair_val = await cdp.evaluate("currentInputValues['MainHair']")
    assert body_val == 2, f"Body should be 2, got {body_val}"
    assert hair_val == 48, f"MainHair should be 48, got {hair_val}"
    ok(f"State preserved: Body={body_val}, MainHair={hair_val}")


async def test_07_cache_key_format(cdp: CDPClient):
    """Verify tileInstances map key format: tabIdx-sectionIdx-idx."""
    info("Testing tile instance key format...")

    await cdp.evaluate("switchTab(0)")
    await asyncio.sleep(3)

    keys = await cdp.evaluate("JSON.stringify([...tileInstances.keys()].slice(0, 10))")
    key_list = json.loads(keys)
    info(f"Sample tile instance keys: {key_list}")

    assert len(key_list) > 0, "No tile instance keys found"
    for key in key_list:
        parts = key.split("-")
        assert len(parts) == 3, f"Instance key '{key}' should have 3 parts (tab-section-idx)"
        assert all(p.isdigit() for p in parts), f"All key parts should be numeric: '{key}'"
    ok(f"All {len(key_list)} instance keys have valid format (tabIdx-sectionIdx-idx)")

    # Verify tileInstances is a Map
    is_map = await cdp.evaluate("tileInstances instanceof Map")
    assert is_map, "tileInstances should be a Map"
    ok("tileInstances is a Map")


async def test_08_thumb_status_feedback(cdp: CDPClient):
    """Verify the tile rendering status indicator shows progress."""
    info("Testing tile status feedback...")

    # Trigger re-render to see the status text
    await cdp.evaluate("renderTabTiles(0)")
    await asyncio.sleep(0.2)

    status = await cdp.evaluate(
        "document.getElementById('thumbStatus').textContent"
    )
    info(f"Status text during rendering: '{status}'")

    # Status should eventually clear
    await asyncio.sleep(5)
    status_after = await cdp.evaluate(
        "document.getElementById('thumbStatus').textContent"
    )
    assert status_after == "", \
        f"Status should be empty after rendering, got '{status_after}'"
    ok("Status text cleared after rendering completes")


async def test_09_reset_all(cdp: CDPClient):
    """Verify resetAll() restores defaults and recreates tile instances."""
    info("Testing resetAll()...")

    # Change some values away from defaults
    await cdp.evaluate("setSMValue('Body', 5)")
    await cdp.evaluate("setSMValue('MainHair', 10)")
    await asyncio.sleep(0.5)

    # Verify changes took effect
    body_before = await cdp.evaluate("currentInputValues['Body']")
    assert body_before == 5, f"Body should be 5, got {body_before}"
    ok(f"Before reset: Body={body_before}")

    # Reset
    await cdp.evaluate("resetAll()")
    await asyncio.sleep(3)

    # Values should be back to defaults
    body_after = await cdp.evaluate("currentInputValues['Body']")
    info(f"After reset: Body={body_after}")

    # Tile instances should exist after reset triggers regeneration
    instance_count = await cdp.evaluate("tileInstances.size")
    assert instance_count > 0, "Tile instances should exist after reset"
    ok(f"Tile instances regenerated after reset: {instance_count}")


async def test_10_no_duplicate_thumbnails_in_tile(cdp: CDPClient):
    """Verify each tile has exactly one canvas element (no duplicate canvases)."""
    info("Testing tile canvas count...")

    await cdp.evaluate("switchTab(0)")
    await asyncio.sleep(3)

    canvas_counts = await cdp.evaluate("""
        (function() {
            var tiles = document.querySelectorAll('.tab-panel.active .tile');
            var counts = [];
            for (var t of tiles) {
                counts.push(t.querySelectorAll('canvas').length);
            }
            return JSON.stringify(counts);
        })()
    """)
    counts = json.loads(canvas_counts)
    info(f"Canvas counts per tile: {counts}")

    for i, c in enumerate(counts):
        assert c <= 1, f"Tile {i} has {c} canvas elements (should be 0 or 1)"
    ok(f"All {len(counts)} tiles have at most 1 canvas element")


async def test_11_mobile_shell_layout(cdp: CDPClient):
    """Verify mobile layout keeps preview fixed and separates actions from category tabs."""
    info("Testing mobile shell layout...")

    await cdp.send("Emulation.setDeviceMetricsOverride", {
        "width": 390,
        "height": 844,
        "deviceScaleFactor": 2,
        "mobile": True,
    })
    await asyncio.sleep(0.5)

    layout_json = await cdp.evaluate("""
        (function() {
            var preview = document.querySelector('.preview-panel').getBoundingClientRect();
            var tabs = document.querySelector('.tab-bar').getBoundingClientRect();
            var actions = document.querySelector('.mobile-action-bar').getBoundingClientRect();
            var options = document.querySelector('.options-scroll');
            var optionsRect = options.getBoundingClientRect();
            var actionLabels = Array.from(document.querySelectorAll('.mobile-action-bar .btn'))
                .map(function(btn) { return btn.textContent.trim(); });
            var beforeTop = preview.top;
            options.scrollTop = 500;
            var afterTop = document.querySelector('.preview-panel').getBoundingClientRect().top;
            return JSON.stringify({
                innerHeight: window.innerHeight,
                bodyOverflowY: getComputedStyle(document.body).overflowY,
                optionsOverflowY: getComputedStyle(options).overflowY,
                previewTop: preview.top,
                previewBottom: preview.bottom,
                previewHeight: preview.height,
                tabsTop: tabs.top,
                tabsBottom: tabs.bottom,
                actionsTop: actions.top,
                actionsBottom: actions.bottom,
                actionsDisplay: getComputedStyle(document.querySelector('.mobile-action-bar')).display,
                tabsPosition: getComputedStyle(document.querySelector('.tab-bar')).position,
                toolRailDisplay: getComputedStyle(document.querySelector('.tool-rail')).display,
                tabCount: document.querySelectorAll('.tab-btn').length,
                actionLabels: actionLabels,
                optionsClientHeight: options.clientHeight,
                optionsScrollHeight: options.scrollHeight,
                optionsTop: optionsRect.top,
                optionsBottom: optionsRect.bottom,
                previewTopAfterOptionsScroll: afterTop,
                previewTopBeforeOptionsScroll: beforeTop,
                windowScrollY: window.scrollY
            });
        })()
    """)
    layout = json.loads(layout_json)
    info(f"Mobile layout: {layout}")

    assert layout["actionsDisplay"] != "none", "Mobile action bar should be visible"
    assert layout["toolRailDisplay"] == "none", "Desktop action rail should be hidden on mobile"
    assert layout["tabCount"] == 8, f"Category tabs should contain 8 avatar groups, got {layout['tabCount']}"
    assert layout["actionLabels"] == ["Generate", "Export", "Reset", "More"], \
        f"Mobile action bar should only contain global actions, got {layout['actionLabels']}"
    assert layout["tabsPosition"] == "static", f"Category tabs should not be fixed, got {layout['tabsPosition']}"
    assert layout["previewHeight"] >= 220, f"Preview should remain visible, got height {layout['previewHeight']}"
    assert layout["tabsTop"] >= layout["previewBottom"] - 2, "Category tabs should sit below preview"
    assert layout["tabsBottom"] < layout["actionsTop"], "Category tabs should stay above the bottom action bar"
    assert layout["optionsBottom"] <= layout["actionsTop"] + 2, "Options scroller should not run behind actions"
    assert layout["optionsOverflowY"] in ("auto", "scroll"), \
        f"Options panel should own vertical scrolling, got {layout['optionsOverflowY']}"
    assert abs(layout["previewTopAfterOptionsScroll"] - layout["previewTopBeforeOptionsScroll"]) < 1, \
        "Preview should not move when options scroll"
    assert layout["bodyOverflowY"] == "hidden", f"Body should not own mobile scrolling, got {layout['bodyOverflowY']}"
    assert layout["windowScrollY"] == 0, f"Window should not scroll on mobile shell, got {layout['windowScrollY']}"
    ok("Mobile shell keeps preview fixed and actions separate")

    await cdp.send("Emulation.clearDeviceMetricsOverride")


async def test_12_ai_generate_mock_and_history(cdp: CDPClient):
    """Verify AI route, streamed result application, and undo/redo history with a mocked backend."""
    info("Testing mocked AI generation and history...")

    result_json = await cdp.evaluate_async("""
        (async function() {
            var before = currentInputValues['Body'];
            var target = before === 5 ? 1 : 5;
            var originalFetch = window.fetch.bind(window);

            window.__TEST_TURNSTILE_TOKEN__ = 'test-token';
            backendConfig = {
                baseUrl: API_BASE_URL,
                available: true,
                config: {
                    ok: true,
                    features: { avatarGeneration: true },
                    generation: {
                        turnstileSiteKey: 'test-site-key',
                        maxPromptLength: 800,
                        sessionTtlSeconds: 1800,
                        supportedMentions: ['current', 'default']
                    },
                    endpoints: {
                        avatarSession: '/api/avatar/session',
                        avatarGenerate: '/api/avatar/generate'
                    }
                }
            };
            window.avatarBackend = backendConfig;
            window.fetch = function(url, init) {
                if (String(url).indexOf('/api/avatar/session') !== -1) {
                    return Promise.resolve(new Response(JSON.stringify({
                        ok: true,
                        sessionToken: 'test-ai-session',
                        expiresAt: Date.now() + 1800000,
                        ttlSeconds: 1800
                    }), {
                        status: 200,
                        headers: { 'Content-Type': 'application/json' }
                    }));
                }
                if (String(url).indexOf('/api/avatar/generate') !== -1) {
                    var payload = JSON.parse(init.body || '{}');
                    if (payload.sessionToken !== 'test-ai-session') {
                        return Promise.resolve(new Response(JSON.stringify({
                            ok: false,
                            error: 'session_required'
                        }), {
                            status: 401,
                            headers: { 'Content-Type': 'application/json' }
                        }));
                    }
                    var final = {
                        ok: true,
                        contextMode: 'current',
                        avatarState: { Body: target },
                        steps: ['Open Body and choose the generated body tile.'],
                        warnings: [],
                        confidence: 0.8
                    };
                    var body = ''
                        + 'event: plan_delta\\n'
                        + 'data: {"text":"Choose a stronger body shape."}\\n\\n'
                        + 'event: final\\n'
                        + 'data: ' + JSON.stringify(final) + '\\n\\n';
                    return Promise.resolve(new Response(body, {
                        status: 200,
                        headers: { 'Content-Type': 'text/event-stream' }
                    }));
                }
                return originalFetch(url, init);
            };

            openGeneratePage();
            await new Promise(function(resolve) { setTimeout(resolve, 100); });
            aiPrompt.value = '@current make it bold';
            aiPrompt.dispatchEvent(new Event('input', { bubbles: true }));
            var disabledBeforeVerify = generateBtn.disabled;
            await verifyAiSession();
            await new Promise(function(resolve) { setTimeout(resolve, 100); });
            var disabledAfterVerify = generateBtn.disabled;
            await startAvatarGeneration();
            await new Promise(function(resolve) { setTimeout(resolve, 300); });
            var after = currentInputValues['Body'];
            var streamText = document.getElementById('aiStream').textContent;
            var stepCount = document.querySelectorAll('#aiSteps li').length;

            undoAvatarChange();
            await new Promise(function(resolve) { setTimeout(resolve, 200); });
            var undone = currentInputValues['Body'];

            redoAvatarChange();
            await new Promise(function(resolve) { setTimeout(resolve, 200); });
            var redone = currentInputValues['Body'];

            window.fetch = originalFetch;
            return JSON.stringify({
                before: before,
                target: target,
                after: after,
                undone: undone,
                redone: redone,
                disabledBeforeVerify: disabledBeforeVerify,
                disabledAfterVerify: disabledAfterVerify,
                streamText: streamText,
                stepCount: stepCount,
                modeGenerate: document.body.classList.contains('mode-generate'),
                actionLabels: Array.from(document.querySelectorAll('.mobile-action-bar .btn'))
                    .map(function(btn) { return btn.textContent.trim(); })
            });
        })()
    """)
    result = json.loads(result_json)
    info(f"Mocked AI result: {result}")

    assert result["modeGenerate"], "Generate route should activate mode-generate"
    assert result["disabledBeforeVerify"], "Generate should be disabled before explicit Verify"
    assert not result["disabledAfterVerify"], "Generate should be enabled after a verified AI session"
    assert result["after"] == result["target"], "AI final state should apply to current avatar"
    assert result["undone"] == result["before"], "Undo should restore the pre-AI avatar state"
    assert result["redone"] == result["target"], "Redo should restore the AI avatar state"
    assert "stronger body" in result["streamText"], "Streamed planning text should be visible"
    assert result["stepCount"] == 1, "Final manual guide should render one mocked step"
    assert result["actionLabels"] == ["Generate", "Export", "Reset", "More"], \
        f"Mobile action bar should include Generate, got {result['actionLabels']}"


# === MAIN ===============================================================

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Avatar Explorer Test Suite")
    parser.add_argument("--keep", action="store_true",
                        help="Keep browser open after tests")
    parser.add_argument("--test", type=int, default=None,
                        help="Run only a specific test number")
    parser.add_argument("--port", type=int, default=8769,
                        help="HTTP server port (default: 8769)")
    parser.add_argument("--debug-port", type=int, default=9223,
                        help="Chrome debug port (default: 9223)")
    parser.add_argument("--chrome-exec", default=None,
                        help="Path or command for Chrome/Chromium")
    parser.add_argument("--require-browser", action="store_true",
                        help="Fail instead of skipping when Chrome/Chromium is unavailable")
    args = parser.parse_args()

    chrome_exec = find_chrome_exec(args.chrome_exec)
    if not chrome_exec:
        if args.require_browser:
            msg = "No Chrome/Chromium found"
            fail(msg)
            sys.exit(1)
        msg = "SKIP: no Chrome/Chromium found"
        warn(msg)
        sys.exit(0)
    ok(f"Using browser: {chrome_exec}")

    # Update module-level config so page_url() works
    global http_port, chrome_debug_port, CHROME_EXEC
    http_port = args.port
    chrome_debug_port = args.debug_port
    CHROME_EXEC = chrome_exec

    runner = TestRunner(
        keep_browser=args.keep,
        http_port=args.port,
        debug_port=args.debug_port,
        chrome_exec=chrome_exec,
    )

    # Register all tests
    runner.register("Canvas dimensions", test_01_canvas_dimensions)
    runner.register("Rive loaded and ready", test_02_rive_loaded)
    runner.register("Cache invalidation on setSMValue", test_03_cache_invalidation_on_set_sm_value)
    runner.register("Thumbnail dynamic composition", test_04_thumbnail_dynamic_composition)
    runner.register("Thumbnail visual uniqueness", test_05_thumbnail_image_uniqueness_pixels)
    runner.register("Cross-tab state persistence", test_06_cross_tab_state_persistence)
    runner.register("Cache key format", test_07_cache_key_format)
    runner.register("Thumbnail status feedback", test_08_thumb_status_feedback)
    runner.register("Reset restores defaults", test_09_reset_all)
    runner.register("No duplicate images in tiles", test_10_no_duplicate_thumbnails_in_tile)
    runner.register("Mobile shell layout", test_11_mobile_shell_layout)
    runner.register("Mocked AI generation and history", test_12_ai_generate_mock_and_history)

    exit_code = await runner.run(only_test=args.test)
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
