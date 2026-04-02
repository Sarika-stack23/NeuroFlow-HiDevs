"""CSV extractor — small files as markdown table, large as statistical summary."""
from __future__ import annotations
from pipelines.ingestion.extractors.pdf_extractor import ExtractedPage


def extract_csv(file_path: str) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    try:
        import pandas as pd
        df = pd.read_csv(file_path)

        if len(df) <= 1000:
            md = df.to_markdown(index=False)
            pages.append(ExtractedPage(1, md or "", "table", {"row_count": len(df)}))
        else:
            # Statistical summary
            summary_lines = [f"CSV with {len(df)} rows, {len(df.columns)} columns.\n"]
            for col in df.columns:
                if pd.api.types.is_numeric_dtype(df[col]):
                    summary_lines.append(
                        f"- {col} (numeric): min={df[col].min():.2f}, max={df[col].max():.2f}, mean={df[col].mean():.2f}"
                    )
                else:
                    top5 = df[col].value_counts().head(5).to_dict()
                    summary_lines.append(f"- {col} (categorical): top values = {top5}")
            pages.append(ExtractedPage(1, "\n".join(summary_lines), "text", {}))

            # Chunked rows
            for i in range(0, min(len(df), 5000), 100):
                chunk_md = df.iloc[i:i + 100].to_markdown(index=False)
                pages.append(ExtractedPage(
                    page_number=len(pages) + 1,
                    content=chunk_md or "",
                    content_type="table",
                    metadata={"row_start": i, "row_end": i + 100},
                ))
    except Exception as e:
        pages.append(ExtractedPage(1, f"[CSV error: {e}]", "text", {}))
    return pages
