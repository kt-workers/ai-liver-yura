from app.bootstrap.emotion_runtime import create_runtime_coordinator

__all__ = [
    "StreamPreparationRuntime",
    "StreamingComposition",
    "compose_streaming",
    "create_runtime_coordinator",
    "create_stream_preparation_runtime",
    "create_streaming_demo_config",
]

_STREAMING_COMPOSITION_EXPORTS = frozenset(
    {"StreamingComposition", "compose_streaming"}
)
_STREAMING_RUNTIME_EXPORTS = frozenset(
    {
        "StreamPreparationRuntime",
        "create_stream_preparation_runtime",
        "create_streaming_demo_config",
    }
)


def __getattr__(name: str) -> object:
    """Keep Core imports independent from the optional Streaming package."""

    if name in _STREAMING_COMPOSITION_EXPORTS:
        module_name = "app.bootstrap.streaming"
    elif name in _STREAMING_RUNTIME_EXPORTS:
        module_name = "app.bootstrap.streaming_runtime"
    else:
        raise AttributeError(name)
    module = __import__(module_name, fromlist=[name])
    return getattr(module, name)
