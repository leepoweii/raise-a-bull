"""Unit tests for Taiwan e-invoice parser and QR code processing."""
import pytest
from raisebull.parsers.invoice import parse_left_qr, decrypt_right_qr, parse_items, format_invoice
from raisebull.parsers.qrcode import scan_qr_codes, process_qr_codes


class TestParseLeftQr:
    def test_valid_invoice(self):
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
