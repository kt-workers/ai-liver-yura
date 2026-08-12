from app.adapters.llm.dummy_response_generator import DummyResponseGenerator
from app.adapters.llm.legacy_character_model_adapter import LegacyCharacterModelAdapter
from app.adapters.llm.ollama_response_generator import OllamaResponseGenerator
from app.adapters.llm.openai_response_generator import (
    OpenAIResponseGenerator as BaseOpenAIResponseGenerator,
)
from app.adapters.llm.openai_structured_response_generator import (
    OpenAIStructuredResponseGenerator,
)
from app.adapters.llm.streaming_demo_response_generator import (
    StreamingDemoResponseGenerator,
)

# Composition Rootは既存名を維持したままStructured capability付きAdapterを受け取る。
# 直接module importする既存テスト/互換コードはBase classをそのまま利用できる。
OpenAIResponseGenerator = OpenAIStructuredResponseGenerator

__all__ = [
    "BaseOpenAIResponseGenerator",
    "DummyResponseGenerator",
    "LegacyCharacterModelAdapter",
    "OllamaResponseGenerator",
    "OpenAIResponseGenerator",
    "OpenAIStructuredResponseGenerator",
    "StreamingDemoResponseGenerator",
]
