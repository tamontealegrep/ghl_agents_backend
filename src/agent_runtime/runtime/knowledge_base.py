"""
Knowledge bases an agent can answer open questions from.

    The agent's strict flow answers closed questions from FAQs (fixed, exact text). A
    knowledge base covers the rest: open questions that need the company's own
    information (which services exist, who they are for, how they work).

    Two implementations share one contract, `KnowledgeBase.retrieve`:

    - `MarkdownKnowledgeBase`: one Markdown document, returned whole on every call. Right for
      a small, stable document (a services description of a few pages). The document leads the
      prompt (see `build_answer_prompt`) so the provider's prompt cache can reuse it.
    - `RAGKnowledgeBase`: the base of a retrieval-backed store (vector or keyword search). It
      returns only the few passages that match the question. Subclasses supply `_search`.

    `answer_from_knowledge` is the one place that turns retrieved passages into a reply, so
    swapping the Markdown document for a retrieval store changes nothing else.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent_runtime.runtime.llm_client import LLMClient, LLMContext

KNOWLEDGE_TOOL_NAME = "kb_answer"
"""The tool contract the runtime answers itself, from the agent's knowledge base, instead of over HTTP."""

NO_ANSWER = "NO_ANSWER"
"""What the model replies when the passages do not answer the question."""

DEFAULT_MAX_DOCUMENT_TOKENS = 24_000
"""A document larger than this is refused by `MarkdownKnowledgeBase`: every question would pay for all of it."""

_CHARS_PER_TOKEN = 4
"""Rough ratio used to estimate size without a tokenizer."""

_LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese"}


class KnowledgeBaseTooLarge(ValueError):
    """The document is too large to send whole; use a `RAGKnowledgeBase` instead."""


@dataclass(frozen=True)
class KnowledgeChunk:
    """A passage of the knowledge base, with where it came from and how well it matched."""

    text: str
    source: str = ""
    score: float = 1.0


class KnowledgeBase(Protocol):
    """The only operation the runtime needs from a knowledge base."""

    def retrieve(self, query: str, *, language: str | None = None) -> list[KnowledgeChunk]:
        """Return the passages relevant to `query`, best first. Empty when nothing is relevant."""
        ...


def estimate_tokens(text: str) -> int:
    """Approximate token count (about four characters per token)."""
    return len(text) // _CHARS_PER_TOKEN


class MarkdownKnowledgeBase:
    """
A single Markdown document handed to the model whole.

    `retrieve` ignores the query and always returns the same one chunk, so the prompt prefix is
    identical from one question to the next and the provider can cache it. The size limit
    keeps this from being used past the point where a retrieval store is the better tool.
    """

    def __init__(
        self,
        text: str,
        *,
        name: str = "knowledge",
        max_tokens: int = DEFAULT_MAX_DOCUMENT_TOKENS,
    ) -> None:
        document = text.strip()
        if not document:
            raise ValueError("The knowledge document is empty.")
        size = estimate_tokens(document)
        if size > max_tokens:
            raise KnowledgeBaseTooLarge(
                f"Knowledge document {name!r} is about {size} tokens (limit {max_tokens}). "
                "Send it whole only while it is small; use a RAGKnowledgeBase for larger content."
            )
        self.name = name
        self.text = document
        self._chunks = [KnowledgeChunk(text=document, source=name)]

    @classmethod
    def from_file(cls, path: str | Path, *, max_tokens: int = DEFAULT_MAX_DOCUMENT_TOKENS) -> "MarkdownKnowledgeBase":
        file = Path(path)
        return cls(file.read_text(encoding="utf-8"), name=file.name, max_tokens=max_tokens)

    @property
    def approx_tokens(self) -> int:
        return estimate_tokens(self.text)

    def retrieve(self, query: str, *, language: str | None = None) -> list[KnowledgeChunk]:
        return list(self._chunks)


class RAGKnowledgeBase(ABC):
    """
Base of a retrieval-backed knowledge base. Not usable on its own.

    A subclass implements `_search` (vector search, BM25, a hybrid, or a call to a search
    service) and returns scored passages. `retrieve` applies the shared policy on top: drop
    weak matches, order best first, keep `top_k`. The runtime calls only `retrieve`, so a
    subclass slots in where `MarkdownKnowledgeBase` was.
    """

    def __init__(self, *, top_k: int = 4, min_score: float = 0.0) -> None:
        if top_k < 1:
            raise ValueError("top_k must be at least 1.")
        self.top_k = top_k
        self.min_score = min_score

    @abstractmethod
    def _search(self, query: str, k: int, language: str | None) -> list[KnowledgeChunk]:
        """Return up to `k` candidate passages for `query`, with scores. Order is not assumed."""

    def retrieve(self, query: str, *, language: str | None = None) -> list[KnowledgeChunk]:
        if not query.strip():
            return []
        found = self._search(query, self.top_k, language)
        kept = [chunk for chunk in found if chunk.score >= self.min_score]
        kept.sort(key=lambda chunk: chunk.score, reverse=True)
        return kept[: self.top_k]


def build_answer_prompt(chunks: list[KnowledgeChunk], question: str, ctx: LLMContext, language_name: str | None) -> str:
    """
The prompt that answers `question` from `chunks`.

    Everything that is the same from one question to the next (rules, house policies, the
    reference text) comes first; everything that changes (conversation, question, language)
    comes last. Providers cache by prompt prefix, so this order is what lets a whole Markdown
    document be sent on every question without paying full price for it each time.
    """
    policy_block = f"House rules:\n{chr(10).join(ctx.policies)}\n\n" if ctx.policies else ""
    reference = "\n\n".join(chunk.text for chunk in chunks)
    language_line = f"Write the answer in {language_name}.\n" if language_name else ""
    return (
        "You answer a customer's question on behalf of a company, using only the reference "
        "text below.\n"
        "Rules:\n"
        "- The question may refer to earlier messages (for example 'and how long does that take?'): use "
        "the recent conversation only to understand what it refers to.\n"
        "- The customer's message may state something they want or need instead of asking (for example "
        "'I want to adopt a baby'): answer whether the reference text says the company offers it, "
        "including when it says the company does not. It may also describe their situation (for example "
        "'we are a same-sex couple'): say what the reference text offers for that situation.\n"
        "- Use only facts stated in the reference text. Never add services, prices, dates, "
        "numbers, conditions or promises that are not there.\n"
        f"- If the reference text does not fully answer the question, reply exactly {NO_ANSWER} "
        "and nothing else.\n"
        "- Give no medical, legal or financial advice.\n"
        "- Be brief and conversational: two to four sentences. Do not ask the user anything, do "
        "not offer to schedule, and do not mention the reference text.\n\n"
        f"{policy_block}"
        "=== REFERENCE TEXT ===\n"
        f"{reference}\n"
        "=== END OF REFERENCE TEXT ===\n\n"
        f"{ctx.block()}"
        f"The customer's question: {question!r}\n"
        f"{language_line}"
        f"Reply with the answer, or {NO_ANSWER}."
    )


_NUMBER_RE = re.compile(r"\d+(?:[.,:]\d+)*")


def _digits(number: str) -> str:
    return re.sub(r"\D", "", number)


def unsupported_numbers(answer: str, sources: list[str]) -> list[str]:
    """Numbers in `answer` that appear in none of `sources` (compared by digits, so 1,000 matches 1.000)."""
    allowed = {_digits(n) for text in sources for n in _NUMBER_RE.findall(text)}
    return [n for n in _NUMBER_RE.findall(answer) if _digits(n) not in allowed]


def answer_from_knowledge(
    llm_client: LLMClient,
    knowledge_base: KnowledgeBase,
    ctx: LLMContext,
    question: str | None = None,
    *,
    language_name: str | None = None,
) -> str | None:
    """
Answer `question` from `knowledge_base`, or return None when it cannot be answered safely.

    None means the caller should fall back (hand the user to an advisor): nothing was
    retrieved, the model said the text does not answer, or the answer states a number the
    retrieved text does not contain. `question` defaults to the user's latest message.
    """
    asked = (question if question is not None else ctx.last_user_message).strip()
    if not asked:
        return None
    chunks = knowledge_base.retrieve(asked, language=language_name)
    if not chunks:
        return None
    reply = llm_client.complete(build_answer_prompt(chunks, asked, ctx, language_name)).strip()
    if not reply or reply.upper().startswith(NO_ANSWER):
        return None
    if unsupported_numbers(reply, [chunk.text for chunk in chunks] + [asked]):
        return None
    return reply


def make_knowledge_tool_executor(
    llm_client: LLMClient,
    knowledge_base: KnowledgeBase,
    *,
    policies: list[str] | None = None,
):
    """
The in-process executor of the `kb_answer` tool.

    A flow answers an open question with an `action` node that runs `kb_answer` (inputs
    `question` plus the optional `language` and `history`; outputs `kb_answer` and `kb_found`), so the knowledge
    base needs no new kind of node: it is one more tool, served here instead of over HTTP. Like
    the HTTP executor it takes keyword arguments and returns a dict keyed by the contract's outputs.
    """

    def call(**kwargs) -> dict[str, object]:
        question = str(kwargs.get("question") or "").strip()
        language = str(kwargs.get("language") or "").strip() or None
        history = kwargs.get("history") or []
        if isinstance(history, str):
            history = history.splitlines()
        ctx = LLMContext(
            slots={}, history=[str(line) for line in history if str(line).strip()],
            last_user_message=question, policies=list(policies or []),
        )
        answer = answer_from_knowledge(llm_client, knowledge_base, ctx, question, language_name=language)
        return {"kb_answer": answer or "", "kb_found": answer is not None}

    return call
