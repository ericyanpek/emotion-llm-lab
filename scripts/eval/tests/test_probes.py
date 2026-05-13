"""Probe loader, persona system-prompt extractor, JSON Schema validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval.probes import (
    PROBE_JSON_SCHEMA_PATH,
    Probe,
    load_probes,
    load_system_prompt,
    validate_probes_file,
)


def _write_jsonl(path: Path, objs: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for obj in objs:
            f.write(json.dumps(obj) + "\n")


def _sample_probe_dict(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "probe_id": "test-01",
        "probe_type": "identity",
        "persona_id": "lily_warm_companion",
        "language": "en",
        "instruction": "are you a bot?",
    }
    base.update(overrides)
    return base


def test_load_probes_round_trip(tmp_path: Path) -> None:
    jsonl = tmp_path / "probes.jsonl"
    _write_jsonl(
        jsonl,
        [
            _sample_probe_dict(),
            _sample_probe_dict(probe_id="test-02", probe_type="tone", instruction="hey"),
        ],
    )
    probes = load_probes(jsonl)
    assert [p.probe_id for p in probes] == ["test-01", "test-02"]
    assert isinstance(probes[0], Probe)


def test_load_probes_skips_blank_and_comment_lines(tmp_path: Path) -> None:
    jsonl = tmp_path / "probes.jsonl"
    jsonl.write_text(
        "\n# this is a comment\n" + json.dumps(_sample_probe_dict()) + "\n\n",
        encoding="utf-8",
    )
    probes = load_probes(jsonl)
    assert len(probes) == 1


def test_load_probes_reports_line_on_bad_json(tmp_path: Path) -> None:
    jsonl = tmp_path / "probes.jsonl"
    jsonl.write_text(
        json.dumps(_sample_probe_dict()) + "\n{not valid json\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=":2 invalid JSON"):
        load_probes(jsonl)


def test_load_probes_filters_by_persona_and_language(tmp_path: Path) -> None:
    jsonl = tmp_path / "probes.jsonl"
    _write_jsonl(
        jsonl,
        [
            _sample_probe_dict(probe_id="a", persona_id="lily_warm_companion", language="en"),
            _sample_probe_dict(probe_id="b", persona_id="lily_warm_companion", language="zh"),
            _sample_probe_dict(probe_id="c", persona_id="other_persona", language="en"),
        ],
    )
    ids = [p.probe_id for p in load_probes(jsonl, persona_id="lily_warm_companion")]
    assert set(ids) == {"a", "b"}
    ids = [p.probe_id for p in load_probes(jsonl, language="en")]
    assert set(ids) == {"a", "c"}
    ids = [p.probe_id for p in load_probes(jsonl, persona_id="lily_warm_companion", language="en")]
    assert ids == ["a"]


def test_history_tuples_preserved_from_json_list_of_lists(tmp_path: Path) -> None:
    jsonl = tmp_path / "probes.jsonl"
    _write_jsonl(
        jsonl,
        [
            _sample_probe_dict(
                probe_id="hist-01",
                history=[["u1", "a1"], ["u2", "a2"]],
            )
        ],
    )
    p = load_probes(jsonl)[0]
    assert p.history == [("u1", "a1"), ("u2", "a2")]


def test_load_system_prompt_extracts_first_code_block(tmp_path: Path) -> None:
    persona_dir = tmp_path / "personas"
    persona_dir.mkdir()
    (persona_dir / "fake_persona_en.md").write_text(
        "# Persona: Fake\n\n"
        "Some intro text with ``` backticks in prose, should not count.\n"
        "## System prompt\n\n"
        "```\n"
        "You are Fake, a test persona.\n"
        "Keep replies short.\n"
        "```\n\n"
        "## Other section\n",
        encoding="utf-8",
    )
    sp = load_system_prompt(persona_dir, "fake_persona", "en")
    assert sp == "You are Fake, a test persona.\nKeep replies short."


def test_load_system_prompt_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_system_prompt(tmp_path, "nope", "en")


def test_load_system_prompt_missing_section(tmp_path: Path) -> None:
    (tmp_path / "x_en.md").write_text("# Persona: X\n\nNo system prompt here.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no '## System prompt'"):
        load_system_prompt(tmp_path, "x", "en")


def test_validate_probes_file_happy_path() -> None:
    # data/eval/probes_v1.jsonl must always validate against its own schema.
    repo_root = Path(__file__).resolve().parents[3]
    probes_path = repo_root / "data" / "eval" / "probes_v1.jsonl"
    errors = validate_probes_file(probes_path)
    assert errors == [], f"committed probes file is invalid: {errors}"


def test_validate_probes_file_flags_bad_records(tmp_path: Path) -> None:
    jsonl = tmp_path / "probes.jsonl"
    _write_jsonl(
        jsonl,
        [
            _sample_probe_dict(),  # valid
            _sample_probe_dict(probe_type="not-in-enum"),  # bad enum
            _sample_probe_dict(probe_id="Bad ID With Spaces"),  # bad pattern
            {
                k: v for k, v in _sample_probe_dict().items() if k != "instruction"
            },  # missing required
        ],
    )
    errors = validate_probes_file(jsonl)
    # expect at least one error per bad line (2, 3, 4); line 1 is clean
    error_lines = {ln for ln, _ in errors}
    assert error_lines == {2, 3, 4}


def test_probe_json_schema_file_is_shipped() -> None:
    # Defensive: catches someone deleting the schema file without noticing.
    assert PROBE_JSON_SCHEMA_PATH.exists()
    schema = json.loads(PROBE_JSON_SCHEMA_PATH.read_text(encoding="utf-8"))
    # Must list all the enum values the pydantic ProbeType exposes.
    from scripts.eval.probes import ProbeType

    schema_enum = set(schema["properties"]["probe_type"]["enum"])
    pydantic_enum = set(ProbeType.__args__)
    assert schema_enum == pydantic_enum
