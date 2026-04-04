"""Vision parser — image description via Gemini 2.5 Flash.

Uses OpenAI Python SDK directly (not Mini-Agent's LLMClient which adds
MiniMax-specific parameters that Gemini rejects).

Fallback chain: Gemini 2.5 Flash → skip.
"""

import base64
import os
from dataclasses import dataclass


@dataclass
class VisionClient:
    """Lightweight vision client wrapping OpenAI SDK for Gemini."""
    api_key: str
    base_url: str
    model: str


def create_vision_client(
    gemini_api_key: str | None = None,
    minimax_api_key: str | None = None,
    minimax_api_base: str | None = None,
) -> VisionClient | None:
    """Create a vision client. Gemini preferred."""
    key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
    if key:
        return VisionClient(
            api_key=key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            model="gemini-3.1-flash-lite-preview",
        )
    return None


async def describe_image(
    vision_client: VisionClient,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> str:
    """Send image to vision model and get text description."""
    import openai

    # Resize if too large (>4MB)
    if len(image_bytes) > 4 * 1024 * 1024:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes))
        img.thumbnail((2048, 2048), Image.LANCZOS)
        buf = io.BytesIO()
        fmt = "JPEG" if "jpeg" in mime_type or "jpg" in mime_type else "PNG"
        img.save(buf, format=fmt)
        image_bytes = buf.getvalue()

    b64 = base64.b64encode(image_bytes).decode("ascii")

    client = openai.AsyncOpenAI(
        api_key=vision_client.api_key,
        base_url=vision_client.base_url,
    )

    response = await client.chat.completions.create(
        model=vision_client.model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一個圖片分析助手。描述圖片內容，提取所有可見文字。"
                    "如果是收據或發票，提取金額、日期、品項。用繁體中文回答。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "請描述這張圖片的內容，提取所有可見文字。"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                ],
            },
        ],
    )

    return response.choices[0].message.content or "(無法辨識圖片內容)"
