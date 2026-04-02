"""Build prompts for RAG generation based on query type."""
from providers.base import ChatMessage

BASE_SYSTEM = """You are a precise research assistant. Answer the user's question using ONLY the provided context.
If the context does not contain enough information to answer fully, say so explicitly.
For every factual claim, include a citation in the format [Source N].
Do not introduce information not present in the context."""

QUERY_TYPE_ADDITIONS = {
    "factual": "Provide a direct, concise answer. If multiple sources agree, cite all of them.",
    "analytical": "Analyze and synthesize across the provided sources. Identify agreements and contradictions.",
    "comparative": "Organize your response as a structured comparison. Use a table if appropriate.",
    "procedural": "Provide numbered steps. Each step must be cited.",
}


def build_prompt(
    query: str,
    context: str,
    query_type: str = "factual",
) -> list[ChatMessage]:
    addition = QUERY_TYPE_ADDITIONS.get(query_type, QUERY_TYPE_ADDITIONS["factual"])
    system = f"{BASE_SYSTEM}\n\n{addition}"
    user = f"<context>\n{context}\n</context>\n\nQuestion: {query}"
    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=user),
    ]
