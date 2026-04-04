"""Taiwan e-invoice QR code parser (MOF 財政部電子發票格式)."""


def parse_left_qr(qr_data: str) -> dict | None:
    """Parse left QR code of a Taiwan e-invoice.

    Returns dict with invoice_number, date, random_code, sales_amount,
    total, buyer_id, seller_id.  Returns None if not a valid invoice QR.
    """
    if not qr_data or not qr_data.startswith("**"):
        return None

    data = qr_data[2:]  # strip **
    if len(data) < 77:
        return None

    try:
        # Invoice number: 2 letters + 8 digits (positions 0-9)
        inv_letters = data[0:2]
        inv_digits = data[2:10]
        invoice_number = f"{inv_letters}-{inv_digits}"

        # Date: ROC year (3) + month (2) + day (2) → western date
        roc_year = int(data[10:13])
        month = data[13:15]
        day = data[15:17]
        western_year = roc_year + 1911
        date = f"{western_year}/{month}/{day}"

        # Random code: 4 chars
        random_code = data[17:21]

        # Sales amount (without tax): 8 hex chars
        sales_hex = data[21:29]
        sales_amount = int(sales_hex, 16)

        # Total amount (with tax): 8 hex chars
        total_hex = data[29:37]
        total = int(total_hex, 16)

        # Buyer ID: 8 chars ("00000000" means no buyer ID)
        buyer_raw = data[37:45]
        buyer_id = None if buyer_raw == "00000000" else buyer_raw

        # Seller ID: 8 chars
        seller_id = data[45:53]
    except (ValueError, IndexError):
        return None

    return {
        "invoice_number": invoice_number,
        "date": date,
        "random_code": random_code,
        "sales_amount": sales_amount,
        "total": total,
        "buyer_id": buyer_id,
        "seller_id": seller_id,
    }


def decrypt_right_qr(
    encoded_data: str | bytes, invoice_number: str, random_code: str
) -> str | None:
    """Decrypt the right QR code payload using AES-128-CBC.

    Key = invoice_no (10 chars, no dash) + random_code (4 chars) + \\x00*2
    IV  = 16 zero bytes.
    """
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
    except ImportError:
        return None

    try:
        # Build key: 10-char invoice number (no dash) + 4-char random code = 14, pad to 16
        inv_no = invoice_number.replace("-", "")
        key_str = inv_no + random_code  # 14 chars
        key = key_str.encode("utf-8").ljust(16, b"\x00")
        iv = b"\x00" * 16

        if isinstance(encoded_data, str):
            import base64

            ciphertext = base64.b64decode(encoded_data)
        else:
            ciphertext = encoded_data

        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = unpad(cipher.decrypt(ciphertext), AES.block_size)
        return decrypted.decode("utf-8")
    except Exception:
        return None


def parse_items(decrypted_text: str) -> list[dict]:
    """Parse colon-delimited item triplets: name:qty:price:name:qty:price...

    Returns list of {"name": str, "qty": int, "price": int}.
    """
    if not decrypted_text or not decrypted_text.strip():
        return []

    parts = decrypted_text.strip().split(":")
    items = []
    # Process in groups of 3
    for i in range(0, len(parts) - 2, 3):
        name = parts[i]
        try:
            qty = int(parts[i + 1])
            price = int(parts[i + 2])
        except (ValueError, IndexError):
            continue
        items.append({"name": name, "qty": qty, "price": price})
    return items


def format_invoice(info: dict, items: list[dict] | None = None) -> str:
    """Format invoice info + items into a readable string."""
    lines = [
        f"\U0001f4c4 電子發票 {info['invoice_number']}",
        f"日期：{info['date']}",
        f"金額：${info['total']}",
    ]

    if info.get("seller_id"):
        lines.append(f"賣方統編：{info['seller_id']}")
    if info.get("buyer_id"):
        lines.append(f"買方統編：{info['buyer_id']}")

    if items:
        lines.append("")
        lines.append("\U0001f4e6 品項明細：")
        for item in items:
            lines.append(f"  {item['name']}  x{item['qty']}  ${item['price']}")

    return "\n".join(lines)
