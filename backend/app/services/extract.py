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
    """텍스트 뽑기 — 업로드된 파일에서 글자만 추출한다(에이전트가 읽을 수 있게).

    무슨 일을 하나: 허용된 파일 종류(txt/md는 그대로 디코드, pdf는 글자 추출)에서 텍스트를 뽑아
        (추출텍스트, 파일종류)를 돌려준다. 허용 안 된 종류면 400으로 거부. 이 텍스트가 나중에
        에이전트 프롬프트에 통째로 들어간다.
    누가 부르나: 자료 업로드 — upload_context (backend/app/routers/context.py).
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
