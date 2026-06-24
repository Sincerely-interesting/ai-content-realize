"""Pluggable embedding providers for offline-first retrieval."""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Protocol, Sequence

import httpx
import numpy as np


class EmbeddingProvider(Protocol):
    @property
    def name(self) -> str:
        ...

    @property
    def version(self) -> str:
        ...

    @property
    def dim(self) -> int:
        ...

    def embed_text(self, text: str) -> List[float]:
        ...

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        ...


@dataclass(frozen=True)
class EmbeddingProviderSettings:
    provider_name: str = "hash-ngram"
    dim: int = 1536
    model_name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout_sec: float = 30.0
    device: Optional[str] = None
    normalize: bool = True


@dataclass(frozen=True)
class HashingNgramEmbeddingProvider:
    """Deterministic offline embedder based on hashed character n-grams."""

    dim: int = 1536
    char_ngram_min: int = 2
    char_ngram_max: int = 4

    @property
    def name(self) -> str:
        return "hash-ngram"

    @property
    def version(self) -> str:
        return (
            f"{self.name}_v1"
            f"_dim{self.dim}"
            f"_c{self.char_ngram_min}{self.char_ngram_max}"
        )

    def embed_text(self, text: str) -> List[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> List[float]:
        normalized = _normalize_text(text)
        vector = np.zeros(self.dim, dtype=np.float32)
        if not normalized:
            return vector.tolist()

        feature_counts = Counter(self._iter_features(normalized))
        for feature, count in feature_counts.items():
            index, sign = _stable_hash(feature, self.dim)
            vector[index] += sign * np.float32(1.0 + math.log1p(count))

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm
        return vector.astype(np.float32).tolist()

    def _iter_features(self, text: str) -> Sequence[str]:
        features: List[str] = []

        tokens = _tokenize(text)
        for token in tokens:
            features.append(f"tok:{token}")
        for left, right in zip(tokens, tokens[1:]):
            features.append(f"bigram:{left}|{right}")

        compact_text = re.sub(r"\s+", "", text)
        if compact_text:
            for size in range(self.char_ngram_min, self.char_ngram_max + 1):
                if len(compact_text) < size:
                    continue
                for idx in range(0, len(compact_text) - size + 1):
                    features.append(f"char{size}:{compact_text[idx:idx + size]}")

        if not features:
            features.append(f"raw:{text}")
        return features


class SentenceTransformerEmbeddingProvider:
    """Optional local provider backed by sentence-transformers."""

    def __init__(self, settings: EmbeddingProviderSettings):
        if not settings.model_name:
            raise ValueError("sentence-transformers provider requires `model_name`.")
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on local env
            raise RuntimeError(
                "The `sentence-transformers` package is required for the "
                "sentence-transformers embedding provider."
            ) from exc

        self._settings = settings
        self._model = SentenceTransformer(settings.model_name, device=settings.device)

    @property
    def name(self) -> str:
        return "sentence-transformers"

    @property
    def version(self) -> str:
        return f"{self.name}:{self._settings.model_name}"

    @property
    def dim(self) -> int:
        return self._settings.dim

    def embed_text(self, text: str) -> List[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=self._settings.normalize,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        matrix = np.asarray(vectors, dtype=np.float32)
        return _validate_matrix_dim(matrix, self._settings.dim).tolist()


class FastEmbedEmbeddingProvider:
    """Optional local provider backed by fastembed."""

    def __init__(self, settings: EmbeddingProviderSettings):
        if not settings.model_name:
            raise ValueError("fastembed provider requires `model_name`.")
        try:
            from fastembed import TextEmbedding  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on local env
            raise RuntimeError(
                "The `fastembed` package is required for the fastembed provider."
            ) from exc

        self._settings = settings
        self._model = TextEmbedding(
            model_name=settings.model_name,
            cache_dir="data/model_cache",
        )

    @property
    def name(self) -> str:
        return "fastembed"

    @property
    def version(self) -> str:
        return f"{self.name}:{self._settings.model_name}"

    @property
    def dim(self) -> int:
        return self._settings.dim

    def embed_text(self, text: str) -> List[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        vectors = list(self._model.embed(list(texts)))
        matrix = np.asarray(vectors, dtype=np.float32)
        if self._settings.normalize:
            matrix = _normalize_matrix(matrix)
        return _validate_matrix_dim(matrix, self._settings.dim).tolist()


class OpenAICompatibleEmbeddingProvider:
    """Remote provider for OpenAI-compatible embedding endpoints."""

    def __init__(self, settings: EmbeddingProviderSettings):
        if not settings.base_url:
            raise ValueError("openai-compatible provider requires `base_url`.")
        if not settings.model_name:
            raise ValueError("openai-compatible provider requires `model_name`.")

        self._settings = settings
        self._endpoint = settings.base_url.rstrip("/") + "/embeddings"
        headers = {"Content-Type": "application/json"}
        if settings.api_key:
            headers["Authorization"] = f"Bearer {settings.api_key}"
        self._client = httpx.Client(timeout=settings.timeout_sec, headers=headers)

    @property
    def name(self) -> str:
        return "openai-compatible"

    @property
    def version(self) -> str:
        return f"{self.name}:{self._settings.model_name}"

    @property
    def dim(self) -> int:
        return self._settings.dim

    def embed_text(self, text: str) -> List[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        payload: dict[str, Any] = {
            "model": self._settings.model_name,
            "input": list(texts),
        }
        if self._settings.dim:
            payload["dimensions"] = self._settings.dim

        response = self._client.post(self._endpoint, json=payload)
        response.raise_for_status()
        body = response.json()
        data = body.get("data")
        if not isinstance(data, list):
            raise RuntimeError("Embedding response missing `data` array.")
        vectors = [item.get("embedding") for item in data if isinstance(item, Mapping)]
        matrix = np.asarray(vectors, dtype=np.float32)
        if self._settings.normalize:
            matrix = _normalize_matrix(matrix)
        return _validate_matrix_dim(matrix, self._settings.dim).tolist()


def create_embedding_provider(
    settings: EmbeddingProviderSettings | str,
    dim: Optional[int] = None,
    **kwargs: Any,
) -> EmbeddingProvider:
    if isinstance(settings, str):
        settings = EmbeddingProviderSettings(
            provider_name=settings,
            dim=dim or int(kwargs.pop("dim", 1536)),
            model_name=kwargs.pop("model_name", None),
            base_url=kwargs.pop("base_url", None),
            api_key=kwargs.pop("api_key", None),
            timeout_sec=float(kwargs.pop("timeout_sec", 30.0)),
            device=kwargs.pop("device", None),
            normalize=bool(kwargs.pop("normalize", True)),
        )

    normalized = settings.provider_name.strip().lower()
    if normalized in {"hash-ngram", "hash_ngram", "hash"}:
        return HashingNgramEmbeddingProvider(dim=settings.dim)
    if normalized in {"sentence-transformers", "sentence_transformers", "st"}:
        return SentenceTransformerEmbeddingProvider(settings)
    if normalized in {"fastembed", "fast-embed", "fe"}:
        return FastEmbedEmbeddingProvider(settings)
    if normalized in {"openai-compatible", "openai_compatible", "remote-http", "http"}:
        return OpenAICompatibleEmbeddingProvider(settings)
    raise ValueError(
        f"Unsupported embedding provider: {settings.provider_name}. "
        "Available: hash-ngram, sentence-transformers, fastembed, openai-compatible."
    )


def provider_settings_from_env(dim: int) -> EmbeddingProviderSettings:
    return EmbeddingProviderSettings(
        provider_name=os.getenv("MULTIMODAL_EMBEDDING_PROVIDER", "hash-ngram"),
        dim=dim,
        model_name=os.getenv("MULTIMODAL_EMBEDDING_MODEL"),
        base_url=os.getenv("MULTIMODAL_EMBEDDING_BASE_URL"),
        api_key=os.getenv("MULTIMODAL_EMBEDDING_API_KEY"),
        timeout_sec=float(os.getenv("MULTIMODAL_EMBEDDING_TIMEOUT_SEC", "30")),
        device=os.getenv("MULTIMODAL_EMBEDDING_DEVICE"),
        normalize=os.getenv("MULTIMODAL_EMBEDDING_NORMALIZE", "true").lower() != "false",
    )


def _normalize_text(text: str) -> str:
    value = str(text or "").lower().replace("\u3000", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _tokenize(text: str) -> List[str]:
    pattern = re.compile(r"[a-z0-9_./:-]+|[\u4e00-\u9fff]+")
    tokens = pattern.findall(text)
    return tokens or [text]


def _stable_hash(feature: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
    index = int.from_bytes(digest[:8], "big") % dim
    sign = 1.0 if digest[8] % 2 == 0 else -1.0
    return index, sign


def _normalize_matrix(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return matrix / norms


def _validate_matrix_dim(matrix: np.ndarray, expected_dim: int) -> np.ndarray:
    if matrix.ndim != 2:
        raise RuntimeError(f"Expected 2-D embedding matrix, got shape={matrix.shape}")
    if matrix.shape[1] != expected_dim:
        raise RuntimeError(
            f"Embedding dimension mismatch: expected={expected_dim}, got={matrix.shape[1]}"
        )
    return matrix.astype(np.float32)
