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
        assert "|" in result

    def test_empty_csv(self):
        result = parse_csv(b"", "test.csv")
        assert result == "(空檔案)"

    def test_header_only(self):
        result = parse_csv(b"name,age", "test.csv")
        assert "name" in result
        assert "---" in result

    def test_large_csv_truncation(self):
        lines = ["id,value"] + [f"{i},{i*10}" for i in range(200)]
        data = "\n".join(lines).encode()
        result = parse_csv(data, "big.csv")
        assert "showing first 50" in result

    def test_pipe_escaping(self):
        data = b"col1,col2\nhas|pipe,normal"
        result = parse_csv(data, "test.csv")
        assert "\\|" in result
