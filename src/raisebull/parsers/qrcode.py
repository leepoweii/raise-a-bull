"""QR code scanning and processing (supports Taiwan e-invoices)."""

import io
import re

from .invoice import (
    decrypt_right_qr,
    format_invoice,
    parse_items,
    parse_left_qr,
)


def scan_qr_codes(image_bytes: bytes) -> list[str]:
    """Scan QR codes from an image. Returns list of decoded strings."""
    try:
        from PIL import Image
        from pyzbar.pyzbar import decode

        img = Image.open(io.BytesIO(image_bytes))
        results = decode(img)
        return [r.data.decode("utf-8", errors="replace") for r in results]
    except Exception:
        return []


_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def process_qr_codes(qr_strings: list[str]) -> str | None:
    """Process decoded QR strings into human-readable output.

    - Taiwan e-invoice (starts with **) → parse and format
    - URL → link label
    - Other → raw content (truncated)

    Returns None if qr_strings is empty.
    """
    if not qr_strings:
        return None

    parts: list[str] = []

    # Separate invoice QRs from others
    invoice_qrs = [s for s in qr_strings if s.startswith("**")]
    other_qrs = [s for s in qr_strings if not s.startswith("**")]

    # Process invoice QRs (left + optional right)
    if invoice_qrs:
        left_data = invoice_qrs[0]
        info = parse_left_qr(left_data)
        if info:
            items = []
            # Try to decrypt right QR if available
            if len(invoice_qrs) > 1:
                decrypted = decrypt_right_qr(
                    invoice_qrs[1].lstrip("*"),  # right QR might also have prefix
                    info["invoice_number"],
                    info["random_code"],
                )
                if decrypted:
                    items = parse_items(decrypted)
            parts.append(format_invoice(info, items if items else None))
        else:
            # Could not parse — show raw
            parts.append(f"\U0001f4f1 QR Code: {left_data[:500]}")

    # Process non-invoice QRs
    for qs in other_qrs:
        if _URL_RE.match(qs):
            parts.append(f"\U0001f517 QR Code: {qs}")
        else:
            parts.append(f"\U0001f4f1 QR Code: {qs[:500]}")

    return "\n\n".join(parts)
