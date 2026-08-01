import pytest

from app.domain.desires import DesireState, DesireType, DesireValue


def test_desire_state_has_seven_provisional_baselines() -> None:
    state = DesireState()

    assert state.connection.baseline == pytest.approx(0.45)
    assert state.curiosity.baseline == pytest.approx(0.50)
    assert state.expression.baseline == pytest.approx(0.40)
    assert state.recognition.baseline == pytest.approx(0.30)
    assert state.autonomy.baseline == pytest.approx(0.40)
    assert state.security.baseline == pytest.approx(0.35)
    assert state.achievement.baseline == pytest.approx(0.35)
    assert set(state.effective_values()) == {
        desire_type.value for desire_type in DesireType
    }


def test_desire_value_clamps_all_values_to_0_1_range() -> None:
    value = DesireValue(
        level=1.5,
        baseline=-0.5,
        sensitivity=2.0,
        satisfaction=-1.0,
        frustration=1.2,
    )

    assert value.level == 1.0
    assert value.baseline == 0.0
    assert value.sensitivity == 1.0
    assert value.satisfaction == 0.0
    assert value.frustration == 1.0


def test_effective_level_reflects_satisfaction_and_frustration() -> None:
    value = DesireValue(
        level=0.5,
        baseline=0.5,
        satisfaction=0.2,
        frustration=0.4,
    )

    assert value.effective_level == pytest.approx(0.7)


def test_adjusted_applies_sensitivity() -> None:
    value = DesireValue(
        level=0.4,
        baseline=0.4,
        sensitivity=0.5,
    )

    updated = value.adjusted(
        level_delta=0.2,
        satisfaction_delta=0.1,
        frustration_delta=0.04,
    )

    assert updated.level == pytest.approx(0.5)
    assert updated.satisfaction == pytest.approx(0.05)
    assert updated.frustration == pytest.approx(0.02)


def test_with_value_replaces_only_requested_desire() -> None:
    state = DesireState()
    replacement = DesireValue(level=0.9, baseline=0.5)

    updated = state.with_value(DesireType.CURIOSITY, replacement)

    assert updated.curiosity == replacement
    assert updated.connection == state.connection
    assert updated.expression == state.expression


def test_strongest_desire_name_uses_effective_level() -> None:
    state = DesireState().with_value(
        DesireType.RECOGNITION,
        DesireValue(
            level=0.5,
            baseline=0.3,
            frustration=0.4,
        ),
    )

    assert state.strongest_desire_name() == "recognition"


def test_as_dict_contains_observable_components() -> None:
    state = DesireState()

    snapshot = state.as_dict()

    assert snapshot["connection"] == {
        "level": 0.45,
        "baseline": 0.45,
        "sensitivity": 1.0,
        "satisfaction": 0.0,
        "frustration": 0.0,
        "effective_level": 0.45,
    }
