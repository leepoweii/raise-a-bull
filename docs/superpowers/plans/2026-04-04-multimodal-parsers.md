# Multimodal Parsers Implementation Plan (Sub-phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port raise-a-calf's multimodal parser system to raise-a-bull so Discord and LINE attachments are parsed into text, saved to workspace/uploads/, and referenced in prompts for Claude Code to Read on demand.

**Architecture:** Attachments are downloaded → classified by MIME → dispatched to specialized parsers (text/document/vision/invoice/QR) → output saved as .txt in workspace/uploads/{session_id}/ → prompt includes file path + 200-char preview → Claude Code uses Read tool to access full content.

**Tech Stack:** PyMuPDF (PDF), python-docx (DOCX), openpyxl (XLSX), python-pptx (PPTX), Pillow (images), pycryptodomex (AES), pyzbar (QR), openai SDK (Gemini Vision)

**Spec:** `docs/superpowers/specs/2026-04-04-multimodal-parsers-design.md`

**Source reference:** raise-a-calf parsers at `/Users/pwlee/Documents/Github/raise-a-calf/bot/src/parsers/`

---

## File Structure

### New files to create
| File | Responsibility |
|------|---------------|
| `src/raisebull/parsers/__init__.py` | Empty package init |
| `src/raisebull/parsers/text.py` | Plain text + CSV parsing |
| `src/raisebull/parsers/document.py` | PDF, DOCX, XLSX, PPTX parsing |
| `src/raisebull/parsers/vision.py` | Image → Gemini Vision → text |
| `src/raisebull/parsers/invoice.py` | Taiwan e-invoice QR AES decryption |
| `src/raisebull/parsers/qrcode.py` | QR code scanning + dispatch |
| `src/raisebull/parsers/router.py` | MIME classification + dispatch + file storage |
| `tests/unit/test_parsers_text.py` | Text/CSV parser unit tests |
| `tests/unit/test_parsers_document.py` | Document parser unit tests |
| `tests/unit/test_invoice.py` | Invoice + QR unit tests |
| `tests/unit/test_attachment_router.py` | Router unit tests |

### Files to modify
| File | Changes |
|------|---------|
| `pyproject.toml` | Add parser dependencies |
| `Dockerfile` | Add `libzbar0` system dep |
| `src/raisebull/discord_bot.py:184-208` | Process attachments in `on_message()` |
| `src/raisebull/main.py:24,180-193` | Handle LINE image/file message types |
| `src/raisebull/webhook_line.py` | Add `handle_line_attachment()` function |

---

## Task 1: Dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `Dockerfile`

- [ ] **Step 1: Add Python dependencies to pyproject.toml**

In `pyproject.toml`, replace the dependencies list:

```python
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "line-bot-sdk>=3.12",
    "discord.py>=2.4",
    "apscheduler>=3.10",
    "aiosqlite>=0.20",
    "httpx>=0.27",
    "python-dotenv>=1.0",
    "python-docx>=1.2.0",
    "PyMuPDF>=1.24",
    "openpyxl>=3.1",
    "python-pptx>=1.0",
    "Pillow>=10.0",
    "pycryptodomex>=3.20",
    "pyzbar>=0.1.9",
    "openai>=1.50",
]
```

- [ ] **Step 2: Add libzbar0 to Dockerfile**

In `Dockerfile`, change line 3 from:
```dockerfile
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
```
to:
```dockerfile
RUN apt-get update && apt-get install -y curl libzbar0 && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 3: Sync dependencies**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && uv sync`
Expected: resolves and installs new packages without error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock Dockerfile
git commit -m "deps: add multimodal parser dependencies (PyMuPDF, Pillow, pyzbar, etc.)"
```

---

## Task 2: Text Parsers

**Files:**
- Create: `src/raisebull/parsers/__init__.py`
- Create: `src/raisebull/parsers/text.py`
- Create: `tests/unit/test_parsers_text.py`

- [ ] **Step 1: Create parser package**

Create empty `src/raisebull/parsers/__init__.py`.

- [ ] **Step 2: Write failing tests**

Create `tests/unit/test_parsers_text.py`:

```python
"""Unit tests for text parsers."""
import pytest
from raisebull.parsers.text import parse_text, parse_csv


class TestParseText:
    def test_short_text(self):
        result = parse_text(b"Hello world", "test.txt")
        assert result == "Hello world"

    def test_empty_file(self):
        result = parse_text(b"", "test.txt")
        assert result == "(空檔案)"

    def test_whitespace_only(self):
        result = parse_text(b"   \n  ", "test.txt")
        assert result == "(空檔案)"

    def test_truncation(self):
        text = "x" * 15_000
        result = parse_text(text.encode(), "big.txt")
        assert len(result) < 15_000
        assert "truncated" in result
        assert "15000 chars total" in result

    def test_utf8(self):
        result = parse_text("你好世界".encode("utf-8"), "test.txt")
        assert result == "你好世界"

    def test_big5_fallback(self):
        result = parse_text("你好".encode("big5"), "test.txt")
        assert "你好" in result

    def test_markdown_file(self):
        result = parse_text(b"# Title\n\nParagraph", "test.md")
        assert "# Title" in result


class TestParseCsv:
    def test_simple_csv(self):
        data = b"name,age\nAlice,30\nBob,25"
        result = parse_csv(data, "test.csv")
        assert "name" in result
        assert "Alice" in result
        assert "|" in result  # markdown table format

    def test_empty_csv(self):
        result = parse_csv(b"", "test.csv")
        assert result == "(空檔案)"

    def test_header_only(self):
        result = parse_csv(b"name,age", "test.csv")
        assert "name" in result
        assert "---" in result  # separator row

    def test_large_csv_truncation(self):
        lines = ["id,value"] + [f"{i},{i*10}" for i in range(200)]
        data = "\n".join(lines).encode()
        result = parse_csv(data, "big.csv")
        assert "showing first 50" in result

    def test_pipe_escaping(self):
        data = b"col1,col2\nhas|pipe,normal"
        result = parse_csv(data, "test.csv")
        assert "\\|" in result  # pipe escaped in markdown
```

- [ ] **Step 3: Run tests — verify they fail**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && uv run pytest tests/unit/test_parsers_text.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'raisebull.parsers'`

- [ ] **Step 4: Implement text.py**

Create `src/raisebull/parsers/text.py` — copy directly from raise-a-calf (`/Users/pwlee/Documents/Github/raise-a-calf/bot/src/parsers/text.py`). The file is self-contained (stdlib only) and needs no modifications.

- [ ] **Step 5: Run tests — verify they pass**

Run: `uv run pytest tests/unit/test_parsers_text.py -v`
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/raisebull/parsers/ tests/unit/test_parsers_text.py
git commit -m "feat: add text parsers (plain text + CSV)"
```

---

## Task 3: Document Parsers

**Files:**
- Create: `src/raisebull/parsers/document.py`
- Create: `tests/unit/test_parsers_document.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_parsers_document.py`:

```python
"""Unit tests for document parsers."""
import io
import pytest
from raisebull.parsers.document import parse_docx, parse_xlsx, parse_pptx, parse_pdf


class TestParseDocx:
    def test_simple_docx(self):
        from docx import Document
        doc = Document()
        doc.add_paragraph("Hello World")
        doc.add_paragraph("Second paragraph")
        buf = io.BytesIO()
        doc.save(buf)
        result = parse_docx(buf.getvalue(), "test.docx")
        assert "Hello World" in result
        assert "Second paragraph" in result

    def test_empty_docx(self):
        from docx import Document
        doc = Document()
        buf = io.BytesIO()
        doc.save(buf)
        result = parse_docx(buf.getvalue(), "test.docx")
        assert result == "(空檔案)"

    def test_docx_with_table(self):
        from docx import Document
        doc = Document()
        doc.add_paragraph("Before table")
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "H1"
        table.cell(0, 1).text = "H2"
        table.cell(1, 0).text = "A"
        table.cell(1, 1).text = "B"
        buf = io.BytesIO()
        doc.save(buf)
        result = parse_docx(buf.getvalue(), "test.docx")
        assert "Before table" in result
        assert "H1" in result
        assert "|" in result


class TestParseXlsx:
    def test_simple_xlsx(self):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Data"
        ws.append(["Name", "Value"])
        ws.append(["Alice", 10])
        buf = io.BytesIO()
        wb.save(buf)
        result = parse_xlsx(buf.getvalue(), "test.xlsx")
        assert "Sheet: Data" in result
        assert "Alice" in result

    def test_empty_sheet(self):
        import openpyxl
        wb = openpyxl.Workbook()
        buf = io.BytesIO()
        wb.save(buf)
        result = parse_xlsx(buf.getvalue(), "test.xlsx")
        assert "空工作表" in result

    def test_large_xlsx_truncation(self):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["id", "value"])
        for i in range(200):
            ws.append([i, i * 10])
        buf = io.BytesIO()
        wb.save(buf)
        result = parse_xlsx(buf.getvalue(), "test.xlsx")
        assert "showing first" in result


class TestParsePptx:
    def test_simple_pptx(self):
        from pptx import Presentation
        from pptx.util import Inches
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Title Slide"
        slide.placeholders[1].text = "Body text"
        buf = io.BytesIO()
        prs.save(buf)
        result = parse_pptx(buf.getvalue(), "test.pptx")
        assert "Slide 1" in result
        assert "Title Slide" in result

    def test_empty_pptx(self):
        from pptx import Presentation
        prs = Presentation()
        buf = io.BytesIO()
        prs.save(buf)
        result = parse_pptx(buf.getvalue(), "test.pptx")
        assert result == "(空檔案)"


class TestParsePdf:
    @pytest.mark.asyncio
    async def test_simple_pdf(self):
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello PDF")
        pdf_bytes = doc.tobytes()
        doc.close()
        result = await parse_pdf(pdf_bytes, "test.pdf")
        assert "Hello PDF" in result

    @pytest.mark.asyncio
    async def test_empty_pdf(self):
        import fitz
        doc = fitz.open()
        pdf_bytes = doc.tobytes()
        doc.close()
        result = await parse_pdf(pdf_bytes, "test.pdf")
        assert result == "(空檔案)"
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run pytest tests/unit/test_parsers_document.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement document.py**

Create `src/raisebull/parsers/document.py` — copy directly from raise-a-calf (`/Users/pwlee/Documents/Github/raise-a-calf/bot/src/parsers/document.py`). The file is self-contained and needs no modifications.

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest tests/unit/test_parsers_document.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/raisebull/parsers/document.py tests/unit/test_parsers_document.py
git commit -m "feat: add document parsers (PDF, DOCX, XLSX, PPTX)"
```

---

## Task 4: Vision Parser

**Files:**
- Create: `src/raisebull/parsers/vision.py`

- [ ] **Step 1: Implement vision.py**

Create `src/raisebull/parsers/vision.py` — copy directly from raise-a-calf (`/Users/pwlee/Documents/Github/raise-a-calf/bot/src/parsers/vision.py`). The file is self-contained. No test for this module (requires real Gemini API key — tested via integration in router smoke tests).

- [ ] **Step 2: Verify import works**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && uv run python -c "from raisebull.parsers.vision import create_vision_client; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/raisebull/parsers/vision.py
git commit -m "feat: add vision parser (Gemini Flash via OpenAI SDK)"
```

---

## Task 5: Invoice + QR Parsers

**Files:**
- Create: `src/raisebull/parsers/invoice.py`
- Create: `src/raisebull/parsers/qrcode.py`
- Create: `tests/unit/test_invoice.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_invoice.py`:

```python
"""Unit tests for Taiwan e-invoice parser and QR code processing."""
import pytest
from raisebull.parsers.invoice import parse_left_qr, decrypt_right_qr, parse_items, format_invoice
from raisebull.parsers.qrcode import scan_qr_codes, process_qr_codes


class TestParseLeftQr:
    def test_valid_invoice(self):
        # Construct valid QR: ** + 2 letters + 8 digits + ROC date + random + hex amounts + IDs
        qr = "**AB12345678" + "11401" + "15" + "ABCD" + "0000007B" + "00000082" + "00000000" + "12345678" + "X" * 24
        result = parse_left_qr(qr)
        assert result is not None
        assert result["invoice_number"] == "AB-12345678"
        assert result["random_code"] == "ABCD"
        assert result["total"] == 130  # 0x82

    def test_not_invoice(self):
        assert parse_left_qr("https://example.com") is None

    def test_empty_string(self):
        assert parse_left_qr("") is None

    def test_too_short(self):
        assert parse_left_qr("**AB") is None

    def test_no_buyer_id(self):
        qr = "**AB12345678" + "11401" + "15" + "ABCD" + "0000007B" + "00000082" + "00000000" + "12345678" + "X" * 24
        result = parse_left_qr(qr)
        assert result["buyer_id"] is None


class TestParseItems:
    def test_single_item(self):
        items = parse_items("咖啡:1:65")
        assert len(items) == 1
        assert items[0] == {"name": "咖啡", "qty": 1, "price": 65}

    def test_multiple_items(self):
        items = parse_items("咖啡:1:65:蛋糕:2:120")
        assert len(items) == 2

    def test_empty(self):
        assert parse_items("") == []

    def test_malformed(self):
        items = parse_items("name:notanumber:50")
        assert len(items) == 0


class TestFormatInvoice:
    def test_basic(self):
        info = {
            "invoice_number": "AB-12345678",
            "date": "2025/01/15",
            "total": 130,
            "seller_id": "12345678",
            "buyer_id": None,
        }
        result = format_invoice(info)
        assert "AB-12345678" in result
        assert "$130" in result

    def test_with_items(self):
        info = {
            "invoice_number": "AB-12345678",
            "date": "2025/01/15",
            "total": 130,
            "seller_id": "12345678",
            "buyer_id": None,
        }
        items = [{"name": "咖啡", "qty": 1, "price": 65}]
        result = format_invoice(info, items)
        assert "咖啡" in result


class TestProcessQrCodes:
    def test_empty(self):
        assert process_qr_codes([]) is None

    def test_url(self):
        result = process_qr_codes(["https://example.com"])
        assert "example.com" in result

    def test_raw_text(self):
        result = process_qr_codes(["some random text"])
        assert "some random text" in result
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run pytest tests/unit/test_invoice.py -v`
Expected: FAIL

- [ ] **Step 3: Implement invoice.py and qrcode.py**

Create `src/raisebull/parsers/invoice.py` — copy from raise-a-calf. No modifications needed.

Create `src/raisebull/parsers/qrcode.py` — copy from raise-a-calf. Update the import path on line 6-11:

```python
from raisebull.parsers.invoice import (
    decrypt_right_qr,
    format_invoice,
    parse_items,
    parse_left_qr,
)
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest tests/unit/test_invoice.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/raisebull/parsers/invoice.py src/raisebull/parsers/qrcode.py tests/unit/test_invoice.py
git commit -m "feat: add invoice parser (Taiwan e-invoice QR AES) + QR scanner"
```

---

## Task 6: Attachment Router

**Files:**
- Create: `src/raisebull/parsers/router.py`
- Create: `tests/unit/test_attachment_router.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_attachment_router.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run pytest tests/unit/test_attachment_router.py -v`
Expected: FAIL

- [ ] **Step 3: Implement router.py**

Create `src/raisebull/parsers/router.py`:

```python
"""Attachment router — dispatches files to parsers, saves output to workspace/uploads/."""

import os
from typing import Optional

from raisebull.parsers.text import parse_text, parse_csv
from raisebull.parsers.document import parse_pdf, parse_docx, parse_xlsx, parse_pptx
from raisebull.parsers.qrcode import scan_qr_codes, process_qr_codes

PREVIEW_CHARS = 200

_EXT_MAP = {
    ".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".xls": "xlsx",
    ".pptx": "pptx", ".csv": "csv", ".md": "text", ".txt": "text",
    ".jpg": "image", ".jpeg": "image", ".png": "image",
    ".gif": "image", ".webp": "image",
}


def get_mime_category(content_type: str, filename: str) -> str:
    """Classify attachment by MIME type, falling back to file extension."""
    ct = content_type.lower()
    if ct.startswith("image/"): return "image"
    if ct == "application/pdf": return "pdf"
    if "wordprocessingml" in ct: return "docx"
    if "spreadsheetml" in ct: return "xlsx"
    if "presentationml" in ct: return "pptx"
    if ct == "text/csv": return "csv"
    if ct.startswith("text/"): return "text"
    ext = os.path.splitext(filename)[1].lower()
    return _EXT_MAP.get(ext, "unsupported")


def _save_output(text: str, filename: str, session_id: str, workspace: str) -> str:
    """Save parsed text to workspace/uploads/{session_id}/{filename}.txt.

    Returns the absolute file path. Handles collisions with counter suffix.
    """
    upload_dir = os.path.join(workspace, "uploads", session_id)
    os.makedirs(upload_dir, exist_ok=True)

    out_name = f"{filename}.txt"
    out_path = os.path.join(upload_dir, out_name)

    # Handle collision
    counter = 2
    while os.path.exists(out_path):
        out_name = f"{filename}.{counter}.txt"
        out_path = os.path.join(upload_dir, out_name)
        counter += 1

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)

    return out_path


async def process_attachment(
    file_bytes: bytes,
    filename: str,
    content_type: str = "",
    session_id: str = "unknown",
    workspace: str = "/app/workspace",
    vision_client=None,
) -> tuple[str, str]:
    """Route attachment to parser, save output, return (filepath, preview).

    Args:
        file_bytes: Raw attachment bytes.
        filename: Original filename.
        content_type: MIME type (may be empty).
        session_id: Session key for directory scoping.
        workspace: Workspace root path.
        vision_client: Optional VisionClient for image description.

    Returns:
        (filepath, preview) — absolute path to saved .txt file and first 200 chars.
    """
    category = get_mime_category(content_type, filename)

    if category == "text":
        text = parse_text(file_bytes, filename)
    elif category == "csv":
        text = parse_csv(file_bytes, filename)
    elif category == "docx":
        text = parse_docx(file_bytes, filename)
    elif category == "xlsx":
        text = parse_xlsx(file_bytes, filename)
    elif category == "pptx":
        text = parse_pptx(file_bytes, filename)
    elif category == "pdf":
        async def vision_fn(img_bytes):
            if vision_client:
                from raisebull.parsers.vision import describe_image
                return await describe_image(vision_client, img_bytes)
            return "(scanned page, vision unavailable)"
        text = await parse_pdf(file_bytes, filename, vision_fn=vision_fn)
    elif category == "image":
        parts = []
        qr_strings = scan_qr_codes(file_bytes)
        qr_text = process_qr_codes(qr_strings)
        if qr_text:
            parts.append(qr_text)
        if vision_client:
            from raisebull.parsers.vision import describe_image
            desc = await describe_image(vision_client, file_bytes, content_type or "image/jpeg")
            parts.append(desc)
        elif not qr_text:
            parts.append("(收到圖片，但 vision 功能未啟用)")
        text = "\n\n".join(parts)
    else:
        text = f"不支援此格式：{filename}"

    filepath = _save_output(text, filename, session_id, workspace)
    preview = text[:PREVIEW_CHARS]
    return filepath, preview
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest tests/unit/test_attachment_router.py -v`
Expected: all tests PASS

- [ ] **Step 5: Run all unit tests**

Run: `uv run pytest tests/unit/ -v`
Expected: all tests PASS (existing + new)

- [ ] **Step 6: Commit**

```bash
git add src/raisebull/parsers/router.py tests/unit/test_attachment_router.py
git commit -m "feat: add attachment router (MIME dispatch + workspace storage)"
```

---

## Task 7: Discord Integration

**Files:**
- Modify: `src/raisebull/discord_bot.py:184-210`

- [ ] **Step 1: Add attachment processing to on_message**

In `src/raisebull/discord_bot.py`, add import at top (after existing imports):

```python
from raisebull.parsers.router import process_attachment
from raisebull.parsers.vision import create_vision_client
```

In `create_bot()`, before the `@bot.event` on_message handler (around line 182), add vision client init:

```python
    _vision_client = create_vision_client()
```

In `on_message()`, after line 208 (`if not prompt: prompt = "Hello"`), replace with:

```python
        if not prompt and not message.attachments:
            prompt = "Hello"

        # Process attachments
        attachment_parts = []
        for att in message.attachments:
            try:
                file_bytes = await att.read()
                filepath, preview = await process_attachment(
                    file_bytes, att.filename, att.content_type or "",
                    session_id=key, workspace=runner.workspace,
                    vision_client=_vision_client,
                )
                attachment_parts.append(
                    f"用戶上傳了 {att.filename}，已解析存放在：{filepath}\n"
                    f"請用 Read 工具查看完整內容。\n"
                    f"前 200 字預覽：\n{preview}"
                )
            except Exception:
                logger.exception("Failed to process attachment %s", att.filename)
                attachment_parts.append(f"(附件 {att.filename} 處理失敗)")

        if attachment_parts:
            prompt = "\n\n---\n\n".join(attachment_parts) + "\n\n" + (prompt or "")
            prompt = prompt.strip()
```

- [ ] **Step 2: Run existing tests to check for breakage**

Run: `uv run pytest tests/test_discord_bot.py tests/unit/ tests/integration/ -v`
Expected: all existing tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/raisebull/discord_bot.py
git commit -m "feat: Discord attachment processing (download → parse → workspace)"
```

---

## Task 8: LINE Integration

**Files:**
- Modify: `src/raisebull/main.py:24,180-193`
- Modify: `src/raisebull/webhook_line.py`

- [ ] **Step 1: Update LINE webhook to handle image/file messages**

In `src/raisebull/main.py`, add imports at line 24 (after existing LINE imports):

```python
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent, FileMessageContent
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, MessagingApiBlob
```

(Remove the duplicate `TextMessageContent` from the existing import on line 24 if present.)

In the `_process()` function (lines 180-190), expand the isinstance check:

```python
    async def _process() -> None:
        configuration = Configuration(access_token=access_token)
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            blob_api = MessagingApiBlob(api_client)
            for event in events:
                if not isinstance(event, MessageEvent):
                    continue
                if isinstance(event.message, TextMessageContent):
                    await handle_line_message(
                        event, _runner, _sessions, messaging_api
                    )
                elif isinstance(event.message, (ImageMessageContent, FileMessageContent)):
                    await handle_line_attachment(
                        event, _runner, _sessions, messaging_api, blob_api
                    )
```

Add new import at top of main.py:

```python
from raisebull.webhook_line import handle_line_message, handle_line_attachment
```

(Replace the existing `from raisebull.webhook_line import handle_line_message` line.)

- [ ] **Step 2: Add handle_line_attachment to webhook_line.py**

Add at the bottom of `src/raisebull/webhook_line.py`:

```python
from raisebull.parsers.router import process_attachment
from raisebull.parsers.vision import create_vision_client

_vision_client_line = create_vision_client()


async def handle_line_attachment(
    event: "MessageEvent",
    runner: "ClaudeRunner",
    sessions: "SessionStore",
    messaging_api: "MessagingApi",
    blob_api,
) -> None:
    """Handle image/file attachments from LINE."""
    user_id: str = event.source.user_id
    session_key, _, chat_id = _resolve_context(event)

    # Download content from LINE
    try:
        message_id = event.message.id
        content_response = blob_api.get_message_content(message_id)
        file_bytes = content_response

        # Determine filename and content type
        msg = event.message
        if hasattr(msg, "file_name") and msg.file_name:
            filename = msg.file_name
            content_type = getattr(msg, "content_type", "") or ""
        else:
            # Image message — no filename, use message_id
            filename = f"{message_id}.jpg"
            content_type = "image/jpeg"

    except Exception:
        logger.exception("Failed to download LINE content %s", event.message.id)
        _send(chat_id, event.reply_token, "⚠️ 無法下載附件", messaging_api)
        return

    # Process attachment
    try:
        row = await sessions.get(session_key)
        existing_session_id = row["session_id"] if row else None

        filepath, preview = await process_attachment(
            file_bytes, filename, content_type,
            session_id=session_key,
            workspace=os.path.dirname(os.path.dirname(__file__)) + "/../workspace"
                if not os.environ.get("WORKSPACE") else os.environ["WORKSPACE"],
            vision_client=_vision_client_line,
        )

        prompt = (
            f"用戶上傳了 {filename}，已解析存放在：{filepath}\n"
            f"請用 Read 工具查看完整內容。\n"
            f"前 200 字預覽：\n{preview}"
        )

        await _process_message(
            prompt=prompt,
            session_key=session_key,
            chat_id=chat_id,
            user_id=user_id,
            reply_token=event.reply_token,
            runner=runner,
            sessions=sessions,
            messaging_api=messaging_api,
        )
    except Exception:
        logger.exception("Failed to process LINE attachment")
        _send(chat_id, event.reply_token, "⚠️ 附件處理失敗", messaging_api)
```

- [ ] **Step 3: Run all tests**

Run: `uv run pytest tests/ -v --ignore=tests/smoke --ignore=tests/e2e`
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/raisebull/main.py src/raisebull/webhook_line.py
git commit -m "feat: LINE attachment processing (image + file → parse → workspace)"
```

---

## Task 9: Add GEMINI_API_KEY to .env.example and entrypoint

**Files:**
- Modify: `.env.example`
- Modify: `entrypoint.sh`

- [ ] **Step 1: Update .env.example**

Add after the JINA_API_KEY line:

```
# Vision (image description via Gemini)
# Get free key: https://aistudio.google.com/apikey
GEMINI_API_KEY=
```

- [ ] **Step 2: Update entrypoint.sh to pass GEMINI_API_KEY to environment**

No changes needed — GEMINI_API_KEY is read at runtime via `os.getenv()` in vision.py, and Docker passes all env vars from .env file to the container automatically.

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: add GEMINI_API_KEY to .env.example"
```

---

## Task 10: Final Integration Test

- [ ] **Step 1: Run all fast tests**

Run: `uv run pytest tests/unit/ tests/integration/ -v`
Expected: all tests PASS (existing ~70 + new ~50)

- [ ] **Step 2: Verify parser count**

Run: `uv run pytest tests/unit/test_parsers_text.py tests/unit/test_parsers_document.py tests/unit/test_invoice.py tests/unit/test_attachment_router.py -v --tb=short`
Expected: ~50+ tests PASS

- [ ] **Step 3: Push and rebuild**

```bash
git push origin feature/calf-merge
```

Then on samantha-wsl:
```bash
ssh -p 2222 samantha-machine@samantha-wsl.tail5a1118.ts.net
cd ~/raise-a-bull
git pull origin feature/calf-merge
BOT_NAME=daniu BOT_PORT=18888 BOT_ENV_FILE=~/bots/daniu/.env WORKSPACE_PATH=~/bots/daniu/workspace docker compose build
docker stop bull-daniu && docker rm bull-daniu
BOT_NAME=daniu BOT_PORT=18888 BOT_ENV_FILE=~/bots/daniu/.env WORKSPACE_PATH=~/bots/daniu/workspace docker compose up -d
```

Add GEMINI_API_KEY to `~/bots/daniu/.env` if available.
