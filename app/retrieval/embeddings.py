"""Gemini dense embeddings and a deterministic lexical sparse vector."""

import hashlib
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from collections import Counter

from qdrant_client import models

from app.config import settings

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _gemini_request(model: str, operation: str, payload: dict) -> dict:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is missing; add it to .env")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:{operation}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": settings.gemini_api_key,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Gemini request failed: {exc}") from exc


def embed_dense(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    """Create a Gemini embedding with the configured Qdrant dimension."""
    result = _gemini_request(
        settings.gemini_embedding_model,
        "embedContent",
        {
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": settings.dense_embedding_dim,
            "taskType": task_type,
        },
    )
    try:
        return list(result["embedding"]["values"])
    except (KeyError, TypeError) as exc:
        raise RuntimeError("Gemini returned an invalid embedding response") from exc


def embed_sparse(text: str) -> models.SparseVector:
    """Create a small BM25-like sparse vector without another model download."""
    counts = Counter(_TOKEN_PATTERN.findall(text.lower()))
    hashed = {
        int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest(), "big"): count
        for token, count in counts.items()
    }
    indices = sorted(hashed)
    values = [1.0 + (count - 1) * 0.25 for _, count in sorted(hashed.items())]
    return models.SparseVector(indices=indices, values=values)


def generate_answer(prompt: str) -> str:
    """Generate an answer from a prompt containing retrieved context."""
    response = _gemini_request(
        settings.gemini_generation_model,
        "generateContent",
        {"contents": [{"parts": [{"text": prompt}]}]},
    )
    try:
        text = response["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Gemini returned an invalid answer response") from exc
    if not text:
        raise RuntimeError("Gemini returned an empty answer")
    return text.strip()
