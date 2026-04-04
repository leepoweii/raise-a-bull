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
