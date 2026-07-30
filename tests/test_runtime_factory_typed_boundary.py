from __future__ import annotations

from app.runtime import runtime_factory


def test_legacy_runtime_factory_routes_adapter_creation_through_typed_boundary() -> None:
    assert (
        runtime_factory.create_response_generator.__module__
        == "app.bootstrap.typed_runtime_adapters"
    )
    assert (
        runtime_factory.create_llm_role_generator.__module__
        == "app.bootstrap.typed_runtime_adapters"
    )
    assert (
        runtime_factory.create_topic_classifier.__module__
        == "app.bootstrap.typed_runtime_adapters"
    )
    assert (
        runtime_factory.create_embedding_generator.__module__
        == "app.bootstrap.typed_runtime_adapters"
    )
    assert (
        runtime_factory.create_topic_memory_store.__module__
        == "app.bootstrap.typed_runtime_adapters"
    )


def test_streaming_composition_root_is_defined_in_streaming_runtime() -> None:
    assert (
        runtime_factory.StreamPreparationRuntime.__module__
        == "app.bootstrap.streaming_runtime"
    )
    assert (
        runtime_factory.create_stream_preparation_runtime.__module__
        == "app.bootstrap.streaming_runtime"
    )
    assert (
        runtime_factory.create_streaming_demo_config.__module__
        == "app.bootstrap.streaming_runtime"
    )
