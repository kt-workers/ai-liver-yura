"""#340が所有するrenderer非依存のRealtime Body overlay契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from app.adapters.tts.contracts import (
    PreparedAudioArtifact,
    SpeechTimingKind,
    SpeechTimingTrack,
)
from app.domain.contracts.common import require_aware, require_identifier, require_revision
from app.domain.speech_runtime.contracts import (
    SpeechPresentationMode,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)


def _unit(value: float, name: str, *, signed: bool = False) -> float:
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f"{name}は有限値である必要があります")
    lower = -1.0 if signed else 0.0
    if not lower <= value <= 1.0:
        raise ValueError(f"{name}が正規化範囲外です")
    return float(value)


class RealtimeLayer(str, Enum):
    GAZE = "gaze"
    BLINK = "blink"
    BREATH = "breath"
    SPEECH_ARTICULATION = "speech_articulation"
    SUBTLE_MOTION = "subtle_motion"
    POSTURE_ASSIST = "posture_assist"


class RealtimeLayerStatus(str, Enum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    INACTIVE_NO_SOURCE = "inactive_no_source"
    DISABLED_BY_CAPABILITY = "disabled_by_capability"
    FAILED = "failed"


class OverlayMode(str, Enum):
    ADDITIVE_ROTATION = "additive_rotation"
    TARGET_BIAS = "target_bias"


class RealtimeChannel(str, Enum):
    GAZE_X = "gaze_x"
    GAZE_Y = "gaze_y"
    EYELID_OPENNESS = "eyelid_openness"
    MOUTH_OPENNESS = "mouth_openness"
    MOUTH_ROUNDNESS = "mouth_roundness"
    JAW_OPENNESS = "jaw_openness"
    LIP_CLOSURE = "lip_closure"
    BREATH_PHASE = "breath_phase"
    BREATH_AMPLITUDE = "breath_amplitude"
    SUBTLE_SWAY = "subtle_sway"


class BlinkPhase(str, Enum):
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"
    OPENING = "opening"


@dataclass(frozen=True, slots=True)
class RealtimeMotionConstraintView:
    """Activity / physical ownerが確定した#340向けのmotion許可だけを表すView。"""

    source_owner: str
    source_revision: int
    active_plan_id: str | None
    subtle_motion_permitted: bool

    def __post_init__(self) -> None:
        require_identifier(self.source_owner, "source_owner")
        require_revision(self.source_revision, "source_revision")
        if self.active_plan_id is not None:
            require_identifier(self.active_plan_id, "active_plan_id")
        if type(self.subtle_motion_permitted) is not bool:
            raise ValueError("subtle_motion_permittedが不正です")


@dataclass(frozen=True, slots=True)
class BodyGazeTargetView:
    target_ref: str
    horizontal: float | None
    vertical: float | None
    source_attention_revision: int
    source_owner: str
    confidence: float
    observed_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.target_ref, "target_ref")
        require_revision(self.source_attention_revision, "source_attention_revision")
        require_identifier(self.source_owner, "source_owner")
        _unit(self.confidence, "confidence")
        require_aware(self.observed_at, "observed_at")
        if (self.horizontal is None) != (self.vertical is None):
            raise ValueError("spatial gazeは水平・垂直を対で持つ必要があります")
        if self.horizontal is not None:
            assert self.vertical is not None
            object.__setattr__(
                self, "horizontal", _unit(self.horizontal, "horizontal", signed=True)
            )
            object.__setattr__(self, "vertical", _unit(self.vertical, "vertical", signed=True))

    @property
    def has_spatial_target(self) -> bool:
        return self.horizontal is not None


@dataclass(frozen=True, slots=True)
class RealtimeSpeechView:
    """#348 STARTEDと#358 trusted timingをexactにbindした#340入力。"""

    presentation: SpeechPresentationReport
    artifact: PreparedAudioArtifact
    timing_track: SpeechTimingTrack | None
    presentation_monotonic_started_at_s: float

    def __post_init__(self) -> None:
        if not isinstance(self.presentation, SpeechPresentationReport):
            raise ValueError("presentationが不正です")
        if self.presentation.status is not SpeechPresentationReportStatus.STARTED:
            raise ValueError("STARTED以外のPresentationはspeech realtimeを開始できません")
        if self.presentation.started_at is None:
            raise ValueError("STARTED Presentationにはactual start時刻が必要です")
        if (
            type(self.presentation_monotonic_started_at_s) not in (int, float)
            or not isfinite(self.presentation_monotonic_started_at_s)
            or self.presentation_monotonic_started_at_s < 0
        ):
            raise ValueError("presentation_monotonic_started_at_sが不正です")
        object.__setattr__(
            self,
            "presentation_monotonic_started_at_s",
            float(self.presentation_monotonic_started_at_s),
        )
        if SpeechPresentationMode.AUDIO_WITH_TEXT not in self.presentation.output_modes:
            raise ValueError("音声再生なしのPresentationはspeech realtimeを開始できません")
        if not isinstance(self.artifact, PreparedAudioArtifact):
            raise ValueError("artifactが不正です")
        if self.presentation.candidate_id != self.artifact.candidate_id:
            raise ValueError("Presentationとartifactのcandidate identityが一致しません")
        if self.presentation.audio_ref != self.artifact.audio_ref:
            raise ValueError("Presentationとartifactのaudio identityが一致しません")
        if self.timing_track is not None and not isinstance(self.timing_track, SpeechTimingTrack):
            raise ValueError("timing_trackが不正です")
        if (
            self.timing_track is not None
            and self.timing_track.audio_artifact_id != self.artifact.audio_artifact_id
        ):
            raise ValueError("timing trackとartifactのidentityが一致しません")
        if (
            self.timing_track is not None
            and self.presentation.timing_ref != self.timing_track.timing_track_id
        ):
            raise ValueError("Presentationとtiming trackのidentityが一致しません")


@dataclass(frozen=True, slots=True)
class ChannelOverlay:
    overlay_id: str
    layer: RealtimeLayer
    channel: RealtimeChannel
    value: float
    strength: float
    priority: int

    def __post_init__(self) -> None:
        require_identifier(self.overlay_id, "overlay_id")
        if not isinstance(self.layer, RealtimeLayer) or not isinstance(
            self.channel, RealtimeChannel
        ):
            raise ValueError("overlay layer/channelが不正です")
        signed = self.channel in {
            RealtimeChannel.GAZE_X,
            RealtimeChannel.GAZE_Y,
            RealtimeChannel.MOUTH_ROUNDNESS,
            RealtimeChannel.SUBTLE_SWAY,
        }
        object.__setattr__(self, "value", _unit(self.value, "value", signed=signed))
        object.__setattr__(self, "strength", _unit(self.strength, "strength"))
        if type(self.priority) is not int or not 0 <= self.priority <= 100:
            raise ValueError("priorityが不正です")


@dataclass(frozen=True, slots=True)
class RealtimeLayerState:
    layer: RealtimeLayer
    status: RealtimeLayerStatus
    source_ref: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.layer, RealtimeLayer) or not isinstance(
            self.status, RealtimeLayerStatus
        ):
            raise ValueError("layer statusが不正です")
        if self.source_ref is not None:
            require_identifier(self.source_ref, "source_ref")
        if self.detail is not None and (not isinstance(self.detail, str) or len(self.detail) > 256):
            raise ValueError("detailが不正です")


@dataclass(frozen=True, slots=True)
class RealtimeOverlayBundle:
    overlay_bundle_id: str
    based_on_body_state_revision: int
    expression_revision: int | None
    attention_revision: int | None
    speech_presentation_id: str | None
    generated_at: datetime
    actual_interval_ms: float
    jitter_ms: float
    channel_overlays: tuple[ChannelOverlay, ...]
    layer_statuses: tuple[RealtimeLayerState, ...]

    def __post_init__(self) -> None:
        require_identifier(self.overlay_bundle_id, "overlay_bundle_id")
        require_revision(self.based_on_body_state_revision, "based_on_body_state_revision")
        require_revision(self.expression_revision, "expression_revision", optional=True)
        require_revision(self.attention_revision, "attention_revision", optional=True)
        if self.speech_presentation_id is not None:
            require_identifier(self.speech_presentation_id, "speech_presentation_id")
        require_aware(self.generated_at, "generated_at")
        if (
            type(self.actual_interval_ms) not in (int, float)
            or not isfinite(self.actual_interval_ms)
            or self.actual_interval_ms < 0
            or type(self.jitter_ms) not in (int, float)
            or not isfinite(self.jitter_ms)
            or self.jitter_ms < 0
        ):
            raise ValueError("realtime interval telemetryが不正です")
        object.__setattr__(self, "actual_interval_ms", float(self.actual_interval_ms))
        object.__setattr__(self, "jitter_ms", float(self.jitter_ms))
        overlays = tuple(self.channel_overlays)
        states = tuple(self.layer_statuses)
        if any(not isinstance(value, ChannelOverlay) for value in overlays):
            raise ValueError("channel_overlaysが不正です")
        if any(not isinstance(value, RealtimeLayerState) for value in states):
            raise ValueError("layer_statusesが不正です")
        if len({item.layer for item in states}) != len(RealtimeLayer):
            raise ValueError("全realtime layerの状態が必要です")
        object.__setattr__(self, "channel_overlays", overlays)
        object.__setattr__(self, "layer_statuses", states)


def articulation_for(symbol: str, kind: SpeechTimingKind) -> tuple[float, float, float, float]:
    """provider IDではなくcanonical symbol集合をmouth channelへ正規化する。"""
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("timing symbolが不正です")
    if kind is SpeechTimingKind.VISEME:
        mapping = {
            "A": (0.9, 0.0, 0.8, 0.0),
            "I": (0.35, -0.8, 0.3, 0.0),
            "U": (0.35, 0.8, 0.25, 0.0),
            "E": (0.45, -0.45, 0.35, 0.0),
            "O": (0.6, 0.75, 0.5, 0.0),
            "C": (0.2, 0.0, 0.15, 0.0),
            "M": (0.0, 0.0, 0.0, 1.0),
        }
        if symbol in mapping:
            return mapping[symbol]
    if kind is SpeechTimingKind.PHONEME:
        vowel = _canonical_phoneme_viseme_symbol(symbol)
        return articulation_for(vowel, SpeechTimingKind.VISEME)
    if kind is SpeechTimingKind.MORA:
        vowel = _canonical_viseme_symbol(symbol, kind)
        return articulation_for(vowel, SpeechTimingKind.VISEME)
    raise ValueError("未対応timing symbolです")


def _canonical_phoneme_viseme_symbol(symbol: str) -> str:
    """trustedな汎用日本語phonemeを、closed-setのcanonical articulationへ写像する。"""
    mapping = {
        "a": "A",
        "i": "I",
        "u": "U",
        "e": "E",
        "o": "O",
        "m": "M",
        "b": "M",
        "p": "M",
        "N": "M",
        "k": "C",
        "g": "C",
        "s": "C",
        "z": "C",
        "t": "C",
        "d": "C",
        "n": "C",
        "h": "C",
        "f": "C",
        "r": "C",
        "j": "C",
        "w": "C",
        "y": "C",
        "q": "C",
        "ky": "C",
        "gy": "C",
        "sh": "C",
        "ch": "C",
        "ts": "C",
        "dz": "C",
        "ny": "C",
        "hy": "C",
        "by": "C",
        "py": "C",
        "my": "C",
        "ry": "C",
    }
    try:
        return mapping[symbol]
    except KeyError as error:
        raise ValueError("未対応phoneme symbolです") from error


def _canonical_viseme_symbol(symbol: str, kind: SpeechTimingKind) -> str:
    """日本語moraをrendererやproviderに依存しないcanonical visemeへ縮約する。"""
    if kind is SpeechTimingKind.MORA:
        if symbol[-1:] in {"ー", "ｰ"} and len(symbol) > 1:
            return _canonical_viseme_symbol(symbol[:-1], kind)
        kana_vowels = {
            "A": "あかさたなはまやらわがざだばぱぁゃアカサタナハマヤラワガザダバパァャ",
            "I": "いきしちにひみりゐぎじぢびぴぃイキシチニヒミリヰギジヂビピィ",
            "U": "うくすつぬふむゆるぐずづぶぷぅゅゔウクスツヌフムユルグズヅブプゥュヴ",
            "E": "えけせてねへめれゑげぜでべぺぇエケセテネヘメレヱゲゼデベペェ",
            "O": "おこそとのほもよろをごぞどぼぽぉょオコソトノホモヨロヲゴゾドボポォョ",
            "M": "んンっッ",
        }
        last = symbol[-1:]
        for viseme, kana in kana_vowels.items():
            if last in kana:
                return viseme
    return symbol[-1:].upper()
