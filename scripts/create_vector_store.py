"""Create and populate the SafeMate OpenAI vector store from approved documents."""

from __future__ import annotations

import os
from contextlib import ExitStack
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = PROJECT_ROOT / "data" / "knowledge_base"
SUPPORTED_EXTENSIONS = {
    ".docx",
    ".html",
    ".json",
    ".md",
    ".pdf",
    ".pptx",
    ".txt",
}


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    existing_store_id = (os.getenv("OPENAI_VECTOR_STORE_ID") or "").strip()
    if existing_store_id:
        raise SystemExit(
            "OPENAI_VECTOR_STORE_ID가 이미 설정되어 있습니다: "
            f"{existing_store_id}\n새 저장소가 필요할 때만 기존 값을 비운 뒤 실행하세요."
        )

    file_paths = sorted(
        path
        for path in KNOWLEDGE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if file_paths:
        print("업로드 대상:")
        for path in file_paths:
            print(f"- {path.name}")
    else:
        print("검수된 보안 문서가 없어 빈 Vector Store를 생성합니다.")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    vector_store = client.vector_stores.create(
        name="SafeMate Official Security Knowledge Base",
        description="SafeMate 후속 보안 상담에 사용하는 검수된 공식 자료",
    )

    batch = None
    if file_paths:
        with ExitStack() as stack:
            files = [stack.enter_context(path.open("rb")) for path in file_paths]
            batch = client.vector_stores.file_batches.upload_and_poll(
                vector_store_id=vector_store.id,
                files=files,
            )

    print(f"VECTOR_STORE_ID={vector_store.id}")
    if batch is None:
        print("UPLOAD_STATUS=skipped")
        print("FILE_COUNTS=0")
    else:
        print(f"UPLOAD_STATUS={batch.status}")
        print(f"FILE_COUNTS={batch.file_counts}")
    print(".env에 다음 값을 설정하세요:")
    print(f"OPENAI_VECTOR_STORE_ID={vector_store.id}")


if __name__ == "__main__":
    main()
