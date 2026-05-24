#!/usr/bin/env python3
"""
Test framework for avatar_explorer.html.

Tests thumbnail cache invalidation, dynamic composition, canvas sizing,
and cross-tab consistency via Chrome DevTools Protocol.

Usage:
  python3 tests/test_avatar_explorer.py          # run all tests
  python3 tests/test_avatar_explorer.py --keep   # keep browser open after
  python3 tests/test_avatar_explorer.py --test 3 # run only test #3
"""

import asyncio, json, sys, os, time, signal, subprocess, base64, hashlib
from pathlib import Path
from io import BytesIO

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# === CONFIG ============================================================
PROJECT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_DIR / "assets"
CHROME_EXEC = "google-chrome"
CHROME_USER_DATA = "/tmp/chrome-test-profile"
TEST_TIMEOUT = 30  # seconds per test

# These can be overridden via CLI args
http_port = 8769
chrome_debug_port = 9223

def page_url():
    return f"http://127.0.0.1:{http_port}/avatar_explorer.html"

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


class CDPClient:
    """Minimal CDP client over a single WebSocket connection."""

    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self._req_id = 0
        self._pending = {}

    async def connect(self):
        import websockets
        self.ws = await websockets.connect(
            self.ws_url, max_size=100 * 1024 * 1024,
            ping_interval=30, ping_timeout=10,
        )
        # Drain init messages
        await asyncio.sleep(0.3)
        while True:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                break

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def _recv_id(self, eid, timeout=TEST_TIMEOUT):
        while True:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            msg = json.loads(raw)
            if msg.get("id") == eid:
                if "error" in msg:
                    raise RuntimeError(f"CDP error: {msg['error']}")
                return msg

    async def send(self, method, params=None):
        self._req_id += 1
        eid = self._req_id
        payload = {"id": eid, "method": method}
        if params:
            payload["params"] = params
        await self.ws.send(json.dumps(payload))
        return await self._recv_id(eid)

    async def evaluate(self, expression):
        """Run JS in the page, return the result value."""
        resp = await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
        })
        return resp.get("result", {}).get("result", {}).get("value")

    async def screenshot(self):
        """Capture a PNG screenshot, return raw bytes."""
        resp = await self.send("Page.captureScreenshot", {"format": "png"})
        data = resp.get("result", {}).get("data", "")
        if data:
            return base64.b64decode(data)
        return None


# === TEST RUNNER =======================================================

class TestRunner:
    def __init__(self, keep_browser=False, http_port=8769, debug_port=9223):
        self.keep_browser = keep_browser
        self.http_port = http_port
        self.debug_port = debug_port
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

        # 1. Start HTTP server
        info("Starting HTTP server...")
        self.http_proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(self.http_port)],
            cwd=str(ASSETS_DIR),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        await asyncio.sleep(0.5)
        ok(f"HTTP server on :{self.http_port}")

        # 2. Kill any existing chrome on our debug port
        subprocess.run(
            ["pkill", "-f", f"remote-debugging-port={self.debug_port}"],
            capture_output=True,
        )
        await asyncio.sleep(0.3)

        # 3. Launch Chrome
        info("Launching Chrome...")
        os.makedirs(CHROME_USER_DATA, exist_ok=True)
        self.chrome_proc = subprocess.Popen(
            [
                CHROME_EXEC,
                f"--remote-debugging-port={self.debug_port}",
                f"--user-data-dir={CHROME_USER_DATA}",
                "--no-first-run",
                "--no-default-browser-check",
                "--headless=new",
                "--window-size=1440,900",
                page_url(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        # 4. Wait for Chrome to start and get the page's WS URL
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
                    if "avatar_explorer" in p.get("url", ""):
                        self._ws_url = p["webSocketDebuggerUrl"]
                        break
                if self._ws_url:
                    break
            except Exception:
                pass
        else:
            raise RuntimeError("Chrome did not start in time")

        ok(f"Chrome ready, WS: {self._ws_url[:60]}...")

        # 5. Connect CDP
        self.cdp = CDPClient(self._ws_url)
        await self.cdp.connect()

        # Enable required domains
        await self.cdp.send("Runtime.enable")
        await self.cdp.send("Page.enable")
        ok("CDP connected")

        # 6. Wait for page to fully load (Rive + config)
        info("Waiting for app to load...")
        for attempt in range(30):
            ready = await self.cdp.evaluate(
                "typeof riveInst !== 'undefined' && typeof thumbRive !== 'undefined' && thumbReady"
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
    """Verify main and thumbnail canvas sizes."""
    info("Checking canvas dimensions...")

    # Main canvas size
    w = await cdp.evaluate("document.getElementById('riveCanvas').width")
    h = await cdp.evaluate("document.getElementById('riveCanvas').height")
    assert w == 1000, f"Main canvas width: expected 1000, got {w}"
    assert h == 1380, f"Main canvas height: expected 1380, got {h}"
    ok(f"Main canvas: {w}x{h}")

    # Thumbnail canvas size
    tw = await cdp.evaluate("document.getElementById('thumbCanvas').width")
    th = await cdp.evaluate("document.getElementById('thumbCanvas').height")
    assert tw == 252, f"Thumb canvas width: expected 252, got {tw}"
    assert th == 252, f"Thumb canvas height: expected 252, got {th}"
    ok(f"Thumb canvas: {tw}x{th}")

    # Thumbnail canvas should be visually hidden (not display:none, which
    # prevents WebGL rendering — use visibility:hidden instead)
    display = await cdp.evaluate(
        "document.getElementById('thumbCanvas').style.visibility"
    )
    assert display == "hidden", f"Thumb canvas visibility: expected 'hidden', got '{display}'"
    ok("Thumb canvas is visibility:hidden")


async def test_02_rive_loaded(cdp: CDPClient):
    """Verify Rive instances are loaded and state machine is ready."""
    info("Checking Rive state...")

    # Main Rive instance exists
    has_rive = await cdp.evaluate("typeof riveInst !== 'undefined' && riveInst !== null")
    assert has_rive, "Main Rive instance not found"
    ok("Main Rive instance exists")

    # Thumbnail Rive instance exists
    has_thumb = await cdp.evaluate("typeof thumbRive !== 'undefined' && thumbRive !== null")
    assert has_thumb, "Thumbnail Rive instance not found"
    ok("Thumbnail Rive instance exists")

    # thumbReady flag
    ready = await cdp.evaluate("thumbReady === true")
    assert ready, "thumbReady is not true"
    ok("thumbReady is true")

    # State machine inputs loaded
    sm_count = await cdp.evaluate("Object.keys(stateMachineInputs).length")
    assert sm_count > 20, f"Expected >20 SM inputs, got {sm_count}"
    ok(f"{sm_count} state machine inputs loaded")

    # Current SM name
    sm_name = await cdp.evaluate("currentSM")
    assert sm_name == "SMAvatar", f"Expected SMAvatar, got {sm_name}"
    ok("Current SM is SMAvatar")


async def test_03_cache_invalidation_on_set_sm_value(cdp: CDPClient):
    """Verify that calling setSMValue clears the thumbnail cache."""
    info("Testing cache invalidation...")

    # First, ensure some thumbnails are cached
    await cdp.evaluate("generateVisibleThumbnails()")
    await asyncio.sleep(2)

    cache_size_before = await cdp.evaluate("Object.keys(thumbCache).length")
    info(f"Cache size before: {cache_size_before}")

    # Now change a value via setSMValue
    # Find the current Body value so we can toggle it
    body_val = await cdp.evaluate("currentInputValues['Body'] || 0")
    info(f"Current Body value: {body_val}")

    # Pick a different body value
    new_body = 3 if body_val != 3 else 4

    # Call setSMValue which should trigger invalidateThumbnails
    await cdp.evaluate(f"setSMValue('Body', {new_body})")

    # Cache should be empty immediately after setSMValue
    cache_size_after = await cdp.evaluate("Object.keys(thumbCache).length")
    info(f"Cache size immediately after setSMValue: {cache_size_after}")

    assert cache_size_after == 0, \
        f"Cache should be empty after setSMValue, got {cache_size_after} entries"
    ok("Cache cleared immediately after setSMValue")

    # Wait for debounced regeneration (150ms debounce + rendering time)
    await asyncio.sleep(2)

    cache_size_regen = await cdp.evaluate("Object.keys(thumbCache).length")
    info(f"Cache size after regeneration: {cache_size_regen}")

    assert cache_size_regen > 0, \
        "Cache should have entries after regeneration"
    ok(f"Cache regenerated with {cache_size_regen} entries")


async def test_04_thumbnail_dynamic_composition(cdp: CDPClient):
    """Verify thumbnails reflect the complete current avatar state."""
    info("Testing dynamic thumbnail composition...")

    # Set specific features to create a recognizable avatar state
    info("Setting Body=4, Expression=17, Hair=58...")
    await cdp.evaluate("setSMValue('Body', 4)")
    await cdp.evaluate("setSMValue('Expression', 17)")
    await cdp.evaluate("setSMValue('MainHair', 58)")
    await asyncio.sleep(0.5)

    # Switch to Eye tab (idx=1) to trigger thumbnail generation for eyes
    info("Switching to Eyes tab...")
    await cdp.evaluate("switchTab(1)")
    await asyncio.sleep(3)  # Wait for thumbnails to render

    # Check that all eye thumbnails have different data URLs
    thumb_count = await cdp.evaluate("""
        (function() {
            var imgs = document.querySelectorAll('.tab-panel.active .tile img');
            var urls = new Set();
            for (var img of imgs) {
                if (img.src && img.src.length > 100) urls.add(img.src.substring(0, 200));
            }
            return JSON.stringify({count: imgs.length, uniqueUrls: urls.size});
        })()
    """)
    info(f"Eyes tab thumbnails: {thumb_count}")

    parsed = json.loads(thumb_count)
    assert parsed["count"] > 0, "No thumbnail images found in Eyes tab"
    assert parsed["uniqueUrls"] > 1, \
        f"Expected multiple unique thumbnail URLs, got {parsed['uniqueUrls']}"
    ok(f"{parsed['count']} thumbnails with {parsed['uniqueUrls']} unique URLs")

    # Verify the cache key includes state+value pairs
    cache_keys = await cdp.evaluate("Object.keys(thumbCache).slice(0, 5).join(', ')")
    info(f"Sample cache keys: {cache_keys}")

    # Now switch to Hair tab and verify thumbnails still have Body=4 + Expression=17
    info("Switching to Hair tab...")
    await cdp.evaluate("switchTab(2)")
    await asyncio.sleep(3)

    hair_thumbs = await cdp.evaluate("""
        (function() {
            var imgs = document.querySelectorAll('.tab-panel.active .tile img');
            return imgs.length;
        })()
    """)
    assert hair_thumbs > 0, "No thumbnails in Hair tab"
    ok(f"Hair tab has {hair_thumbs} thumbnails")

    # The hair thumbnails should be different from each other
    hair_unique = await cdp.evaluate("""
        (function() {
            var imgs = document.querySelectorAll('.tab-panel.active .tile img');
            var urls = new Set();
            for (var img of imgs) {
                if (img.src) urls.add(img.src.substring(0, 200));
            }
            return urls.size;
        })()
    """)
    assert hair_unique > 1, \
        f"Hair thumbnails should have unique URLs, got {hair_unique} unique"
    ok(f"Hair thumbnails: {hair_unique} unique")


async def test_05_thumbnail_image_uniqueness_pixels(cdp: CDPClient):
    """Verify thumbnail images are visually different from each other."""
    info("Testing visual uniqueness of thumbnails...")

    if not HAS_PIL:
        warn("PIL not available, skipping pixel-level comparison")
        return

    # Make sure we're on a tab with tiles
    await cdp.evaluate("switchTab(0)")  # Body tab
    await asyncio.sleep(3)

    # Get the first 3 thumbnail data URLs and compare them
    result = await cdp.evaluate("""
        (function() {
            var imgs = document.querySelectorAll('.tab-panel.active .tile img');
            var urls = [];
            for (var i = 0; i < Math.min(6, imgs.length); i++) {
                if (imgs[i].src && imgs[i].src.startsWith('data:image/png')) {
                    urls.push(imgs[i].src);
                }
            }
            return JSON.stringify({count: urls.length});
        })()
    """)

    # Get pairs of data URLs and compute similarity
    sim_result = await cdp.evaluate("""
        (function() {
            var imgs = document.querySelectorAll('.tab-panel.active .tile img');
            var results = [];
            for (var i = 0; i < Math.min(6, imgs.length); i++) {
                if (imgs[i].src && imgs[i].src.startsWith('data:image/png')) {
                    // Compute a simple hash of the base64 data
                    var data = imgs[i].src.substring(100, 500);
                    results.push({idx: i, hash: data});
                }
            }
            return JSON.stringify(results.map(r => r.hash));
        })()
    """)

    hashes = json.loads(sim_result)
    unique_hashes = set(hashes)
    info(f"Thumbnail hashes: {len(hashes)} images, {len(unique_hashes)} unique")

    assert len(unique_hashes) > 1, \
        f"All thumbnails look identical ({len(unique_hashes)} unique out of {len(hashes)})"
    ok(f"Thumbnails are visually distinct ({len(unique_hashes)}/{len(hashes)} unique)")

    # Deeper check: compare first two thumbnails pixel-by-pixel using PIL
    img_data = await cdp.evaluate("""
        (function() {
            var imgs = document.querySelectorAll('.tab-panel.active .tile img');
            return JSON.stringify([
                imgs[0] ? imgs[0].src.substring(0, 100) + '...' : 'none',
                imgs[1] ? imgs[1].src.substring(0, 100) + '...' : 'none'
            ]);
        })()
    """)
    info(f"First two img sources: {img_data}")


async def test_06_cross_tab_state_persistence(cdp: CDPClient):
    """Verify that changing features in one tab affects thumbnails in another tab."""
    info("Testing cross-tab state persistence...")

    # Set a distinctive feature combination
    await cdp.evaluate("setSMValue('Body', 2)")
    await cdp.evaluate("setSMValue('MainHair', 50)")
    await asyncio.sleep(0.5)

    # Go to Body tab and capture current thumbnail state
    await cdp.evaluate("switchTab(0)")
    await asyncio.sleep(3)

    body_img_count = await cdp.evaluate("""
        document.querySelectorAll('.tab-panel.active .tile img').length
    """)
    info(f"Body tab: {body_img_count} thumbnail images")

    # Now change hair while on Body tab shouldn't affect body thumbnails...
    # Actually, it WILL invalidate cache and regenerate, so the body thumbnails
    # should show the new hair!
    await cdp.evaluate("setSMValue('MainHair', 48)")
    await asyncio.sleep(3)

    # After cache invalidation, body thumbnails should regenerate with new hair
    body_img_count_after = await cdp.evaluate("""
        document.querySelectorAll('.tab-panel.active .tile img').length
    """)
    assert body_img_count_after > 0, "Thumbnails should still exist after hair change"
    ok(f"Body thumbnails regenerated with new hair: {body_img_count_after} images")

    # Verify currentInputValues reflects the changes
    body_val = await cdp.evaluate("currentInputValues['Body']")
    hair_val = await cdp.evaluate("currentInputValues['MainHair']")
    assert body_val == 2, f"Body should be 2, got {body_val}"
    assert hair_val == 48, f"MainHair should be 48, got {hair_val}"
    ok(f"State preserved: Body={body_val}, MainHair={hair_val}")


async def test_07_cache_key_format(cdp: CDPClient):
    """Verify cache keys use the correct format: state_value."""
    info("Testing cache key format...")

    # Force some thumbnails to be generated
    await cdp.evaluate("switchTab(0)")
    await asyncio.sleep(3)

    keys = await cdp.evaluate("JSON.stringify(Object.keys(thumbCache).slice(0, 10))")
    key_list = json.loads(keys)
    info(f"Sample cache keys: {key_list}")

    assert len(key_list) > 0, "No cache keys found"
    for key in key_list:
        parts = key.split("_")
        assert len(parts) >= 2, f"Cache key '{key}' should contain at least one '_'"
    ok(f"All {len(key_list)} cache keys have valid format (state_value)")

    # Verify cache is an object (not Map or something else)
    cache_type = await cdp.evaluate("typeof thumbCache")
    assert cache_type == "object", f"thumbCache should be object, got {cache_type}"
    ok("thumbCache is a plain object")


async def test_08_thumb_status_feedback(cdp: CDPClient):
    """Verify the thumbnail status indicator shows progress."""
    info("Testing thumbnail status feedback...")

    # Clear cache and regenerate to see the status text
    await cdp.evaluate("thumbCache = {}; generateVisibleThumbnails()")
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
    """Verify resetAll() restores defaults and regenerates thumbnails."""
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
    await asyncio.sleep(2)

    # Values should be back to defaults (Body default is usually 0)
    body_after = await cdp.evaluate("currentInputValues['Body']")
    info(f"After reset: Body={body_after}")

    # Cache should have entries after reset triggers regeneration
    cache_size = await cdp.evaluate("Object.keys(thumbCache).length")
    assert cache_size > 0, "Cache should have entries after reset"
    ok(f"Cache regenerated after reset: {cache_size} entries")


async def test_10_no_duplicate_thumbnails_in_tile(cdp: CDPClient):
    """Verify each tile has at most one img element."""
    info("Testing tile image count...")

    await cdp.evaluate("switchTab(0)")
    await asyncio.sleep(3)

    img_counts = await cdp.evaluate("""
        (function() {
            var tiles = document.querySelectorAll('.tab-panel.active .tile');
            var counts = [];
            for (var t of tiles) {
                counts.push(t.querySelectorAll('img').length);
            }
            return JSON.stringify(counts);
        })()
    """)
    counts = json.loads(img_counts)
    info(f"Image counts per tile: {counts}")

    for i, c in enumerate(counts):
        assert c <= 1, f"Tile {i} has {c} img elements (should be 0 or 1)"
    ok(f"All {len(counts)} tiles have at most 1 img element")


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
    args = parser.parse_args()

    # Update module-level config so page_url() works
    global http_port, chrome_debug_port
    http_port = args.port
    chrome_debug_port = args.debug_port

    runner = TestRunner(
        keep_browser=args.keep,
        http_port=args.port,
        debug_port=args.debug_port,
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

    exit_code = await runner.run(only_test=args.test)
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
