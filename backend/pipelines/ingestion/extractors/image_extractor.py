"""Image extractor — vision LLM description + pytesseract OCR."""
from __future__ import annotations

import base64
from pipelines.ingestion.extractors.pdf_extractor import ExtractedPage


def _resize_image(file_path: str, max_px: int = 1024) -> bytes:
    from PIL import Image
    import io
    img = Image.open(file_path)
    img.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def extract_image(file_path: str) -> list[ExtractedPage]:
    import pytesseract
    from PIL import Image

    # OCR
    ocr_text = pytesseract.image_to_string(Image.open(file_path)).strip()

    # Vision LLM description
    description = ""
    try:
        from providers.base import ChatMessage, RoutingCriteria
        from providers.router import get_router

        img_bytes = _resize_image(file_path)
        b64 = base64.b64encode(img_bytes).decode()

        router = get_router()
        provider, _ = await router.route(RoutingCriteria(require_vision=True, task_type="image_description"))

        result = await provider.complete([
            ChatMessage(role="user", content=[
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": "Describe this image in detail, including all visible text, diagrams, charts, and important visual elements."},
            ])
        ])
        description = result.content
    except Exception as e:
        description = f"[Vision description unavailable: {e}]"

    combined = description
    if ocr_text:
        combined += f"\n\nText found in image:\n{ocr_text}"

    return [ExtractedPage(
        page_number=1,
        content=combined,
        content_type="image_description",
        metadata={"file_path": file_path},
    )]
