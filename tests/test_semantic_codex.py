#!/usr/bin/env python3
"""Unit checks for Codex semantic labeling helpers."""

import json
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

import semantic_codex  # noqa: E402


def write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def valid_label(**overrides):
    value = {
        "schemaVersion": 1,
        "optionId": "FacialHair:1",
        "group": "facial_hair",
        "tags": ["mustache", "short"],
        "extraTags": ["classic_mustache"],
        "confidence": 0.86,
        "needsReview": False,
        "evidence": "The option adds a short mustache above the mouth.",
        "labelSource": "codex_manual",
        "imagePath": ".cache/avatar-semantic/codex/images/FacialHair_1.compare.png",
    }
    value.update(overrides)
    return value


def test_validate_labels_accepts_controlled_codex_label(tmp_path):
    _, enum_by_id = semantic_codex.option_maps()
    input_path = tmp_path / "labels.jsonl"
    write_jsonl(input_path, [valid_label()])

    labels, errors, _ = semantic_codex.validate_labels(
        input_path,
        enum_by_id,
        {
            "FacialHair:1": {
                "optionId": "FacialHair:1",
                "imagePath": ".cache/avatar-semantic/codex/images/FacialHair_1.compare.png",
            }
        },
    )

    assert errors == []
    assert labels[0]["tags"] == ["mustache", "short"]
    assert labels[0]["extraTags"] == ["classic_mustache"]


def test_validate_labels_rejects_tags_outside_controlled_vocabulary(tmp_path):
    _, enum_by_id = semantic_codex.option_maps()
    input_path = tmp_path / "labels.jsonl"
    write_jsonl(input_path, [valid_label(tags=["classic_mustache"])])

    _, errors, _ = semantic_codex.validate_labels(
        input_path,
        enum_by_id,
        {"FacialHair:1": {"optionId": "FacialHair:1"}},
    )

    assert any("outside controlled vocabulary" in error for error in errors)


def test_validate_labels_requires_current_task_scope(tmp_path):
    _, enum_by_id = semantic_codex.option_maps()
    input_path = tmp_path / "labels.jsonl"
    write_jsonl(input_path, [valid_label()])

    _, errors, _ = semantic_codex.validate_labels(input_path, enum_by_id, {})

    assert any("not in the current Codex task package" in error for error in errors)


def main():
    tests = [
        test_validate_labels_accepts_controlled_codex_label,
        test_validate_labels_rejects_tags_outside_controlled_vocabulary,
        test_validate_labels_requires_current_task_scope,
    ]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
    print("Codex semantic helper checks passed")


if __name__ == "__main__":
    main()
