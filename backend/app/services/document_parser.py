from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pdfplumber
from docx import Document as DocxDocument

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 120


@dataclass
class DocumentParagraph:
    file_name: str
    document_topic: str
    paragraph_index: int
    parsed_at_iso: str
    file_modified_at_iso: str | None
    source_path: str
    page_number: int | None
    start_offset: int | None
    end_offset: int | None
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _clean_segments(segments: Iterable[str]) -> list[str]:
    return [segment.strip() for segment in segments if segment and segment.strip()]


def _split_text_chunks(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[tuple[str, int, int]]:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [(normalized, 0, len(normalized))]

    chunks: list[tuple[str, int, int]] = []
    start = 0
    punctuation = ["。", "；", ";", ".", "!", "?", "！", "？", "\n"]
    while start < len(normalized):
        hard_end = min(len(normalized), start + chunk_size)
        end = hard_end
        if hard_end < len(normalized):
            window = normalized[start:hard_end]
            best_break = max(window.rfind(mark) for mark in punctuation)
            if best_break >= int(chunk_size * 0.55):
                end = start + best_break + 1
        piece = normalized[start:end].strip()
        if piece:
            chunks.append((piece, start, end))
        if end >= len(normalized):
            break
        next_start = max(0, end - chunk_overlap)
        if next_start <= start:
            next_start = end
        start = next_start
    return chunks


def _build_document_chunks(
    *,
    file_name: str,
    document_topic: str,
    source_path: Path,
    segments: list[tuple[int | None, str]],
) -> list[DocumentParagraph]:
    parsed_at = _utc_now_iso()
    modified_at = _file_mtime(source_path)
    paragraphs: list[DocumentParagraph] = []
    chunk_index = 1
    assembled_offset = 0
    buffer_parts: list[str] = []
    buffer_page: int | None = None
    buffer_start = 0

    def flush_buffer() -> None:
        nonlocal buffer_parts, buffer_page, buffer_start, chunk_index
        if not buffer_parts:
            return
        combined = "\n\n".join(buffer_parts)
        for piece, rel_start, rel_end in _split_text_chunks(combined):
            paragraphs.append(
                DocumentParagraph(
                    file_name=file_name,
                    document_topic=document_topic,
                    paragraph_index=chunk_index,
                    parsed_at_iso=parsed_at,
                    file_modified_at_iso=modified_at,
                    source_path=str(source_path),
                    page_number=buffer_page,
                    start_offset=buffer_start + rel_start,
                    end_offset=buffer_start + rel_end,
                    text=piece,
                )
            )
            chunk_index += 1
        buffer_parts = []
        buffer_page = None

    for page_number, raw_text in segments:
        text = raw_text.strip()
        if not text:
            continue
        if not buffer_parts:
            buffer_start = assembled_offset
            buffer_page = page_number
        projected = len("\n\n".join([*buffer_parts, text])) if buffer_parts else len(text)
        if buffer_parts and projected > DEFAULT_CHUNK_SIZE:
            flush_buffer()
            buffer_start = assembled_offset
            buffer_page = page_number
        if len(text) > DEFAULT_CHUNK_SIZE:
            flush_buffer()
            for piece, rel_start, rel_end in _split_text_chunks(text):
                paragraphs.append(
                    DocumentParagraph(
                        file_name=file_name,
                        document_topic=document_topic,
                        paragraph_index=chunk_index,
                        parsed_at_iso=parsed_at,
                        file_modified_at_iso=modified_at,
                        source_path=str(source_path),
                        page_number=page_number,
                        start_offset=assembled_offset + rel_start,
                        end_offset=assembled_offset + rel_end,
                        text=piece,
                    )
                )
                chunk_index += 1
        else:
            buffer_parts.append(text)
        assembled_offset += len(text) + 2

    flush_buffer()
    return paragraphs


def parse_txt(path: Path) -> list[DocumentParagraph]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="ignore")

    pieces = _clean_segments(text.split("\n\n"))
    if len(pieces) <= 1:
        pieces = _clean_segments(text.splitlines())

    topic = path.stem
    return _build_document_chunks(
        file_name=path.name,
        document_topic=topic,
        source_path=path,
        segments=[(None, piece) for piece in pieces],
    )


def parse_docx(path: Path) -> list[DocumentParagraph]:
    doc = DocxDocument(str(path))
    title = (doc.core_properties.title or "").strip() or path.stem
    pieces = _clean_segments(paragraph.text for paragraph in doc.paragraphs)
    return _build_document_chunks(
        file_name=path.name,
        document_topic=title,
        source_path=path,
        segments=[(None, piece) for piece in pieces],
    )


def parse_pdf(path: Path) -> list[DocumentParagraph]:
    topic = path.stem
    segments: list[tuple[int | None, str]] = []
    with pdfplumber.open(str(path)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            pieces = _clean_segments(page_text.split("\n\n"))
            if len(pieces) <= 1:
                pieces = _clean_segments(page_text.splitlines())
            for piece in pieces:
                segments.append((page_number, piece))
    return _build_document_chunks(
        file_name=path.name,
        document_topic=topic,
        source_path=path,
        segments=segments,
    )


def parse_document(path: Path) -> list[DocumentParagraph]:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return parse_txt(path)
    if suffix == ".docx":
        return parse_docx(path)
    if suffix == ".pdf":
        return parse_pdf(path)
    raise ValueError(f"Unsupported file type: {suffix}")
