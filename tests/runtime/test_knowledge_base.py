"""
Unit tests for agent_runtime.runtime.knowledge_base.

    The model is a small fake; nothing here touches the network.
"""

from __future__ import annotations

import pytest

from agent_runtime.runtime.knowledge_base import (
    NO_ANSWER,
    KnowledgeBaseTooLarge,
    KnowledgeChunk,
    MarkdownKnowledgeBase,
    RAGKnowledgeBase,
    answer_from_knowledge,
    build_answer_prompt,
    make_knowledge_tool_executor,
    unsupported_numbers,
)
from agent_runtime.runtime.llm_client import LLMContext

SERVICES = """# Servicios

## Fertilización in vitro
Tratamiento de 3 etapas. La primera consulta dura 45 minutos.

## Subrogación
Programa para parejas que no pueden gestar.
"""


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        self.prompts.append(prompt)
        return self.reply

    def extract_structured(self, prompt, json_schema):
        return {}


def _ctx(message: str = "¿Cuánto dura la primera consulta?", policies: list[str] | None = None) -> LLMContext:
    return LLMContext(
        slots={}, history=["agent: ¿Tienes alguna duda?"], last_user_message=message, policies=policies or []
    )


class StaticRAG(RAGKnowledgeBase):
    def __init__(self, found: list[KnowledgeChunk], **kwargs) -> None:
        super().__init__(**kwargs)
        self.found = found
        self.calls: list[tuple[str, int, str | None]] = []

    def _search(self, query, k, language):
        self.calls.append((query, k, language))
        return self.found


# --- MarkdownKnowledgeBase ---------------------------------------------------


def test_markdown_returns_whole_document():
    """A markdown base returns the whole document for any query."""
    kb = MarkdownKnowledgeBase(SERVICES, name="servicios.md")
    first = kb.retrieve("una pregunta")
    second = kb.retrieve("otra pregunta distinta")
    assert len(first) == 1
    assert first[0].text == SERVICES.strip()
    assert first[0].source == "servicios.md"
    assert first == second


def test_markdown_rejects_empty_document():
    """An empty markdown document is rejected."""
    with pytest.raises(ValueError):
        MarkdownKnowledgeBase("   \n ")


def test_markdown_rejects_oversize():
    """A document over the size limit is rejected."""
    with pytest.raises(KnowledgeBaseTooLarge):
        MarkdownKnowledgeBase("palabra " * 500, max_tokens=100)


def test_markdown_from_file(tmp_path):
    """A markdown base can be loaded from a file."""
    path = tmp_path / "servicios.md"
    path.write_text(SERVICES, encoding="utf-8")
    kb = MarkdownKnowledgeBase.from_file(path)
    assert kb.name == "servicios.md"
    assert "Subrogación" in kb.retrieve("x")[0].text


# --- RAGKnowledgeBase --------------------------------------------------------


def test_rag_base_cannot_be_used_directly():
    """The RAG base class cannot be used directly."""
    with pytest.raises(TypeError):
        RAGKnowledgeBase()  # type: ignore[abstract]


def test_rag_filters_orders_caps():
    """RAG drops weak matches, orders best first and caps at top_k."""
    found = [
        KnowledgeChunk("débil", score=0.1),
        KnowledgeChunk("medio", score=0.5),
        KnowledgeChunk("fuerte", score=0.9),
        KnowledgeChunk("bueno", score=0.7),
    ]
    kb = StaticRAG(found, top_k=2, min_score=0.3)
    result = kb.retrieve("pregunta", language="Spanish")
    assert [c.text for c in result] == ["fuerte", "bueno"]
    assert kb.calls == [("pregunta", 2, "Spanish")]


def test_rag_blank_query_skips_the_search():
    """A blank query skips the RAG search."""
    kb = StaticRAG([KnowledgeChunk("x")])
    assert kb.retrieve("  ") == []
    assert kb.calls == []


def test_rag_rejects_invalid_top_k():
    """An invalid top_k is rejected."""
    with pytest.raises(ValueError):
        StaticRAG([], top_k=0)


# --- prompt ------------------------------------------------------------------


def test_prompt_reference_first():
    """The prompt keeps the reference text before everything that changes."""
    kb = MarkdownKnowledgeBase(SERVICES)
    ctx = _ctx(policies=["No des consejo clínico."])
    prompt = build_answer_prompt(kb.retrieve("q"), "¿Cuánto dura?", ctx, "Spanish")
    reference_end = prompt.index("=== END OF REFERENCE TEXT ===")
    assert prompt.index("No des consejo clínico.") < prompt.index("=== REFERENCE TEXT ===")
    assert reference_end < prompt.index("agent: ¿Tienes alguna duda?")
    assert reference_end < prompt.index("¿Cuánto dura?")
    assert reference_end < prompt.index("Write the answer in Spanish.")


def test_prompt_answers_statements_of_need():
    """The prompt tells the model to answer a statement of need like a question."""
    kb = MarkdownKnowledgeBase(SERVICES)
    prompt = build_answer_prompt(kb.retrieve("q"), "I want to adopt a baby", _ctx(), "English")
    rules = prompt[: prompt.index("=== REFERENCE TEXT ===")]
    assert "may state something they want or need" in rules
    assert "including when it says the company does not" in rules
    assert "describe their situation" in rules


def test_prompt_prefix_is_stable():
    """The prompt prefix is identical across questions."""
    kb = MarkdownKnowledgeBase(SERVICES)
    chunks = kb.retrieve("q")
    one = build_answer_prompt(chunks, "pregunta uno", _ctx("pregunta uno"), "Spanish")
    two = build_answer_prompt(chunks, "pregunta dos", _ctx("pregunta dos"), "English")
    marker = "=== END OF REFERENCE TEXT ==="
    assert one[: one.index(marker)] == two[: two.index(marker)]


# --- answer_from_knowledge ---------------------------------------------------


def test_answers_from_the_document():
    """The answer comes from the document."""
    llm = FakeLLM("La primera consulta dura 45 minutos.")
    answer = answer_from_knowledge(llm, MarkdownKnowledgeBase(SERVICES), _ctx(), language_name="Spanish")
    assert answer == "La primera consulta dura 45 minutos."
    assert len(llm.prompts) == 1


def test_none_when_no_answer():
    """None is returned when the model says there is no answer."""
    llm = FakeLLM(NO_ANSWER)
    assert answer_from_knowledge(llm, MarkdownKnowledgeBase(SERVICES), _ctx()) is None


def test_none_for_empty_reply():
    """None is returned for an empty reply."""
    assert answer_from_knowledge(FakeLLM("  "), MarkdownKnowledgeBase(SERVICES), _ctx()) is None


def test_none_for_invented_number():
    """None is returned when the answer invents a number."""
    llm = FakeLLM("La primera consulta dura 30 minutos.")
    assert answer_from_knowledge(llm, MarkdownKnowledgeBase(SERVICES), _ctx()) is None


def test_user_number_allowed():
    """A number the user said may appear in the answer."""
    llm = FakeLLM("Sí, con 2 personas es posible.")
    ctx = _ctx("¿Pueden ir 2 personas?")
    assert (
        answer_from_knowledge(llm, MarkdownKnowledgeBase(SERVICES), ctx) == "Sí, con 2 personas es posible."
    )


def test_none_without_retrieval():
    """With nothing retrieved the model is not called."""
    llm = FakeLLM("algo")
    rag = StaticRAG([], top_k=3)
    assert answer_from_knowledge(llm, rag, _ctx()) is None
    assert llm.prompts == []


def test_none_for_blank_question():
    """None is returned for a blank question."""
    llm = FakeLLM("algo")
    assert answer_from_knowledge(llm, MarkdownKnowledgeBase(SERVICES), _ctx("  ")) is None
    assert llm.prompts == []


def test_explicit_question_wins():
    """An explicit question overrides the latest message."""
    llm = FakeLLM("Es un programa para parejas.")
    answer_from_knowledge(
        llm, MarkdownKnowledgeBase(SERVICES), _ctx("sí, y además..."), "¿Qué es la subrogación?"
    )
    assert "¿Qué es la subrogación?" in llm.prompts[0]


def test_unsupported_numbers_by_digits():
    """Unsupported numbers are compared by their digits."""
    assert unsupported_numbers("Cuesta 1.000", ["Precio: 1,000"]) == []
    assert unsupported_numbers("Cuesta 2000", ["Precio: 1,000"]) == ["2000"]


# --- kb_answer tool ----------------------------------------------------------


def test_tool_returns_contract_outputs():
    """The tool returns the contract's outputs."""
    llm = FakeLLM("La primera consulta dura 45 minutos.")
    tool = make_knowledge_tool_executor(llm, MarkdownKnowledgeBase(SERVICES))
    result = tool(question="¿Cuánto dura la primera consulta?", language="Spanish")
    assert result == {"kb_answer": "La primera consulta dura 45 minutos.", "kb_found": True}
    assert "Write the answer in Spanish." in llm.prompts[0]


def test_tool_not_found_is_empty():
    """A question with no answer returns an empty answer and found false."""
    tool = make_knowledge_tool_executor(FakeLLM(NO_ANSWER), MarkdownKnowledgeBase(SERVICES))
    assert tool(question="¿Tienen sede en Marte?") == {"kb_answer": "", "kb_found": False}


def test_tool_language_optional():
    """The language input is optional."""
    llm = FakeLLM("Es un programa para parejas.")
    tool = make_knowledge_tool_executor(llm, MarkdownKnowledgeBase(SERVICES))
    assert tool(question="¿Qué es la subrogación?")["kb_found"] is True
    assert "Write the answer in" not in llm.prompts[0]


def test_tool_history_after_reference():
    """The recent conversation is placed after the reference text."""
    llm = FakeLLM("Dura entre 20 y 30 días.")
    tool = make_knowledge_tool_executor(llm, MarkdownKnowledgeBase(SERVICES))
    tool(question="¿y cuánto dura?", history="agent: ¿Qué te interesa?\nuser: la fiv\nuser: ¿y cuánto dura?")
    prompt = llm.prompts[0]
    assert prompt.index("=== END OF REFERENCE TEXT ===") < prompt.index("user: la fiv")
    assert "may refer to earlier messages" in prompt


def test_tool_history_as_list():
    """History may be given as a list."""
    llm = FakeLLM("Es un programa para parejas.")
    tool = make_knowledge_tool_executor(llm, MarkdownKnowledgeBase(SERVICES))
    tool(question="¿y eso?", history=["user: háblame de subrogación", "agent: Es un proceso…"])
    assert "user: háblame de subrogación" in llm.prompts[0]
