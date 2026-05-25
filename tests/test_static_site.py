#!/usr/bin/env python3
"""
Static checks for the GitHub Pages site.

This suite is intended to run in Codespaces and CI without requiring Chrome.
It verifies the static publish shape, local resource references, and inline JS
syntax. Browser rendering remains covered by tests/test_avatar_explorer.py.
"""

import html.parser
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse


PROJECT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_DIR / "assets"
HTML_PATH = ASSETS_DIR / "avatar_explorer.html"

REQUIRED_ASSET_FILES = [
    "avatar_explorer.html",
    "avatar_builder_config.json",
    "avatar_builder_25_sept2025.riv",
    "avatar_builder_body_unselected_dark.svg",
]


class StaticReferenceParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []
        self.inline_scripts = []
        self._in_inline_script = False
        self._script_chunks = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            src = attrs.get("src")
            if src:
                self.refs.append(("script src", src))
                self._in_inline_script = False
            else:
                self._in_inline_script = True
                self._script_chunks = []
        for attr in ("src", "href"):
            value = attrs.get(attr)
            if value:
                self.refs.append((f"{tag} {attr}", value))

    def handle_data(self, data):
        if self._in_inline_script:
            self._script_chunks.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._in_inline_script:
            self.inline_scripts.append("".join(self._script_chunks))
            self._in_inline_script = False
            self._script_chunks = []


def is_local_reference(ref):
    if not ref or ref.startswith("#"):
        return False
    parsed = urlparse(ref)
    if parsed.scheme in ("http", "https", "data", "mailto", "tel"):
        return False
    return True


def normalize_reference(ref):
    parsed = urlparse(ref)
    path = parsed.path
    if path.startswith("/"):
        path = path[1:]
    return path


def read_html():
    assert HTML_PATH.exists(), f"Missing HTML entry: {HTML_PATH}"
    return HTML_PATH.read_text(encoding="utf-8")


def parse_html():
    parser = StaticReferenceParser()
    parser.feed(read_html())
    return parser


def assert_required_assets_exist():
    for rel in REQUIRED_ASSET_FILES:
        path = ASSETS_DIR / rel
        assert path.exists(), f"Required asset missing: {rel}"


def assert_local_references_exist(parser):
    refs = list(parser.refs)
    html = read_html()
    for match in re.finditer(r"fetch\(\s*(['\"])(.*?)\1", html):
        refs.append(("fetch", match.group(2)))

    missing = []
    for source, ref in refs:
        if not is_local_reference(ref):
            continue
        rel = normalize_reference(ref)
        if not rel:
            continue
        if not (ASSETS_DIR / rel).exists():
            missing.append(f"{source}: {ref}")

    assert not missing, "Missing local references:\n" + "\n".join(missing)


def assert_inline_scripts_parse(parser):
    node = shutil.which("node")
    assert node, "node is required for inline script syntax checks"
    code = """
const fs = require('fs');
const scripts = JSON.parse(fs.readFileSync(0, 'utf8'));
for (let i = 0; i < scripts.length; i++) {
  new Function(scripts[i]);
}
console.log(`Parsed ${scripts.length} inline script(s)`);
"""
    result = subprocess.run(
        [node, "-e", code],
        input=json.dumps(parser.inline_scripts),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def assert_pages_publish_shape():
    with tempfile.TemporaryDirectory(prefix="avatar-pages-") as tmp:
        site_dir = Path(tmp) / "_site"
        shutil.copytree(ASSETS_DIR, site_dir)
        shutil.copy2(HTML_PATH, site_dir / "index.html")
        (site_dir / ".nojekyll").touch()

        for rel in ("index.html", "avatar_builder_config.json", "avatar_builder_25_sept2025.riv"):
            assert (site_dir / rel).exists(), f"Pages artifact missing: {rel}"


def main():
    parser = parse_html()
    assert_required_assets_exist()
    assert_local_references_exist(parser)
    assert_inline_scripts_parse(parser)
    assert_pages_publish_shape()
    print("Static site checks passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"Static site check failed: {exc}", file=sys.stderr)
        sys.exit(1)
