"""Domain DTOとversion付きJSONLを変換し、message identityを閉じて検証する。"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from app.domain.speech_runtime.contracts import (
    SpeechPresentationCommand,
    SpeechPresentationMode,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)
from app.domain.speech_runtime.execution import (
    PresentationExecutionError,
)
from app.domain.speech_runtime.execution import (
    PresentationExecutionFailureCode as Code,
)

MAX_MESSAGE_BYTES = 65536
SCHEMA = "yura.speech-presentation"


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("重複keyです")
        result[key] = value
    return result


def encode(kind: str, command: SpeechPresentationCommand, payload: object) -> bytes:
    try:
        packet = dict(
            schema=SCHEMA,
            version=1,
            kind=kind,
            utterance_id=command.utterance_id,
            correlation_id=command.presentation_id,
            payload=payload,
        )
        data = (json.dumps(packet, ensure_ascii=False, allow_nan=False) + "\n").encode()
        if len(data) > MAX_MESSAGE_BYTES:
            raise ValueError("message上限を超えています")
        return data
    except (ValueError, TypeError, OverflowError):
        raise PresentationExecutionError(Code.COMMAND_ENCODE_FAILED) from None


def decode(
    data: bytes, kind: str, command: SpeechPresentationCommand | None = None
) -> dict[str, Any]:
    try:
        if len(data) > MAX_MESSAGE_BYTES or not data.endswith(b"\n"):
            raise ValueError("message framingが不正です")
        packet = json.loads(
            data,
            object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(packet, dict) or set(packet) != {
            "schema",
            "version",
            "kind",
            "utterance_id",
            "correlation_id",
            "payload",
        }:
            raise ValueError("envelopeが不正です")
        if (
            packet["schema"] != SCHEMA
            or type(packet["version"]) is not int
            or packet["version"] != 1
            or packet["kind"] != kind
        ):
            raise ValueError("protocolが不正です")
        if command is not None and (
            packet["utterance_id"] != command.utterance_id
            or packet["correlation_id"] != command.presentation_id
        ):
            raise PresentationExecutionError(Code.IDENTITY_MISMATCH)
        if not isinstance(packet["payload"], dict):
            raise ValueError("payloadが不正です")
        return packet
    except PresentationExecutionError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise PresentationExecutionError(Code.PROTOCOL_INVALID) from None


def command_payload(command: SpeechPresentationCommand) -> dict[str, Any]:
    result = asdict(command)
    result["committed_at"] = command.committed_at.isoformat()
    return result


def parse_command(raw: dict[str, Any]) -> SpeechPresentationCommand:
    value = dict(raw)
    value["committed_at"] = datetime.fromisoformat(value["committed_at"])
    value["modes"] = tuple(SpeechPresentationMode(x) for x in value["modes"])
    return SpeechPresentationCommand(**value)


def report_payload(report: SpeechPresentationReport) -> dict[str, Any]:
    result = asdict(report)
    for name in ("started_at", "completed_at"):
        value = getattr(report, name)
        result[name] = None if value is None else value.isoformat()
    return result


def parse_report(data: bytes, command: SpeechPresentationCommand) -> SpeechPresentationReport:
    try:
        raw = decode(data, "report", command)["payload"]
        for name in ("started_at", "completed_at"):
            if raw[name] is not None:
                raw[name] = datetime.fromisoformat(raw[name])
        raw["status"] = SpeechPresentationReportStatus(raw["status"])
        raw["output_modes"] = tuple(SpeechPresentationMode(x) for x in raw["output_modes"])
        report = SpeechPresentationReport(**raw)
        if (
            report.presentation_id != command.presentation_id
            or report.candidate_id != command.candidate_id
        ):
            raise PresentationExecutionError(Code.IDENTITY_MISMATCH)
        return report
    except PresentationExecutionError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError):
        raise PresentationExecutionError(Code.PROTOCOL_INVALID) from None
