# Phase 3: Multimodal Parsers — Design Spec

**Date:** 2026-04-04
**Status:** Approved
**Scope:** Sub-phase 1 (parsers + Discord + LINE), Sub-phase 2 (Web Chat upload) deferred

---

## Overview

Port raise-a-calf's multimodal parser system to raise-a-bull. Attachments from Discord and LINE are downloaded, parsed into plain text, saved to `workspace/uploads/`, and the file path is given to Claude Code so it can `Read` on demand.

MiniMax M2.7 is text-only — images go through Gemini Vision API for description.

---

## Architecture

```
Discord attachment / LINE content message
  → download bytes
  → router.process_attachment(bytes, filename, content_type, session_id, workspace)
      ├─ classify MIME type
      ├─ call appropriate parser → plain text
      ├─ write to workspace/uploads/{session_id}/{filename}.txt
      └─ return (filepath, preview)
  → build prompt:
      「用戶上傳了 {filename}，內容已解析並存放在：
       {filepath}
       請用 Read 工具查看完整內容。

       前 200 字預覽：
       {preview}」
  → append original text message if any
  → ClaudeRunner.run(combined_prompt, session_id)
```

---

## Parsers Module: `src/raisebull/parsers/`

### text.py — Plain Text / CSV

| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `parse_text(bytes, filename)` | .txt, .md bytes | str | UTF-8 → Big5 fallback, truncate at 10K chars |
| `parse_csv(bytes, filename)` | .csv bytes | str | Markdown table, first 50 + last 10 of 100 rows |

Dependencies: stdlib only.

### document.py — Office Documents

| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `parse_pdf(bytes, filename, vision_fn?)` | .pdf bytes | str | PyMuPDF, max 20 pages, vision fallback for scanned pages (<50 chars) |
| `parse_docx(bytes, filename)` | .docx bytes | str | python-docx, paragraphs + tables as markdown |
| `parse_xlsx(bytes, filename)` | .xlsx bytes | str | openpyxl, markdown tables per sheet, max 100 rows |
| `parse_pptx(bytes, filename)` | .pptx bytes | str | python-pptx, slides as headings + text |

Dependencies: PyMuPDF, python-docx, openpyxl, python-pptx, Pillow (for PDF vision fallback).

### vision.py — Image Description via Gemini

| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `create_vision_client(gemini_api_key?)` | API key | VisionClient or None | Returns None if no key |
| `describe_image(client, bytes, mime_type)` | image bytes | str | Gemini Flash via OpenAI SDK, resize if >4MB, Chinese system prompt |

Dependencies: openai SDK, Pillow.
Env: `GEMINI_API_KEY` (optional — graceful degrade if missing).

### invoice.py — Taiwan E-Invoice QR

| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `parse_left_qr(qr_data)` | QR string (** prefix) | dict | Invoice number, date, amounts, seller/buyer IDs |
| `decrypt_right_qr(data, invoice_no, random_code)` | encoded data | str | AES-128-CBC, key = invoice_no + random_code + padding |
| `parse_items(decrypted)` | decrypted text | list[dict] | name:qty:price triplets |
| `format_invoice(info, items?)` | dict + list | str | Human-readable formatted string |

Dependencies: pycryptodomex.

### qrcode.py — QR Code Scanner

| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `scan_qr_codes(bytes)` | image bytes | list[str] | Returns decoded strings |
| `process_qr_codes(strings)` | list[str] | str or None | ** → invoice, http → URL, else raw |

Dependencies: pyzbar, Pillow.
System dep: `libzbar0` (Dockerfile).

### router.py — Attachment Router

| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `get_mime_category(content_type, filename)` | MIME + name | str | text/csv/docx/xlsx/pptx/pdf/image/unsupported |
| `process_attachment(bytes, filename, content_type, session_id, workspace, vision_client?)` | all above | (filepath, preview) | Parses → saves to uploads/ → returns path |

MIME category map:
- text: .txt, .md → `parse_text`
- csv: .csv → `parse_csv`
- docx: .docx → `parse_docx`
- xlsx: .xlsx → `parse_xlsx`
- pptx: .pptx → `parse_pptx`
- pdf: .pdf → `parse_pdf`
- image: .jpg, .jpeg, .png, .gif, .webp → QR scan + vision
- unsupported: everything else → error message

Output path: `{workspace}/uploads/{session_id}/{filename}.txt`

---

## Channel Integration

### Discord (`discord_bot.py`)

In `on_message()`, after extracting text content:

```python
attachment_prompts = []
for att in message.attachments:
    file_bytes = await att.read()
    filepath, preview = await process_attachment(
        file_bytes, att.filename, att.content_type or "",
        session_id, workspace, vision_client
    )
    attachment_prompts.append(
        f"用戶上傳了 {att.filename}，已解析存放在：{filepath}\n"
        f"請用 Read 工具查看完整內容。\n前 200 字預覽：\n{preview}"
    )
# Prepend attachment info to text prompt
prompt = "\n\n".join(attachment_prompts + [text_content])
```

### LINE (`main.py` + `webhook_line.py`)

Expand `isinstance()` check in `main.py`:

```python
if isinstance(event.message, TextMessageContent):
    await handle_line_message(event, ...)
elif isinstance(event.message, (ImageMessageContent, FileMessageContent)):
    await handle_line_attachment(event, ...)
```

New `handle_line_attachment()` in `webhook_line.py`:
- Get content via LINE Messaging API `get_content(message_id)`
- Route through `process_attachment()`
- Send result to `_process_message()` with attachment prompt

### Web Chat (Sub-phase 2, deferred)

- Extend `MessageBody` to accept `UploadFile`
- Multipart/form-data endpoint
- Same router flow
- Alpine.js file picker UI

---

## File Storage

```
workspace/
└── uploads/
    └── {session_id}/          ← one dir per session
        ├── photo.jpg.txt      ← parsed image description
        ├── report.pdf.txt     ← parsed PDF content
        └── invoice.csv.txt    ← parsed CSV as markdown table
```

- No auto-cleanup (future dashboard session management)
- File naming: `{original_filename}.txt` (always .txt suffix for parsed output)
- Collision: append counter if file exists (`report.pdf.txt`, `report.pdf.2.txt`)

---

## Dependencies

### pyproject.toml additions

```
PyMuPDF>=1.24
python-docx>=1.2
openpyxl>=3.1
python-pptx>=1.0
Pillow>=10.0
pycryptodomex>=3.20
pyzbar>=0.1.9
openai>=1.50
```

### Dockerfile additions

```dockerfile
RUN apt-get update && apt-get install -y curl libzbar0 && rm -rf /var/lib/apt/lists/*
```

(Merge with existing `apt-get install -y curl` line.)

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | optional | Enables image vision (Gemini Flash). Without it: QR scan only, no image description. |

---

## Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| No `GEMINI_API_KEY` | Images: QR scan only, no vision description. PDFs: text extraction only, scanned pages show "(scanned page, vision unavailable)" |
| pyzbar import fails | QR scanning disabled, images go straight to vision |
| Document lib import fails | That format returns "unsupported (missing dependency)" |

---

## Tests

Port from raise-a-calf, adapted for raise-a-bull test structure:

| Test file | Count | What |
|-----------|-------|------|
| `tests/unit/test_parsers_text.py` | ~15 | Encoding, truncation, CSV formatting, empty files |
| `tests/unit/test_parsers_document.py` | ~14 | PDF pages, DOCX tables, XLSX sheets, PPTX slides |
| `tests/unit/test_invoice.py` | ~24 | QR parsing, AES decryption, item parsing, formatting |
| `tests/unit/test_attachment_router.py` | ~20 | MIME classification, routing, file storage, preview |
| **Total** | **~73** | All unit tests, no LLM or API calls needed |

---

## Sub-phase 2 (Web Chat — deferred)

1. `POST /api/chat/{session_id}/messages` accepts `multipart/form-data`
2. `MessageBody` gets optional `files: list[UploadFile]`
3. Alpine.js: file picker button + drag-and-drop zone in chat input
4. Same `process_attachment()` flow
5. Additional integration tests for file upload
