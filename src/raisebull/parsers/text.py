"""Text file parsers: plain text, markdown, and CSV."""

import csv
import io

MAX_TEXT_CHARS = 10_000
MAX_CSV_ROWS = 100


def _decode(file_bytes: bytes) -> str:
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return file_bytes.decode("big5")
        except UnicodeDecodeError:
            return file_bytes.decode("utf-8", errors="replace")


def parse_text(file_bytes: bytes, filename: str) -> str:
    """Parse plain text or markdown file. Truncates at MAX_TEXT_CHARS."""
    text = _decode(file_bytes)
    if not text.strip():
        return "(空檔案)"
    if len(text) > MAX_TEXT_CHARS:
        total = len(text)
        text = text[:MAX_TEXT_CHARS] + f"\n\n(truncated, {total} chars total)"
    return text


def parse_csv(file_bytes: bytes, filename: str) -> str:
    """Parse CSV and convert to markdown table. Caps at MAX_CSV_ROWS."""
    text = _decode(file_bytes)
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    if not rows:
        return "(空檔案)"

    header = rows[0]
    data_rows = rows[1:]
    total_data = len(data_rows)

    if total_data > MAX_CSV_ROWS:
        selected = data_rows[:50] + data_rows[-10:]
        truncated = True
    else:
        selected = data_rows
        truncated = False

    def md_row(cells):
        return "| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |"

    sep = "| " + " | ".join("---" for _ in header) + " |"
    lines = [md_row(header), sep]
    lines += [md_row(r) for r in selected]

    if truncated:
        lines.append(
            f"\n*(showing first 50 + last 10 of {total_data} rows)*"
        )

    return "\n".join(lines)
