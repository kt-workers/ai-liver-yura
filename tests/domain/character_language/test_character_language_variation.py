from dataclasses import replace
from datetime import timedelta
from typing import cast

import pytest

from app.domain.character_language import (
    CharacterLanguageAuthority,
    CharacterLanguagePriorConstraintRevision,
    CharacterLanguagePriorRealizationView,
    build_request,
    character_language_instructions,
    prior_realization_from_utterance,
)
from app.domain.contracts.common import thaw_json
from tests.domain.character_language.test_character_language import (
    NOW,
    candidate,
    constraints,
    context,
    current,
    policy,
)


def prior_view(
    index: int,
    *,
    text: str | None = None,
) -> CharacterLanguagePriorRealizationView:
    snapshot = context()
    return CharacterLanguagePriorRealizationView(
        f"utterance-{index}",
        snapshot.semantic_plan.plan_id,
        snapshot.character_profile.character_id,
        snapshot.character_profile.schema_version,
        snapshot.character_profile.definition_revision,
        tuple(
            CharacterLanguagePriorConstraintRevision(
                item.constraint_id,
                item.source_revision,
            )
            for item in snapshot.constraints
        ),
        text or f"表現{index}",
        NOW,
    )


def test_bounded_prior_realizations_project_style_only_input_v2() -> None:
    snapshot = replace(
        context(),
        prior_realizations=(
            prior_view(1, text="もちろん、一緒に進めよう。"),
            prior_view(2, text="うん、一緒にやっていこう。"),
        ),
    )

    request = build_request(snapshot, created_at=NOW, policy=policy())
    payload = cast(dict[str, object], thaw_json(request.input.value))
    prior = cast(list[dict[str, object]], payload["prior_realizations"])

    assert request.input.schema_id == "character.language.context.v2"
    assert prior == [
        {
            "source_utterance_id": "utterance-1",
            "text": "もちろん、一緒に進めよう。",
            "committed_at": NOW.isoformat(),
        },
        {
            "source_utterance_id": "utterance-2",
            "text": "うん、一緒にやっていこう。",
            "committed_at": NOW.isoformat(),
        },
    ]
    assert "semantic_plan_id" not in prior[0]
    assert "constraint_revisions" not in prior[0]
    assert "history" not in payload


def test_committed_utterance_builder_preserves_style_only_provenance() -> None:
    source_snapshot = context()
    utterance = CharacterLanguageAuthority().commit(
        candidate(source_snapshot, text="もちろん、一緒に進めよう。"),
        source_snapshot,
        current=current(source_snapshot),
        utterance_id="utterance-source",
        committed_at=NOW + timedelta(seconds=2),
    )
    prior = prior_realization_from_utterance(utterance, source_snapshot.constraints)
    next_snapshot = replace(
        source_snapshot,
        request_id="request-next",
        captured_at=NOW + timedelta(seconds=3),
        prior_realizations=(prior,),
    )

    payload = next_snapshot.to_dict()
    assert payload["prior_realizations"] == [
        {
            "source_utterance_id": "utterance-source",
            "text": "もちろん、一緒に進めよう。",
            "committed_at": (NOW + timedelta(seconds=2)).isoformat(),
        }
    ]


def test_prior_realizations_reject_more_than_three() -> None:
    with pytest.raises(ValueError, match="最大3件"):
        replace(
            context(),
            prior_realizations=tuple(prior_view(index) for index in range(1, 5)),
        )


def test_prior_realizations_reject_duplicate_identity_and_text() -> None:
    with pytest.raises(ValueError, match="source_utterance_id"):
        replace(
            context(),
            prior_realizations=(prior_view(1), prior_view(1, text="別表現")),
        )
    with pytest.raises(ValueError, match="text"):
        replace(
            context(),
            prior_realizations=(prior_view(1, text="同じ"), prior_view(2, text="同じ")),
        )


def test_prior_realizations_require_same_plan_character_and_constraints() -> None:
    base = prior_view(1)
    with pytest.raises(ValueError, match="同一Plan"):
        replace(context(), prior_realizations=(replace(base, semantic_plan_id="other-plan"),))
    with pytest.raises(ValueError, match="Character provenance"):
        replace(
            context(),
            prior_realizations=(replace(base, character_definition_revision=999),),
        )
    wrong_constraints = tuple(
        CharacterLanguagePriorConstraintRevision(item.constraint_id, item.source_revision + 1)
        for item in constraints()
    )
    with pytest.raises(ValueError, match="constraint provenance"):
        replace(
            context(),
            prior_realizations=(replace(base, constraint_revisions=wrong_constraints),),
        )


def test_prior_realizations_reject_future_commit() -> None:
    with pytest.raises(ValueError, match="未来"):
        replace(
            context(),
            prior_realizations=(replace(prior_view(1), committed_at=NOW + timedelta(seconds=1)),),
        )


def test_production_instructions_keep_prior_realizations_style_only() -> None:
    instructions = character_language_instructions()

    assert "prior_realizations" in instructions
    assert "How-to-say上のnegative reference" in instructions
    assert "Fact source、会話履歴、追加propositionとして扱ってはいけません" in instructions
    assert "actual meaningはcurrent semantic_planだけから" in instructions
    assert "不自然な同義語置換" in instructions
