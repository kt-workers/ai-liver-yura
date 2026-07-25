"""Compatibility imports for Composition Root factories.

New code should import from ``app.bootstrap``.  The compatibility module keeps
legacy import paths stable while routing external Adapter creation through the
typed settings boundary.
"""

from app.bootstrap.emotion_runtime import create_runtime_coordinator
from app.bootstrap.runtime import (
    StreamPreparationRuntime,
    create_audio_player,
    create_character_profile,
    create_memory_summary_generator,
    create_speech_synthesizer,
    create_stream_preparation_runtime,
    create_streaming_demo_config,
)
from app.bootstrap.typed_runtime_adapters import (
    create_embedding_generator,
    create_llm_role_generator,
    create_response_generator,
    create_topic_classifier,
    create_topic_memory_store,
)

__all__ = [
    "StreamPreparationRuntime",
    "create_audio_player",
    "create_character_profile",
    "create_embedding_generator",
    "create_llm_role_generator",
    "create_memory_summary_generator",
    "create_response_generator",
    "create_runtime_coordinator",
    "create_speech_synthesizer",
    "create_stream_preparation_runtime",
    "create_streaming_demo_config",
    "create_topic_classifier",
    "create_topic_memory_store",
]
