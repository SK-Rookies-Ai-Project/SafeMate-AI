import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import create_vector_store


class FakeFileBatches:
    def upload_and_poll(self, **kwargs):
        raise AssertionError("빈 저장소 생성 시 파일 업로드를 호출하면 안 됩니다.")


class FakeVectorStores:
    def __init__(self) -> None:
        self.file_batches = FakeFileBatches()
        self.create_calls: list[dict] = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(id="vs_empty_test")


class CreateVectorStoreTest(unittest.TestCase):
    def test_creates_empty_store_without_uploading_files(self) -> None:
        vector_stores = FakeVectorStores()
        fake_client = SimpleNamespace(vector_stores=vector_stores)

        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            with (
                patch.object(create_vector_store, "KNOWLEDGE_DIR", Path(temp_dir)),
                patch.object(create_vector_store, "load_dotenv"),
                patch.object(create_vector_store, "OpenAI", return_value=fake_client),
                patch.dict(
                    os.environ,
                    {
                        "OPENAI_API_KEY": "test-key",
                        "OPENAI_VECTOR_STORE_ID": "",
                    },
                ),
                redirect_stdout(output),
            ):
                create_vector_store.main()

        self.assertEqual(len(vector_stores.create_calls), 1)
        self.assertIn("VECTOR_STORE_ID=vs_empty_test", output.getvalue())
        self.assertIn("UPLOAD_STATUS=skipped", output.getvalue())
        self.assertIn("FILE_COUNTS=0", output.getvalue())


if __name__ == "__main__":
    unittest.main()
