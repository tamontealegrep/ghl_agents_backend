"""Output review: every message is checked against the agent's output rules and forbidden words before it is sent."""

from __future__ import annotations

from types import SimpleNamespace

from agent_runtime.runtime.graph_builder import _make_render_say
from agent_runtime.runtime.output_review import OUTPUT_REVIEW_ENV, OutputReview, output_review_enabled

_WORDS = [
    {"word": "alquil*", "use_instead": "gestación subrogada", "reason": "no se alquila"},
    {"word": "sueldo", "use_instead": "apoyo para los gastos"},
    {"word": "a cambio de"},
    {"word": "pesos"},
    {"word": "reclut*"},
    {"word": "empleo", "reason": "el programa no es un trabajo"},
]
_RULES = ["Nunca hables de dinero.", "Nunca presentes la gestación como un trabajo."]


class _ScriptedLLM:
    """Answers each call from a list, and records the prompts. The last answer repeats."""

    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def _review() -> OutputReview:
    """The review of a test agent; the caller has set `GLOBAL_ROUTER_OUTPUT_REVIEW`."""
    review = OutputReview.from_artifact(SimpleNamespace(output_rules=_RULES, forbidden_words=_WORDS))
    assert review is not None
    return review


def test_review_off_by_default(monkeypatch):
    """Review is off unless the environment turns it on."""
    artifact = SimpleNamespace(output_rules=_RULES, forbidden_words=_WORDS)
    monkeypatch.delenv(OUTPUT_REVIEW_ENV, raising=False)
    assert output_review_enabled() is False
    assert OutputReview.from_artifact(artifact) is None
    for value in ("true", "1", "yes", "on", "TRUE"):
        monkeypatch.setenv(OUTPUT_REVIEW_ENV, value)
        assert OutputReview.from_artifact(artifact) is not None
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "false")
    assert OutputReview.from_artifact(artifact) is None


def test_no_rules_no_review(monkeypatch):
    """An agent without rules or words is never reviewed."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    assert OutputReview.from_artifact(SimpleNamespace(output_rules=[], forbidden_words=[])) is None
    assert OutputReview.from_artifact(SimpleNamespace()) is None


def test_forbidden_words_flexible_match(monkeypatch):
    """Forbidden words match ignoring case, accents and endings."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    review = _review()
    hit = lambda text: sorted(t.word for t in review.find_forbidden(text))  # noqa: E731
    assert hit("Esto NO es un Alquiler de vientre.") == ["alquil*"]
    assert hit("Se alquilan vientres") == ["alquil*"]
    assert hit("Recibirá un SUELDO mensual") == ["sueldo"]
    assert hit("Se hace a cambio   de nada") == ["a cambio de"]  # extra spaces inside a phrase
    assert hit("Reclutamos gestantes") == ["reclut*"]
    # whole words only: the stem of a longer, unrelated word is not a hit
    assert hit("Los sueldos") == []
    assert hit("Estamos en la gestación subrogada") == []


def test_compliant_message_unchanged(monkeypatch):
    """A message that follows the rules goes out unchanged."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    llm = _ScriptedLLM("OK")
    assert (
        _review().review(llm, "Con gusto le cuento cómo es el proceso.")
        == "Con gusto le cuento cómo es el proceso."
    )
    assert len(llm.prompts) == 1
    # the prompt carries the rules, the words and the message
    prompt = llm.prompts[0]
    assert "Nunca hables de dinero." in prompt and '"alquil*" -> prefer: gestación subrogada' in prompt
    assert "Con gusto le cuento" in prompt


def test_rule_breaking_message_rewritten(monkeypatch):
    """A message that breaks a rule is rewritten."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    llm = _ScriptedLLM("REWRITE\nCon gusto le cuento cómo es el proceso.")
    out = _review().review(llm, "Le cuento cómo ganar un sueldo con el proceso.", language="Spanish")
    assert out == "Con gusto le cuento cómo es el proceso."
    assert "written in Spanish" in llm.prompts[0]
    assert '"sueldo"' in llm.prompts[0]  # the word check tells the model what it found


def test_bad_rewrite_retried(monkeypatch):
    """A rewrite that still uses a forbidden word is tried again."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    llm = _ScriptedLLM("REWRITE\nEs un alquiler de vientre.", "REWRITE\nEs una gestación subrogada.")
    out = _review().review(llm, "Es un negocio de alquiler de vientres.")
    assert out == "Es una gestación subrogada."
    assert len(llm.prompts) == 2
    assert "still contains listed words" in llm.prompts[1]


def test_failing_rewrites_still_send(monkeypatch):
    """When rewrites keep failing the message still goes out."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    llm = _ScriptedLLM("REWRITE\nSe paga un sueldo.")
    out = _review().review(llm, "Hay un sueldo.")
    assert out == "Se paga un sueldo."  # the message is never held back
    assert len(llm.prompts) == 2


def test_ok_from_the_model_is_final_even_when_a_listed_word_is_present(monkeypatch):
    """Words are judged by how they are used: answering, quoting or denying is not a violation."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    review = _review()
    for text in (
        "Claro, puede mantener su empleo mientras gesta.",
        "No es un alquiler de vientre ni un sueldo: es un apoyo para los gastos.",
    ):
        assert review.find_forbidden(text)  # the word is there...
        llm = _ScriptedLLM("OK")
        assert review.review(llm, text) == text  # ...and the model's judgment stands
        assert len(llm.prompts) == 1
        assert "Judge whether the message CONVEYS that idea, never whether a" in llm.prompts[0]


def test_rewrite_losing_token_discarded(monkeypatch):
    """A rewrite that loses a code-written value is discarded."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    text = "Tengo estas fechas disponibles:\n<LIST_1>"
    llm = _ScriptedLLM("REWRITE\nTengo fechas disponibles.")
    assert _review().review(llm, text, required_tokens=["<LIST_1>"]) == text
    # kept: accepted
    llm = _ScriptedLLM("REWRITE\nHay fechas:\n<LIST_1>")
    assert (
        _review().review(llm, "Hay un sueldo en estas fechas:\n<LIST_1>", required_tokens=["<LIST_1>"])
        == "Hay fechas:\n<LIST_1>"
    )


def test_rewrite_adding_question_discarded(monkeypatch):
    """A rewrite that adds a question is discarded."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    text = "Le cuento el proceso."
    llm = _ScriptedLLM("REWRITE\nLe cuento el proceso. ¿Quiere saber más?")
    assert _review().review(llm, text) == text


def test_unusable_answer_keeps_message(monkeypatch):
    """An unusable model answer leaves the message alone."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    text = "Le cuento el proceso."
    assert _review().review(_ScriptedLLM(""), text) == text
    assert _review().review(_ScriptedLLM("REWRITE"), text) == text


def test_say_reviews_paraphrase(monkeypatch):
    """The paraphrase is reviewed and code-written values are kept."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    review = _review()

    class _Client:
        prompts: list[str] = []

        def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
            self.prompts.append(prompt)
            if prompt.startswith("You are the final compliance reviewer"):
                assert "<LIST_1>" in prompt  # reviewed behind its token, never as the dates themselves
                return "REWRITE\nTengo estas fechas para usted:\n<LIST_1>"
            return "Tengo estas fechas con sueldo:\n<LIST_1>"  # the paraphrase

    render_say = _make_render_say(_Client(), review)
    out = render_say("SC_DAYS", ["Tengo fechas:\n🗓️ Viernes 13 de noviembre\n └─ Tarde"], False, "es", {})
    assert out == "Tengo estas fechas para usted:\n🗓️ Viernes 13 de noviembre\n └─ Tarde"


def test_say_skips_review_when_off():
    """Nothing is reviewed when review is off."""
    client = _ScriptedLLM("Hola, ¿cómo está?")
    render_say = _make_render_say(client, None)
    assert render_say("N", ["Hola, ¿cómo está?"], False, "es", {}) == "Hola, ¿cómo está?"
    assert not any(p.startswith("You are the final compliance reviewer") for p in client.prompts)


def test_verbatim_never_rewritten(monkeypatch, caplog):
    """Verbatim copy is never rewritten and costs no call."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    llm = _ScriptedLLM("REWRITE\nOtra cosa")
    render_say = _make_render_say(llm, _review())
    with caplog.at_level("WARNING"):
        out = render_say("N", ["Aprobado: un sueldo."], True, "es", {})
    assert out == "Aprobado: un sueldo."
    assert llm.prompts == []
    assert "listed word" in caplog.text


def test_verdict_line_decides(monkeypatch):
    """The verdict line after the analysis decides."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    review = _review()
    text = "Claro, puede mantener su empleo."
    ok = '- "empleo": ANSWER (it answers her question)\nVERDICT: OK'
    assert review.review(_ScriptedLLM(ok), text) == text
    bad = '- "sueldo": PROGRAM (it offers a salary)\nVERDICT: REWRITE\nLe explicamos el proceso.'
    assert review.review(_ScriptedLLM(bad), "Tendrá un sueldo.") == "Le explicamos el proceso."
    inline = "VERDICT: REWRITE Le explicamos el proceso."
    assert review.review(_ScriptedLLM(inline), "Tendrá un sueldo.") == "Le explicamos el proceso."
    # the analysis may mention REWRITE; only the verdict line counts
    tricky = '- "x": PROGRAM, so a rewrite would be needed\nVERDICT: OK'
    assert review.review(_ScriptedLLM(tricky), text) == text


def test_contact_message_and_label(monkeypatch):
    """The contact message is used and a copied label is dropped."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    review = _review()
    llm = _ScriptedLLM("VERDICT: REWRITE\nMESSAGE: Le explicamos el proceso.")
    out = review.review(llm, "Tendrá un sueldo.", asked="¿Cuánto me pagan?")
    assert out == "Le explicamos el proceso."  # a copied "MESSAGE:" label is dropped
    assert "WHAT THE CONTACT JUST WROTE" in llm.prompts[0] and "¿Cuánto me pagan?" in llm.prompts[0]
    llm = _ScriptedLLM("OK")
    review.review(llm, "Hola.")
    assert "WHAT THE CONTACT JUST WROTE" not in llm.prompts[0]


def test_say_passes_contact_message(monkeypatch):
    """The contact's message is handed to the review."""
    monkeypatch.setenv(OUTPUT_REVIEW_ENV, "true")
    seen: list[str] = []

    class _Client:
        def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
            seen.append(prompt)
            return "VERDICT: OK" if prompt.startswith("You are the final compliance reviewer") else "Hola."

    render_say = _make_render_say(_Client(), _review())
    render_say("N", ["Hola."], False, "es", {}, user_message="¿Puedo mantener mi empleo?")
    assert any("¿Puedo mantener mi empleo?" in p for p in seen)
