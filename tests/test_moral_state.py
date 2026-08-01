import pytest

from app.domain.morals import MoralProfile, MoralState


def test_default_profile_exposes_ten_value_tendencies() -> None:
    profile = MoralProfile()

    assert set(profile.as_dict()) == {
        "compassion",
        "honesty",
        "fairness",
        "altruism",
        "rule_respect",
        "dominance",
        "competitiveness",
        "jealousy_tendency",
        "possessiveness",
        "malice",
    }
    assert all(0.0 <= value <= 1.0 for value in profile.as_dict().values())


def test_profile_and_state_reject_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="compassion"):
        MoralProfile(compassion=1.1)

    with pytest.raises(ValueError, match="aggressive_impulse"):
        MoralState(aggressive_impulse=-0.1)


def test_state_is_derived_from_profile_and_adjustment_is_clamped() -> None:
    profile = MoralProfile(compassion=1.0, rule_respect=1.0, malice=0.0)
    state = MoralState.from_profile(profile)
    adjusted = state.adjusted(
        restraint=1.0,
        selfish_impulse=-1.0,
        aggressive_impulse=1.0,
    )

    assert state.restraint > 0.5
    assert state.empathy_activation > 0.5
    assert adjusted.restraint == 1.0
    assert adjusted.selfish_impulse == 0.0
    assert adjusted.aggressive_impulse == 1.0


def test_profile_and_state_compose_observable_summary() -> None:
    profile = MoralProfile()
    state = MoralState.from_profile(profile)

    composite = profile.compose(state)

    assert 0.0 <= composite.prosocial_activation <= 1.0
    assert 0.0 <= composite.adversarial_activation <= 1.0
    assert 0.0 <= composite.effective_restraint <= 1.0
    assert composite.prosocial_activation > composite.adversarial_activation
