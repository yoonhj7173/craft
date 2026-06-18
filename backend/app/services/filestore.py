"""FileStore — 파일 내용 저장/조회 추상화(D27).

MVP는 PostgresFileStore: 내용을 outputs/context_files 행의 content(text) / content_bytes
(bytea) 컬럼에 인라인 저장한다. P1에서 S3FileStore로 교체 시, 내용을 S3에 올리고 행에는
키만 두도록 이 인터페이스 구현만 바꾸면 된다(라우터/서비스는 불변).

행은 content 또는 content_bytes 중 하나만 채운다(CHECK ck_outputs_one_content).
"""

from __future__ import annotations

from typing import Protocol


class HasContent(Protocol):
    content: str | None
    content_bytes: bytes | None
    mime: str
    size_bytes: int


class FileStore(Protocol):
    def put_text(self, row: HasContent, text: str, *, mime: str) -> None: ...
    def put_bytes(self, row: HasContent, data: bytes, *, mime: str) -> None: ...
    def get_text(self, row: HasContent) -> str | None: ...
    def get_bytes(self, row: HasContent) -> bytes: ...


class PostgresFileStore:
    """파일 저장소(현재 구현) — 파일 내용을 DB 행 안에 직접 담아둔다.

    PM 한 줄: '파일을 어디에 둘지'를 한 곳에 가둬, 나중에 S3 같은 클라우드 저장소로 바꿔도
        라우터/서비스 코드는 그대로 두고 이 클래스만 갈아끼우면 되게 만든 설계(=인터페이스 분리).
        지금(MVP)은 간단하게 DB 컬럼에 내용을 인라인 저장한다. 텍스트는 content, 바이너리는 content_bytes.
    누가 쓰나: 컨텍스트 업로드(context.py), 결과물 저장/조회(outputs.py, worker_core.py).
    """

    def put_text(self, row: HasContent, text: str, *, mime: str) -> None:
        row.content = text
        row.content_bytes = None
        row.mime = mime
        row.size_bytes = len(text.encode("utf-8"))

    def put_bytes(self, row: HasContent, data: bytes, *, mime: str) -> None:
        row.content = None
        row.content_bytes = data
        row.mime = mime
        row.size_bytes = len(data)

    def get_text(self, row: HasContent) -> str | None:
        if row.content is not None:
            return row.content
        if row.content_bytes is not None:
            return row.content_bytes.decode("utf-8", errors="replace")
        return None

    def get_bytes(self, row: HasContent) -> bytes:
        if row.content_bytes is not None:
            return row.content_bytes
        if row.content is not None:
            return row.content.encode("utf-8")
        return b""


# 기본 인스턴스(프로세스 공유). P1 교체 지점.
filestore: FileStore = PostgresFileStore()
