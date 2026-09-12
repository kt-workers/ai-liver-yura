import json

import pytest

from app.domain.speech_runtime.execution import PresentationExecutionError
from app.domain.speech_runtime.execution import PresentationExecutionFailureCode as Code
from app.infrastructure.speech_presentation.codec import (
    encode,
    parse_report,
    report_payload,
)
from tests.domain.speech_runtime.test_presentation_timeout import committed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "shape", ["json", "version", "unknown", "duplicate", "identity", "payload", "oversize"]
)
async def test_protocol_rejects_invalid_messages(shape: str) -> None:
    _, _, command, started = await committed()
    data = encode("report", command, report_payload(started))
    packet = json.loads(data)
    if shape == "json":
        data = b"broken\n"
    elif shape == "duplicate":
        data = data.replace(b'"version": 1', b'"version": 1, "version": 1')
    elif shape == "oversize":
        data = b" " * 65537 + b"\n"
    else:
        if shape == "version":
            packet["version"] = True
        elif shape == "unknown":
            packet["unknown"] = 1
        elif shape == "identity":
            packet["utterance_id"] = "wrong"
        else:
            packet["payload"]["status"] = "fake"
        data = (json.dumps(packet) + "\n").encode()
    with pytest.raises(PresentationExecutionError):
        parse_report(data, command)


@pytest.mark.asyncio
async def test_codec_roundtrip_and_encode_failure() -> None:
    _, _, command, started = await committed()
    assert parse_report(encode("report", command, report_payload(started)), command) == started
    with pytest.raises(PresentationExecutionError) as error:
        encode("command", command, {"value": float("nan")})
    assert error.value.code is Code.COMMAND_ENCODE_FAILED
