"""Embedding providers and text renderers for multimodal label retrieval."""

from .providers import (
    EmbeddingProvider,
    EmbeddingProviderSettings,
    FastEmbedEmbeddingProvider,
    HashingNgramEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    create_embedding_provider,
    provider_settings_from_env,
)
from .renderers import (
    render_decision_trace_document,
    render_observation_document,
    render_rule_card_document,
    render_rule_query_text,
    render_sample_memory_document,
    render_sample_query_text,
    render_sample_reason_document,
)

__all__ = [
    "EmbeddingProvider",
    "EmbeddingProviderSettings",
    "FastEmbedEmbeddingProvider",
    "HashingNgramEmbeddingProvider",
    "OpenAICompatibleEmbeddingProvider",
    "SentenceTransformerEmbeddingProvider",
    "create_embedding_provider",
    "provider_settings_from_env",
    "render_decision_trace_document",
    "render_observation_document",
    "render_rule_card_document",
    "render_rule_query_text",
    "render_sample_memory_document",
    "render_sample_query_text",
    "render_sample_reason_document",
]
