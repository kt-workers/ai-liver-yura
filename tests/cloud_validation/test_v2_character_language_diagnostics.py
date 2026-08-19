from app.domain.semantic_verification import (
    SemanticVerificationError,
    SemanticVerificationFailureCode,
)
from cloud_validation.v2_character_language_diagnostics import (
    DiagnosticCharacterLanguageLabService,
    semantic_failure_diagnostic,
)
from cloud_validation.v2_character_language_render import _engine


def test_semantic_verification_error_exports_domain_safe_code_and_message() -> None:
    error = SemanticVerificationError(
        SemanticVerificationFailureCode.SCHEMA_INVALID,
        "relation role exchange invalid: schema_invalid",
    )

    value = semantic_failure_diagnostic(error, latency_ms=12.5)

    assert value["error_type"] == "SemanticVerificationError"
    assert value["error_code"] == "schema_invalid"
    assert value["error_message"] == "relation role exchange invalid: schema_invalid"
    assert value["latency_ms"] == 12.5


def test_domain_value_error_exports_bounded_validation_message() -> None:
    value = semantic_failure_diagnostic(ValueError("relation identity mismatch"), latency_ms=1.0)

    assert value["error_type"] == "ValueError"
    assert value["error_code"] is None
    assert value["error_message"] == "relation identity mismatch"


def test_unknown_exception_does_not_export_raw_message() -> None:
    value = semantic_failure_diagnostic(RuntimeError("SECRET_PROVIDER_DETAIL"), latency_ms=2.0)

    assert value["error_type"] == "RuntimeError"
    assert "error_code" not in value
    assert "error_message" not in value
    assert "SECRET_PROVIDER_DETAIL" not in str(value)


def test_render_uses_diagnostic_character_language_engine() -> None:
    assert isinstance(_engine, DiagnosticCharacterLanguageLabService)
