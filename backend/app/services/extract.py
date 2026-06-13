"""Context 파일 텍스트 추출 + 타입 허용리스트(D14).

MVP 허용: txt/md(그대로 디코드), pdf(pdfminer 텍스트 추출). 그 외는 거부.
추출 텍스트는 프롬프트에 풀텍스트로 주입되므로(no RAG) 여기서 한 번만 뽑아 저장한다.
"""

from __future__ import annotations

import io

from fastapi import HTTPException

# 확장자/мime 허용리스트.
TEXT_EXTS = {".txt", ".md", ".markdown"}
PDF_EXTS = {".pdf"}


def _ext(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot >= 0 else ""


def is_allowed(filename: str) -> bool:
    ext = _ext(filename)
    return ext in TEXT_EXTS or ext in PDF_EXTS


def extract(filename: str, data: bytes) -> tuple[str, str]:
    """(extracted_text, mime)를 반환한다. 허용 외 타입은 400.

    txt/md는 utf-8 디코드, pdf는 pdfminer로 텍스트 추출.
    """
    ext = _ext(filename)
    if ext in TEXT_EXTS:
        return data.decode("utf-8", errors="replace"), "text/markdown" if ext != ".txt" else "text/plain"
    if ext in PDF_EXTS:
        from pdfminer.high_level import extract_text

        text = extract_text(io.BytesIO(data)) or ""
        return text, "application/pdf"
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported file type '{ext or filename}'. Allowed: txt, md, pdf.",
    )
