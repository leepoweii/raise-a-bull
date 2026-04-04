"""Unit tests for attachment router."""
import os
import pytest
from raisebull.parsers.router import get_mime_category, process_attachment


class TestGetMimeCategory:
    def test_image_mime(self):
        assert get_mime_category("image/jpeg", "photo.jpg") == "image"
        assert get_mime_category("image/png", "img.png") == "image"

    def test_pdf_mime(self):
        assert get_mime_category("application/pdf", "doc.pdf") == "pdf"

    def test_docx_mime(self):
        assert get_mime_category(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "doc.docx"
        ) == "docx"

    def test_xlsx_mime(self):
        assert get_mime_category(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "data.xlsx"
        ) == "xlsx"

    def test_pptx_mime(self):
        assert get_mime_category(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "slides.pptx"
        ) == "pptx"

    def test_csv_mime(self):
        assert get_mime_category("text/csv", "data.csv") == "csv"

    def test_text_mime(self):
        assert get_mime_category("text/plain", "notes.txt") == "text"

    def test_fallback_to_extension(self):
        assert get_mime_category("application/octet-stream", "photo.jpg") == "image"
        assert get_mime_category("application/octet-stream", "doc.pdf") == "pdf"
        assert get_mime_category("", "notes.md") == "text"

    def test_unsupported(self):
        assert get_mime_category("application/octet-stream", "file.zip") == "unsupported"
        assert get_mime_category("video/mp4", "video.mp4") == "unsupported"


class TestProcessAttachment:
    @pytest.mark.asyncio
    async def test_text_file(self, tmp_path):
        workspace = str(tmp_path)
        filepath, preview = await process_attachment(
            b"Hello World", "test.txt", "text/plain",
            session_id="test-session", workspace=workspace,
        )
        assert filepath.endswith("test.txt.txt")
        assert "Hello World" in preview
        assert os.path.exists(filepath)
        assert open(filepath).read() == "Hello World"

    @pytest.mark.asyncio
    async def test_csv_file(self, tmp_path):
        workspace = str(tmp_path)
        filepath, preview = await process_attachment(
            b"name,age\nAlice,30", "data.csv", "text/csv",
            session_id="test-session", workspace=workspace,
        )
        assert filepath.endswith("data.csv.txt")
        assert "Alice" in preview

    @pytest.mark.asyncio
    async def test_creates_session_directory(self, tmp_path):
        workspace = str(tmp_path)
        filepath, _ = await process_attachment(
            b"content", "test.txt", "text/plain",
            session_id="sess-123", workspace=workspace,
        )
        assert "/uploads/sess-123/" in filepath

    @pytest.mark.asyncio
    async def test_unsupported_format(self, tmp_path):
        workspace = str(tmp_path)
        filepath, preview = await process_attachment(
            b"\x00\x01", "file.zip", "application/zip",
            session_id="test-session", workspace=workspace,
        )
        assert "不支援" in preview

    @pytest.mark.asyncio
    async def test_collision_handling(self, tmp_path):
        workspace = str(tmp_path)
        fp1, _ = await process_attachment(
            b"first", "test.txt", "text/plain",
            session_id="sess", workspace=workspace,
        )
        fp2, _ = await process_attachment(
            b"second", "test.txt", "text/plain",
            session_id="sess", workspace=workspace,
        )
        assert fp1 != fp2
        assert os.path.exists(fp1)
        assert os.path.exists(fp2)

    @pytest.mark.asyncio
    async def test_image_without_vision(self, tmp_path):
        """Image without GEMINI_API_KEY → QR scan only, no vision description."""
        workspace = str(tmp_path)
        # 1x1 white PNG
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        filepath, preview = await process_attachment(
            png, "photo.png", "image/png",
            session_id="sess", workspace=workspace,
        )
        assert os.path.exists(filepath)
