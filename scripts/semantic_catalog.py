#!/usr/bin/env python3
"""Build and validate the avatar semantic catalog.

The default mode is intentionally offline: it reads avatar_builder_config.json,
generates deterministic taxonomy tags, and writes the semantic catalog plus a
review report. Cloudflare Workers AI is called only when --run is provided.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:  # pragma: no cover - only needed for manual --run capture
    Image = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.cdp import CDPClient  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_DIR / "assets"
CONFIG_PATH = ASSETS_DIR / "avatar_builder_config.json"
OUTPUT_PATH = ASSETS_DIR / "avatar_semantic_catalog.json"
REVIEW_PATH = PROJECT_DIR / "docs" / "agent-steps" / "03.1-semantic-catalog-review.md"
CACHE_DIR = PROJECT_DIR / ".cache" / "avatar-semantic"
SITE_DIR = PROJECT_DIR / "_site"
DEFAULT_MODEL = "@cf/meta/llama-4-scout-17b-16e-instruct"
SEMANTIC_VERSION = 1
DEFAULT_MAX_CALLS = 20
CHROME_CANDIDATES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
]

TAB_LABELS = ["Body", "Eyes", "Hair", "Face", "Beard", "Hat", "Shirt", "BG"]

STATE_GROUPS = {
    "SkinTone": "skin_tone",
    "Body": "body",
    "EyeColor": "eye_color",
    "Expression": "expression",
    "MainHairColor": "main_hair_color",
    "MainHair": "main_hair",
    "GlassesColor": "glasses_color",
    "Glasses": "glasses",
    "Wrinkles": "face_details",
    "Piercings": "piercings",
    "Nose Piercing": "nose_piercing",
    "FacialHairColor": "facial_hair_color",
    "FacialHair": "facial_hair",
    "HeadwearColor": "headwear_color",
    "Headwear": "headwear",
    "ClothingColor": "clothing_color",
    "BackgroundColor": "background_color",
}

COLOR_DEPENDENCIES = {
    "GlassesColor": {"state": "Glasses", "notValue": 0},
    "FacialHairColor": {"state": "FacialHair", "notValue": 0},
    "HeadwearColor": {"state": "Headwear", "notValue": 0},
}

COLOR_PALETTE = {
    "black": (35, 35, 35),
    "gray": (150, 150, 150),
    "white": (240, 240, 240),
    "brown": (105, 65, 40),
    "red": (200, 55, 70),
    "pink": (245, 150, 200),
    "orange": (230, 130, 40),
    "yellow": (235, 200, 65),
    "green": (80, 165, 70),
    "blue": (50, 125, 210),
    "purple": (140, 95, 205),
}


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def parse_color(hex_color: str | None) -> tuple[int, int, int] | None:
    if not hex_color:
        return None
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", hex_color.strip())
    if not match:
        return None
    value = int(match.group(1), 16)
    return ((value >> 16) & 255, (value >> 8) & 255, value & 255)


def luminance(rgb: tuple[int, int, int] | None) -> float:
    if not rgb:
        return 1.0
    r, g, b = rgb
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def nearest_color_name(hex_color: str | None) -> str:
    rgb = parse_color(hex_color)
    if not rgb:
        return "unknown_color"
    return min(
        COLOR_PALETTE,
        key=lambda name: sum((rgb[index] - COLOR_PALETTE[name][index]) ** 2 for index in range(3)),
    )


def add_unique(tags: list[str], *items: str) -> list[str]:
    for item in items:
        if item and item not in tags:
            tags.append(item)
    return tags


def color_tags(state: str, color: str | None) -> list[str]:
    tags: list[str] = ["color", nearest_color_name(color)]
    lum = luminance(parse_color(color))
    if lum < 0.32:
        tags.append("dark")
    elif lum > 0.78:
        tags.append("light")
    else:
        tags.append("medium")
    if color:
        tags.append(color.upper())
    if state in ("ClothingColor", "BackgroundColor"):
        tags.append("neutral" if tags[1] in ("black", "gray", "white", "brown") else "accent")
    return tags


def feature_tags(state: str, value: Any, index: int) -> list[str]:
    tags: list[str] = []
    if state == "Body":
        return ["body", "silhouette", f"body_{value}"]
    if state == "Expression":
        tags = ["expression", f"expression_{value}"]
        if value in (31, 32, 37, 38, 39, 40, 43, 44):
            add_unique(tags, "serious", "stern", "calm")
        elif value in (5, 17, 21, 22, 54, 55):
            add_unique(tags, "smile", "friendly")
        elif value in (8, 9, 10, 11, 12):
            add_unique(tags, "surprised", "playful")
        else:
            add_unique(tags, "neutral")
        return tags
    if state == "MainHair":
        tags = ["hair", "main_hair", f"hair_{value}"]
        if value in (48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60):
            add_unique(tags, "short_hair")
        elif index < 18:
            add_unique(tags, "short_hair", "neat_hair")
        elif index < 42:
            add_unique(tags, "medium_hair")
        else:
            add_unique(tags, "long_hair")
        if value in (1, 2, 3, 4, 5, 6, 13, 14):
            add_unique(tags, "receding_hair")
        return tags
    if state == "Glasses":
        if value == 0:
            return ["none", "no_glasses"]
        tags = ["glasses", f"glasses_{value}"]
        if value in (1, 2):
            add_unique(tags, "round_glasses")
        elif value in (3, 4):
            add_unique(tags, "square_glasses")
        else:
            add_unique(tags, "bold_glasses")
        return tags
    if state == "Wrinkles":
        return ["none", "no_wrinkles"] if value == 0 else ["wrinkles", "older", f"wrinkles_{value}"]
    if state == "Piercings":
        return ["none", "no_earrings"] if value == 0 else ["earrings", "piercing", f"earrings_{value}"]
    if state == "Nose Piercing":
        return ["none", "no_nose_piercing"] if value == 0 else ["nose_piercing", f"nose_piercing_{value}"]
    if state == "FacialHair":
        facial_hair = {
            0: ["none", "no_facial_hair"],
            1: ["mustache", "short", "classic"],
            2: ["goatee", "short"],
            3: ["mustache", "thick"],
            4: ["full_beard", "beard"],
            5: ["full_beard", "rounded_beard"],
            6: ["sideburns", "beard"],
        }
        return ["facial_hair", *facial_hair.get(value, [f"facial_hair_{value}"])]
    if state == "Headwear":
        if value == 0:
            return ["none", "no_headwear"]
        tags = ["headwear", "hat", f"headwear_{value}"]
        if value in (10, 11):
            add_unique(tags, "bowler_like", "brimmed_hat")
        elif value in (7, 8, 9):
            add_unique(tags, "cap")
        elif value in (1, 2, 3):
            add_unique(tags, "brimmed_hat")
        else:
            add_unique(tags, "soft_hat")
        return tags
    return [STATE_GROUPS.get(state, "feature"), f"{state.lower()}_{value}"]


def option_visibility(state: str, value: Any, kind: str) -> tuple[bool, list[dict[str, Any]]]:
    requires = []
    dependency = COLOR_DEPENDENCIES.get(state)
    if dependency:
        requires.append(dependency)
    if kind == "feature" and state in ("Glasses", "FacialHair", "Headwear", "Wrinkles", "Piercings", "Nose Piercing"):
        return value != 0, requires
    return True, requires


def enumerate_options(config: dict[str, Any]) -> list[dict[str, Any]]:
    avatar_config = config["avatarBuilderConfig"]
    tabs = avatar_config.get("stateChooserTabs", [])
    options: list[dict[str, Any]] = []
    for tab_index, tab in enumerate(tabs):
        tab_label = TAB_LABELS[tab_index] if tab_index < len(TAB_LABELS) else tab.get("tabName") or f"Tab {tab_index + 1}"
        for section in tab.get("sections", []):
            section_label = section.get("header") or tab_label
            if section.get("buttonType") == "IMAGE":
                for index, button in enumerate(section.get("imageButtons", [])):
                    options.append(make_option(button, tab_label, section_label, "color", index))
            elif section.get("buttonType") == "FEATURE":
                for index, button in enumerate(section.get("featureButtons", [])):
                    options.append(make_option(button, tab_label, section_label, "feature", index))
    return options


def split_option_ids(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        for item in re.split(r"[\s,]+", value.strip()):
            if item:
                result.append(item)
    return result


def limited_options(options: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    option_ids = set(split_option_ids(getattr(args, "option_id", []) or []))
    sample = getattr(args, "sample", "")
    if sample:
        option_ids.add(sample)
    if option_ids:
        by_id = {option["optionId"]: option for option in options}
        missing = sorted(option_id for option_id in option_ids if option_id not in by_id)
        if missing:
            raise RuntimeError(f"Unknown optionId: {', '.join(missing)}")
        return [by_id[option_id] for option_id in sorted(option_ids)]

    group = getattr(args, "group", "") or ""
    if group:
        options = [option for option in options if option["group"] == group]
    offset = max(0, int(getattr(args, "offset", 0) or 0))
    if offset:
        options = options[offset:]
    if args.limit and args.limit > 0:
        return options[: args.limit]
    return options


def option_report_summary(option: dict[str, Any]) -> dict[str, Any]:
    option_id = option["optionId"]
    result = {
        "optionId": option_id,
        "group": option.get("group"),
        "state": option.get("state"),
        "value": option.get("value"),
        "labelSource": option.get("labelSource"),
        "tags": option.get("tags", []),
        "confidence": option.get("confidence"),
        "needsReview": option.get("needsReview"),
        "visible": option.get("visible"),
        "imagePath": str((CACHE_DIR / "options" / f"{safe_filename(option_id)}.png").relative_to(PROJECT_DIR)),
        "samplePath": str(sample_report_path(option_id).relative_to(PROJECT_DIR)),
    }
    if option.get("evidence"):
        result["evidence"] = option.get("evidence")
    return result


def write_run_report(args: argparse.Namespace, selected: list[dict[str, Any]], processed: int, mode: str, status: str, error: str = "") -> None:
    run_id = os.environ.get("GITHUB_RUN_ID") or str(int(time.time()))
    report = {
        "status": status,
        "mode": mode,
        "model": args.model,
        "selectedCount": len(selected),
        "processedCount": processed,
        "maxCalls": args.max_calls,
        "group": args.group,
        "offset": args.offset,
        "limit": args.limit,
        "all": args.all,
        "optionIds": [option["optionId"] for option in selected],
        "results": [option_report_summary(option) for option in selected],
        "error": error,
    }
    output_path = CACHE_DIR / "runs" / f"semantic_catalog_{run_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_run_preflight(args: argparse.Namespace, selected: list[dict[str, Any]]) -> None:
    errors: list[str] = []
    if not selected:
        raise RuntimeError("No semantic options matched the requested selector.")
    max_calls = int(args.max_calls or DEFAULT_MAX_CALLS)
    if max_calls < 1:
        raise RuntimeError("--max-calls must be at least 1.")
    if len(selected) > max_calls:
        raise RuntimeError(f"Selected {len(selected)} options but --max-calls is {max_calls}. Narrow the selector or raise --max-calls.")
    if not os.environ.get("CLOUDFLARE_ACCOUNT_ID") or not os.environ.get("CLOUDFLARE_API_TOKEN"):
        errors.append("CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are required with --run.")
    if Image is None:
        errors.append("Pillow is required for --run. Install requirements.txt first.")
    if not find_chrome_exec(args.chrome_exec):
        errors.append(
            "Chrome/Chromium is required for --run screenshot capture. "
            "Run the semantic catalog GitHub Action, install Chrome locally, or set CHROME_EXEC."
        )
    if errors:
        raise RuntimeError(" ".join(errors))


def make_option(button: dict[str, Any], tab: str, section: str, kind: str, index: int) -> dict[str, Any]:
    state = button["state"]
    value = button["value"]
    group = STATE_GROUPS.get(state, state.lower().replace(" ", "_"))
    tags = color_tags(state, button.get("color")) if kind == "color" else feature_tags(state, value, index)
    visible, requires = option_visibility(state, value, kind)
    confidence = 1.0 if kind == "color" else 0.78
    needs_review = "unclear" in tags
    return {
        "optionId": f"{state}:{value}",
        "state": state,
        "value": value,
        "tab": tab,
        "section": section,
        "kind": kind,
        "group": group,
        "index": index,
        "color": button.get("color"),
        "tags": tags,
        "confidence": confidence,
        "visible": visible,
        "needsReview": needs_review,
        "requires": requires,
        "statesToOverride": button.get("statesToOverride") or {state: value},
        "labelSource": "deterministic" if kind == "feature" else "config",
    }


def allowed_tags_for_option(option: dict[str, Any]) -> list[str]:
    return {
        "facial_hair": ["none", "mustache", "goatee", "full_beard", "sideburns", "short", "thick", "unclear"],
        "headwear": ["none", "hat", "bowler_like", "brimmed_hat", "cap", "soft_hat", "unclear"],
        "main_hair": ["short_hair", "medium_hair", "long_hair", "receding_hair", "neat_hair", "unclear"],
        "expression": ["serious", "stern", "calm", "smile", "friendly", "surprised", "playful", "neutral", "unclear"],
        "glasses": ["none", "round_glasses", "square_glasses", "bold_glasses", "unclear"],
    }.get(option["group"], ["unclear"])


def build_guided_json(option: dict[str, Any]) -> dict[str, Any]:
    allowed = allowed_tags_for_option(option)
    return {
        "type": "object",
        "properties": {
            "primaryTag": {"type": "string", "enum": allowed},
            "secondaryTags": {
                "type": "array",
                "items": {"type": "string", "enum": allowed},
                "maxItems": 4,
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "string", "maxLength": 180},
        },
        "required": ["primaryTag", "secondaryTags", "confidence", "evidence"],
    }


def build_prompt(option: dict[str, Any]) -> str:
    allowed = allowed_tags_for_option(option)
    return json.dumps({
        "task": "Label one Duolingo-style avatar editor option using only allowedTags. Return JSON only.",
        "group": option["group"],
        "allowedTags": allowed,
        "outputJson": {
            "primaryTag": "one allowed tag",
            "secondaryTags": ["allowed tags"],
            "confidence": "0..1",
            "evidence": "short visual evidence",
        },
    }, ensure_ascii=False)


def compact_json(value: Any, max_chars: int = 4000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...[truncated]"


def unresolved_vision_result(reason: str, body: Any | None = None, text: str = "", detail: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {
        "tags": ["unclear"],
        "confidence": 0,
        "evidence": reason,
        "parseStatus": "failed",
    }
    if text:
        result["rawResponseText"] = text[:4000]
    if body is not None:
        result["rawResponse"] = compact_json(body)
    if detail:
        result["parseError"] = detail
    return result


def extract_response_text(body: Any) -> str:
    result = body.get("result", body) if isinstance(body, dict) else body
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return ""
    for key in ("response", "text", "output_text", "result"):
        value = result.get(key)
        if isinstance(value, str):
            return value
    return ""


def vision_result_from_parsed(parsed: dict[str, Any], option: dict[str, Any], body: Any, raw_response_text: str = "") -> dict[str, Any]:
    tags = [parsed.get("primaryTag"), *parsed.get("secondaryTags", [])]
    allowed = set(allowed_tags_for_option(option))
    raw_tags = [str(tag) for tag in tags if isinstance(tag, str) and tag]
    clean_tags = [tag for tag in raw_tags if tag in allowed]
    discarded_tags = [tag for tag in raw_tags if tag not in allowed]
    if not clean_tags:
        clean_tags = ["unclear"]
    try:
        confidence = float(parsed.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    result = {
        "tags": clean_tags,
        "confidence": max(0, min(1, confidence)),
        "evidence": str(parsed.get("evidence", ""))[:180],
        "rawResponse": compact_json(body),
        "parseStatus": "ok" if "unclear" not in clean_tags else "needs_review",
    }
    if raw_response_text:
        result["rawResponseText"] = raw_response_text[:4000]
    if discarded_tags:
        result["discardedTags"] = discarded_tags
    return result


def call_cloudflare_vision(model: str, image_path: Path, option: dict[str, Any]) -> dict[str, Any]:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not account_id or not token:
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are required with --run")
    image_bytes = image_path.read_bytes()
    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "messages": [
            {"role": "system", "content": "Return compact JSON only."},
            {"role": "user", "content": build_prompt(option)},
        ],
        "image": f"data:image/png;base64,{image_base64}",
        "guided_json": build_guided_json(option),
        "max_tokens": 240,
        "temperature": 0,
    }
    request = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Cloudflare AI request failed: {error.code} {detail}") from error
    if isinstance(body, dict) and body.get("success") is False:
        raise RuntimeError(f"Cloudflare AI request failed: {compact_json(body)}")
    model_result = body.get("result", body) if isinstance(body, dict) else body
    if isinstance(model_result, dict):
        if "primaryTag" in model_result:
            return vision_result_from_parsed(model_result, option, body)
        response_value = model_result.get("response")
        if isinstance(response_value, dict) and "primaryTag" in response_value:
            return vision_result_from_parsed(response_value, option, body)
    text = extract_response_text(body)
    if not text:
        return unresolved_vision_result("vision response missing response text", body=body)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return unresolved_vision_result("vision response did not contain JSON", body=body, text=text)
    raw_response_text = text
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        return unresolved_vision_result(
            "vision response JSON parse failed",
            body=body,
            text=raw_response_text,
            detail=str(error),
        )
    return vision_result_from_parsed(parsed, option, body, raw_response_text)


def sample_report_path(option_id: str) -> Path:
    return CACHE_DIR / "samples" / f"{safe_filename(option_id)}.json"


def write_sample_report(
    option_before: dict[str, Any],
    args: argparse.Namespace,
    default_state: dict[str, Any],
    result: dict[str, Any] | None = None,
    option_after: dict[str, Any] | None = None,
) -> None:
    image_path = CACHE_DIR / "options" / f"{safe_filename(option_before['optionId'])}.png"
    sample: dict[str, Any] = {
        "optionId": option_before["optionId"],
        "cloudflareCalled": bool(args.run),
        "imagePath": str(image_path.relative_to(PROJECT_DIR)),
        "captureState": build_capture_state(option_before, default_state),
        "optionBefore": option_before,
        "visionInput": {
            "model": args.model,
            "prompt": json.loads(build_prompt(option_before)),
        },
    }
    if result is not None:
        sample["visionResult"] = result
    if option_after is not None:
        sample["optionAfter"] = option_after
    output_path = sample_report_path(option_before["optionId"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_resume_annotations(options: list[dict[str, Any]], args: argparse.Namespace) -> None:
    if not args.resume or not OUTPUT_PATH.exists():
        return
    previous = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    previous_by_id = {
        option.get("optionId"): option
        for option in previous.get("options", [])
        if isinstance(option, dict) and option.get("labelSource") == "vision_ai"
    }
    for option in options:
        old = previous_by_id.get(option["optionId"])
        if not old:
            continue
        for key in ("tags", "confidence", "needsReview", "labelSource", "evidence"):
            if key in old:
                option[key] = old[key]


def find_chrome_exec(explicit: str | None = None) -> str | None:
    candidates = [explicit] if explicit else []
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


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_site_build() -> None:
    result = subprocess.run(
        ["npm", "run", "build:site"],
        cwd=PROJECT_DIR,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "Vite build failed")


def wait_for_debug_page(debug_port: int, http_port: int) -> str:
    for _ in range(40):
        time.sleep(0.25)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json", timeout=2) as response:
                pages = json.loads(response.read().decode("utf-8"))
        except Exception:
            continue
        for page in pages:
            if f"127.0.0.1:{http_port}" in page.get("url", "") and page.get("webSocketDebuggerUrl"):
                return page["webSocketDebuggerUrl"]
    raise RuntimeError("Chrome debug page was not ready")


def build_capture_state(option: dict[str, Any], default_state: dict[str, Any]) -> dict[str, Any]:
    state = dict(default_state)
    for requirement in option.get("requires", []):
        if requirement.get("notValue") == 0:
            state[requirement["state"]] = 1
    state[option["state"]] = option["value"]
    overrides = option.get("statesToOverride")
    if isinstance(overrides, dict):
        state.update(overrides)
    return state


def write_png_thumbnail(data_url: str, output_path: Path) -> None:
    if Image is None:
        raise RuntimeError("Pillow is required for --run screenshot capture")
    match = re.match(r"data:image/png;base64,(.+)", data_url or "")
    if not match:
        raise RuntimeError("canvas did not return a PNG data URL")
    image = Image.open(BytesIO(base64.b64decode(match.group(1))))
    image.thumbnail((384, 530), Image.Resampling.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG")


async def capture_screenshots_async(options: list[dict[str, Any]], args: argparse.Namespace, default_state: dict[str, Any]) -> None:
    chrome_exec = find_chrome_exec(args.chrome_exec)
    if not chrome_exec:
        raise RuntimeError("Chrome/Chromium is required for --run screenshot capture")

    http_port = args.port or find_free_port()
    debug_port = args.debug_port or find_free_port()
    run_site_build()
    http_proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(http_port)],
        cwd=SITE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    chrome_proc = subprocess.Popen(
        [
            chrome_exec,
            f"--remote-debugging-port={debug_port}",
            "--remote-debugging-address=127.0.0.1",
            "--user-data-dir=/tmp/avatar-semantic-chrome",
            "--no-first-run",
            "--no-default-browser-check",
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1440,1200",
            f"http://127.0.0.1:{http_port}/index.html",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    cdp: CDPClient | None = None
    try:
        ws_url = wait_for_debug_page(debug_port, http_port)
        cdp = CDPClient(ws_url)
        await cdp.connect()
        await cdp.send("Runtime.enable")
        await cdp.send("Page.enable")
        for _ in range(45):
            ready = await cdp.evaluate(
                "window.__avatarTestHooks?.isReady?.() === true && window.__avatarTestHooks?.isSemanticCatalogReady?.() === true"
            )
            if ready:
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError("Avatar editor did not become ready for screenshot capture")

        for option in options:
            image_path = CACHE_DIR / "options" / f"{safe_filename(option['optionId'])}.png"
            if args.resume and image_path.exists():
                continue
            state = build_capture_state(option, default_state)
            data_url = await cdp.evaluate_async(f"""
                (async function() {{
                    window.__avatarTestHooks.setStatePatch({json.dumps(state)});
                    await new Promise(function(resolve) {{ setTimeout(resolve, 220); }});
                    return document.getElementById('riveCanvas').toDataURL('image/png');
                }})()
            """)
            write_png_thumbnail(data_url, image_path)
    finally:
        if cdp:
            await cdp.close()
        chrome_proc.terminate()
        http_proc.terminate()
        try:
            chrome_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chrome_proc.kill()
        try:
            http_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            http_proc.kill()


def ensure_screenshot_cache(options: list[dict[str, Any]], args: argparse.Namespace, default_state: dict[str, Any]) -> None:
    targets = [
        option
        for option in options
        if not (args.resume and option.get("labelSource") == "vision_ai")
    ]
    missing = [
        option for option in targets
        if not (CACHE_DIR / "options" / f"{safe_filename(option['optionId'])}.png").exists()
        or not args.resume
    ]
    if not missing:
        return
    asyncio.run(capture_screenshots_async(missing, args, default_state))


def maybe_enrich_with_ai(options: list[dict[str, Any]], args: argparse.Namespace, default_state: dict[str, Any]) -> int:
    if not args.run:
        return 0
    processed = 0
    for option in options:
        if args.resume and option.get("labelSource") == "vision_ai":
            continue
        image_path = CACHE_DIR / "options" / f"{safe_filename(option['optionId'])}.png"
        if not image_path.exists():
            continue
        option_before = json.loads(json.dumps(option))
        ai_result = call_cloudflare_vision(args.model, image_path, option)
        processed += 1
        if not ai_result:
            write_sample_report(option_before, args, default_state, None, None)
            continue
        option["tags"] = add_unique([], *ai_result["tags"])
        option["confidence"] = ai_result["confidence"]
        option["needsReview"] = option["confidence"] < 0.65 or "unclear" in option["tags"]
        option["labelSource"] = "vision_ai"
        if ai_result.get("evidence"):
            option["evidence"] = ai_result["evidence"]
        write_sample_report(option_before, args, default_state, ai_result, json.loads(json.dumps(option)))
        time.sleep(0.15)
    return processed


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def build_catalog(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    options = enumerate_options(config)
    avatar_config = config["avatarBuilderConfig"]
    default_state = avatar_config.get("defaultBuiltAvatarState", {})
    apply_resume_annotations(options, args)
    selected = limited_options(options, args)
    if args.run:
        require_run_preflight(args, selected)
        ensure_screenshot_cache(selected, args, default_state)
    processed = maybe_enrich_with_ai(selected, args, default_state)
    catalog = {
        "semanticVersion": SEMANTIC_VERSION,
        "sourceVersion": avatar_config.get("riveFileVersion", ""),
        "generatedAt": "manual-dry-run" if not args.run else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "labeling": {
            "mode": "vision_ai" if args.run else "deterministic_seed",
            "model": args.model,
            "reviewThreshold": 0.65,
        },
        "options": options,
    }
    if args.run:
        write_run_report(args, selected, processed, "catalog", "success")
    return catalog


def run_sample(config: dict[str, Any], args: argparse.Namespace) -> int:
    options = enumerate_options(config)
    selected = limited_options(options, args)
    if len(selected) != 1:
        print("--sample requires exactly one optionId", file=sys.stderr)
        return 2
    option = selected[0]
    option_before = json.loads(json.dumps(option))
    avatar_config = config["avatarBuilderConfig"]
    default_state = avatar_config.get("defaultBuiltAvatarState", {})
    result = None
    option_after = None
    if args.run:
        require_run_preflight(args, selected)
        ensure_screenshot_cache(selected, args, default_state)
        image_path = CACHE_DIR / "options" / f"{safe_filename(option['optionId'])}.png"
        result = call_cloudflare_vision(args.model, image_path, option)
        if result:
            option_after = json.loads(json.dumps(option_before))
            option_after["tags"] = add_unique([], *result["tags"])
            option_after["confidence"] = result["confidence"]
            option_after["needsReview"] = option_after["confidence"] < 0.65 or "unclear" in option_after["tags"]
            option_after["labelSource"] = "vision_ai"
            if result.get("evidence"):
                option_after["evidence"] = result["evidence"]
            selected[0] = option_after
        write_run_report(args, selected, 1, "sample", "success")
    write_sample_report(option_before, args, default_state, result, option_after)
    output_path = sample_report_path(option["optionId"])
    print(f"Wrote {output_path.relative_to(PROJECT_DIR)}")
    if not args.run:
        print("Sample dry-run: Cloudflare AI was not called. Add --run to spend exactly one vision call.")
    return 0


def write_review(catalog: dict[str, Any]) -> None:
    rows = []
    for option in catalog["options"]:
        if option.get("needsReview") or float(option.get("confidence", 0)) < 0.85:
            rows.append(option)
    lines = [
        "# 03.1 Semantic Catalog 复核清单",
        "",
        "本文件由 `npm run semantic:catalog` 生成，用于复核低置信度或需人工确认的选项。",
        "",
        f"- sourceVersion: `{catalog.get('sourceVersion')}`",
        f"- semanticVersion: `{catalog.get('semanticVersion')}`",
        f"- 复核项数量: {len(rows)}",
        "",
        "| optionId | group | tags | confidence | needsReview |",
        "| --- | --- | --- | --- | --- |",
    ]
    for option in rows:
        tags = ", ".join(option.get("tags", []))
        lines.append(
            f"| `{option['optionId']}` | `{option['group']}` | {tags} | "
            f"{option.get('confidence', 0):.2f} | {str(option.get('needsReview', False)).lower()} |"
        )
    REVIEW_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_catalog(catalog: dict[str, Any], config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    avatar_config = config["avatarBuilderConfig"]
    if catalog.get("semanticVersion") != SEMANTIC_VERSION:
        errors.append("semanticVersion mismatch")
    if catalog.get("sourceVersion") != avatar_config.get("riveFileVersion", ""):
        errors.append("sourceVersion mismatch")
    options = catalog.get("options")
    if not isinstance(options, list) or not options:
        errors.append("options must be a non-empty array")
        return errors
    required = {"optionId", "state", "value", "group", "tags", "confidence", "visible", "needsReview"}
    seen = set()
    for index, option in enumerate(options):
        if not isinstance(option, dict):
            errors.append(f"option {index} is not an object")
            continue
        missing = required.difference(option)
        if missing:
            errors.append(f"{option.get('optionId', index)} missing {sorted(missing)}")
        option_id = option.get("optionId")
        if option_id in seen:
            errors.append(f"duplicate optionId {option_id}")
        seen.add(option_id)
        if not isinstance(option.get("tags"), list) or not option.get("tags"):
            errors.append(f"{option_id} tags must be non-empty")
        confidence = option.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            errors.append(f"{option_id} confidence out of range")
    return errors


def run_check() -> int:
    config = load_config()
    if not OUTPUT_PATH.exists():
        print(f"Missing {OUTPUT_PATH.relative_to(PROJECT_DIR)}", file=sys.stderr)
        return 1
    catalog = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    errors = validate_catalog(catalog, config)
    if errors:
        for error in errors:
            print(f"semantic catalog error: {error}", file=sys.stderr)
        return 1
    print(f"Semantic catalog OK: {len(catalog['options'])} options")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build avatar semantic catalog")
    parser.add_argument("--run", action="store_true", help="Call Cloudflare Workers AI for available cached screenshots")
    parser.add_argument("--all", action="store_true", help="Allow --run to process every option")
    parser.add_argument("--limit", type=int, default=0, help="Limit AI-enriched options")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many matched options before applying --limit")
    parser.add_argument("--group", default="", help="Only process options from this semantic group")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS, help="Maximum Cloudflare vision calls allowed")
    parser.add_argument("--option-id", action="append", default=[], help="Only process this optionId; repeatable")
    parser.add_argument("--sample", default="", help="Write one sample input/output report for this optionId")
    parser.add_argument("--resume", action="store_true", help="Reuse existing screenshots and vision labels where possible")
    parser.add_argument("--model", default=os.environ.get("AI_VISION_MODEL", DEFAULT_MODEL))
    parser.add_argument("--chrome-exec", default=None, help="Chrome/Chromium executable for --run screenshot capture")
    parser.add_argument("--port", type=int, default=0, help="HTTP port for --run screenshot capture")
    parser.add_argument("--debug-port", type=int, default=0, help="Chrome debug port for --run screenshot capture")
    parser.add_argument("--check", action="store_true", help="Validate the committed catalog")
    args = parser.parse_args()

    if args.check:
        return run_check()

    config = load_config()
    if args.run and not (args.all or args.limit > 0 or args.option_id or args.sample or args.group):
        print("Refusing unbounded --run. Use --sample OPTION_ID, --limit N, --group GROUP, --option-id OPTION_ID, or --all.", file=sys.stderr)
        return 2
    try:
        if args.sample:
            return run_sample(config, args)
        catalog = build_catalog(config, args)
    except RuntimeError as error:
        print(f"semantic catalog error: {error}", file=sys.stderr)
        return 2

    errors = validate_catalog(catalog, config)
    if errors:
        for error in errors:
            print(f"semantic catalog error: {error}", file=sys.stderr)
        return 1

    OUTPUT_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_review(catalog)
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_DIR)}")
    print(f"Wrote {REVIEW_PATH.relative_to(PROJECT_DIR)}")
    if not args.run:
        print("Dry-run mode: Cloudflare AI was not called. Use --run to enrich cached screenshots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
