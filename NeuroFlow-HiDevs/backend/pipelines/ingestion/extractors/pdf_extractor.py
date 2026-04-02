"""PDF extractor — handles digital and scanned pages."""
from __future__ import annotations

import io
from dataclasses import dataclass, field


@dataclass
class ExtractedPage:
    page_number: int
    content: str
    content_type: str  # "text" | "table" | "image_description"
    metadata: dict = field(default_factory=dict)


def extract_pdf(file_path: str) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []

    try:
        import pypdfium2 as pdfium
        import pdfplumber
        import pytesseract
        from PIL import Image

        doc = pdfium.PdfDocument(file_path)
        plumber_doc = pdfplumber.open(file_path)

        for page_num in range(len(doc)):
            plumber_page = plumber_doc.pages[page_num]

            # Extract tables first
            tables = plumber_page.extract_tables()
            for table in tables:
                if table:
                    md_rows = []
                    for i, row in enumerate(table):
                        cells = [str(c or "") for c in row]
                        md_rows.append("| " + " | ".join(cells) + " |")
                        if i == 0:
                            md_rows.append("|" + "|".join(["---"] * len(cells)) + "|")
                    pages.append(ExtractedPage(
                        page_number=page_num + 1,
                        content="\n".join(md_rows),
                        content_type="table",
                        metadata={"page_number": page_num + 1},
                    ))

            # Extract text
            text = plumber_page.extract_text() or ""

            if len(text.strip()) < 50:
                # Scanned — rasterize + OCR
                pdfium_page = doc[page_num]
                bitmap = pdfium_page.render(scale=2)
                pil_image = bitmap.to_pil()
                text = pytesseract.image_to_string(pil_image, config="--psm 6")

            if text.strip():
                pages.append(ExtractedPage(
                    page_number=page_num + 1,
                    content=text.strip(),
                    content_type="text",
                    metadata={"page_number": page_num + 1},
                ))

        plumber_doc.close()

    except Exception as e:
        # Fallback: basic text extraction
        pages.append(ExtractedPage(
            page_number=1,
            content=f"[Extraction error: {e}]",
            content_type="text",
            metadata={},
        ))

    return pages
