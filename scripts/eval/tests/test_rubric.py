"""Rubric math — weighted mean and config validation.

These numbers will silently be wrong if the rubric's internals change (e.g.
a dimension renames, a weight key typo'd). Unit tests pin the contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.eval.rubric import (
    ALL_DIMENSIONS,
    PROBE_PRIMARY_DIMENSIONS,
    Rubric,
    load_rubric,
)


def test_all_dimensions_order_is_stable() -> None:
    # Report aggregation iterates ALL_DIMENSIONS — reordering silently changes
    # the column order of the Markdown report.
    assert ALL_DIMENSIONS == ("voice", "emotional_register", "identity", "boundaries")


def test_probe_primary_dimensions_cover_dpo_schema_enum() -> None:
    # The drift_probe enum from schemas/dpo_alpaca.schema.json must all have
    # primary-dimension mappings; otherwise hard-reject penalties silently
    # default to `voice` for an unmapped probe type.
    from scripts.eval.probes import ProbeType  # Literal alias

    dpo_enum = set(ProbeType.__args__)
    mapped = set(PROBE_PRIMARY_DIMENSIONS.keys())
    assert dpo_enum == mapped, f"unmapped probe types: {dpo_enum - mapped}"


def test_default_rubric_weights_uniform_and_score_averages() -> None:
    r = Rubric()
    # Uniform default: weighted mean equals arithmetic mean.
    assert r.weighted_score({d: 4.0 for d in ALL_DIMENSIONS}) == pytest.approx(4.0)
    assert r.weighted_score(
        {"voice": 5, "emotional_register": 3, "identity": 5, "boundaries": 3}
    ) == pytest.approx(4.0)


def test_custom_weights_shift_score() -> None:
    r = Rubric(
        weights={"voice": 4.0, "emotional_register": 1.0, "identity": 1.0, "boundaries": 1.0}
    )
    # voice=5, others=3 -> (4*5 + 1*3 + 1*3 + 1*3) / 7 = 29/7 ≈ 4.142857
    s = r.weighted_score({"voice": 5, "emotional_register": 3, "identity": 3, "boundaries": 3})
    assert s == pytest.approx(29 / 7)


def test_weights_must_cover_all_dimensions() -> None:
    with pytest.raises(ValueError, match="missing dimensions"):
        Rubric(weights={"voice": 1.0})  # type: ignore[arg-type]


def test_weights_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        Rubric(
            weights={"voice": 0.0, "emotional_register": 1.0, "identity": 1.0, "boundaries": 1.0}
        )


def test_missing_per_dim_scores_contribute_zero() -> None:
    # If the judge somehow omits a dimension (shouldn't happen — parser fills
    # defaults — but defense in depth), weighted_score treats it as 0. This
    # test pins that behavior so a silent contract change is caught.
    r = Rubric()
    assert r.weighted_score({"voice": 4, "emotional_register": 4, "identity": 4}) == pytest.approx(
        3.0
    )


def test_load_rubric_from_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / "rubric.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "version": "v2",
                "weights": {
                    "voice": 2.0,
                    "emotional_register": 1.0,
                    "identity": 2.0,
                    "boundaries": 1.0,
                },
                "hard_reject_penalty": 3.5,
            }
        ),
        encoding="utf-8",
    )
    r = load_rubric(cfg)
    assert r.version == "v2"
    assert r.hard_reject_penalty == 3.5
    assert r.weights["voice"] == 2.0


def test_load_rubric_none_returns_defaults() -> None:
    r = load_rubric(None)
    assert r.version == "v1"
    assert r.hard_reject_penalty == 2.0
    assert all(r.weights[d] == 1.0 for d in ALL_DIMENSIONS)
