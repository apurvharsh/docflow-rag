"""Structure-aware chunking + contextual headers.

Chunks are built from the structure scanner's parsed sections/fields
(not blind token windows), since the scanner already knows document
structure by the time this runs. Each chunk gets a lightweight
contextual header prepended before embedding — the "contextual
retrieval" pattern — since short chunks otherwise lose surrounding
context (project/stage/doc identity) once embedded in isolation.
"""

from dataclasses import dataclass

from app.models.schema import ChunkPayload

MAX_CHUNK_TOKENS = 500
OVERLAP_RATIO = 0.15


@dataclass
class ParsedSection:
    """One section as produced by the structure scanner's field parser."""

    title: str
    text: str
    is_structured_field: bool = False  # True = table row / form field; never split


def build_contextual_header(
    project_name: str, stage: str, doc_type: str, section_title: str
) -> str:
    """Lightweight header prepended to each chunk before embedding.

    Improves retrieval significantly for short/context-free chunks —
    e.g. a chunk reading just "OAuth2 with refresh token rotation"
    means little on its own; the header anchors it to project/stage/doc.
    """
    return f"Project: {project_name} | Stage: {stage} | Doc: {doc_type} | Section: {section_title}"


def chunk_document(
    sections: list[ParsedSection],
    document_id: str,
    project_id: str,
    project_name: str,
    stage: str,
    doc_type: str,
    visible_to_teams: list[str],
    sensitivity_level: int,
) -> list[ChunkPayload]:
    """Turn parsed sections into ChunkPayload objects ready for embedding.

    Structured fields (tables, form fields) are never split mid-field.
    Prose sections longer than MAX_CHUNK_TOKENS get sub-split with overlap.
    """
    chunks: list[ChunkPayload] = []
    chunk_index = 0

    for section in sections:
        header = build_contextual_header(project_name, stage, doc_type, section.title)

        if section.is_structured_field or _estimate_tokens(section.text) <= MAX_CHUNK_TOKENS:
            chunks.append(
                ChunkPayload(
                    document_id=document_id,
                    project_id=project_id,
                    stage=stage,
                    doc_type=doc_type,
                    section_title=section.title,
                    visible_to_teams=visible_to_teams,
                    sensitivity_level=sensitivity_level,
                    chunk_text=f"{header}\n\n{section.text}",
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1
            continue

        for sub_text in _split_with_overlap(section.text, MAX_CHUNK_TOKENS, OVERLAP_RATIO):
            chunks.append(
                ChunkPayload(
                    document_id=document_id,
                    project_id=project_id,
                    stage=stage,
                    doc_type=doc_type,
                    section_title=section.title,
                    visible_to_teams=visible_to_teams,
                    sensitivity_level=sensitivity_level,
                    chunk_text=f"{header}\n\n{sub_text}",
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1

    return chunks


def _estimate_tokens(text: str) -> int:
    # Rough heuristic (~4 chars/token); swap for a real tokenizer if precision matters.
    return len(text) // 4


def _split_with_overlap(text: str, max_tokens: int, overlap_ratio: float) -> list[str]:
    words = text.split()
    max_words = max_tokens * 3  # rough words-per-token heuristic, tune per tokenizer
    overlap_words = int(max_words * overlap_ratio)

    if len(words) <= max_words:
        return [text]

    pieces = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        pieces.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap_words
    return pieces
