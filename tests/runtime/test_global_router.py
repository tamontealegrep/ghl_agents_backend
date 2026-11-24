"""
Unit tests for agent_runtime.runtime.global_router — the interrupt-loop mechanism.

    Uses a fake LLMClient (canned text responses) — no real model call.
"""

from __future__ import annotations

import pytest

from agent_runtime.runtime.global_router import (
    UNANSWERED_QUESTION_ACK,
    handle_global_router_match,
    has_unanswered_side_question,
    match_global_router,
)
from agent_runtime.runtime.llm_client import LLMContext
from agent_runtime.targets.langgraph.graph_renderer import (
    FaqNode,
    GlobalRouterDefinition,
    GraphEdge,
    GraphNode,
)


@pytest.fixture(autouse=True)
def _respect_filter_off_by_default(monkeypatch):
    """The router tests count model calls: the respect filter (one more call) is switched on only where tested."""
    monkeypatch.setenv("GLOBAL_ROUTER_RESPECT_FILTER", "false")


class _FakeLLMClient:
    """
    Replies consumed in order — one per `complete()` call. The two-stage

        router (2026-09-17) makes up to two calls per `match_global_router`
            invocation (Stage 1: CONTINUE/INTERRUPT, Stage 2: candidate index/NONE,
            only reached when Stage 1 says INTERRUPT), so a single fixed reply no
            longer models every caller.
    """

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.temperatures: list[float] = []

    def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        self.prompts.append(prompt)
        self.temperatures.append(temperature)
        return self.replies.pop(0)

    def extract_structured(self, prompt, json_schema):
        raise NotImplementedError


def _ctx(
    last_user_message: str,
    *,
    pending_question: str = "",
    history: list[str] | None = None,
    slots: dict | None = None,
) -> LLMContext:
    """
    Build the `LLMContext` `match_global_router`/`handle_global_router_match` now take

        (2026-09-17) — every runtime LLM decision shares this one type instead of each call
            site's own hand-picked parameter list.

        Parameters:
            last_user_message: Description.
            pending_question: Description.
            history: Description.
            slots: Description.

        Returns:
            The result.
    """
    return LLMContext(
        slots=slots or {},
        history=history or [],
        last_user_message=last_user_message,
        pending_question=pending_question,
    )


def _handler_node(node_id: str = "H_REPEAT", **overrides) -> GraphNode:
    data = {"node_id": node_id, "node_type": "message", "trigger": ["repeat that"], "say": ["Handled."]}
    data.update(overrides)
    return GraphNode(**data)


def _faq_node(faq_id: str = "FAQ_HOURS", **overrides) -> FaqNode:
    data = {"faq_id": faq_id, "match": ["what are your hours"], "say": ["9 to 5."]}
    data.update(overrides)
    return FaqNode(**data)


# ---------------------------------------------------------------------------
# match_global_router — two stages (2026-09-17): Stage 1 (_continues_the_flow)
# decides CONTINUE/INTERRUPT; Stage 2 (_match_candidate) only runs when Stage
# 1 says INTERRUPT, and picks which candidate.
# ---------------------------------------------------------------------------


def test_no_candidates_skips_model():
    """With no candidates the router returns None without calling the model."""
    client = _FakeLLMClient(replies=[])
    router = GlobalRouterDefinition(handlers=[], faqs=[])
    assert match_global_router(client, router, _ctx("anything")) is None
    assert client.prompts == []


def test_stage_one_continue_returns_none_without_a_second_call():
    """
    The common case: one call, not two.

        Returns:
            None.
    """
    client = _FakeLLMClient(replies=["CONTINUE"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    assert match_global_router(client, router, _ctx("my name is Alex")) is None
    assert len(client.prompts) == 1


def test_stage2_number_selects_candidate():
    """A numeric stage-2 reply selects the matching candidate."""
    client = _FakeLLMClient(replies=["INTERRUPT", "0"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    match = match_global_router(client, router, _ctx("can you repeat that"))
    assert match is not None
    kind, node = match
    assert kind == "handler"
    assert node.node_id == "H_REPEAT"
    assert len(client.prompts) == 2


def test_stage2_none_reply():
    """A NONE stage-2 reply gives no match."""
    client = _FakeLLMClient(replies=["INTERRUPT", "NONE"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    assert match_global_router(client, router, _ctx("something ambiguous")) is None


def test_language_change_comes_first():
    """The language-change handler is tried before FAQs and the continuation check."""
    language_handler = _handler_node(
        node_id="H_LANG_CHANGE",
        trigger=["I don't speak English", "no hablo ingles"],
    )
    router = GlobalRouterDefinition(handlers=[language_handler], faqs=[_faq_node()])
    client = _FakeLLMClient(replies=["LANGUAGE_CHANGE"])

    # Rule-based detection triggers on "no hablo ingles"
    match = match_global_router(
        client, router, _ctx("no hablo ingles", pending_question="Can you travel to Bogotá?")
    )
    assert match is not None
    assert match[0] == "handler"

    # LLM fallback path when message is not rule-matched
    client2 = _FakeLLMClient(replies=["LANGUAGE_CHANGE"])
    match2 = match_global_router(
        client2, router, _ctx("unrecognized phrase", pending_question="Can you travel to Bogotá?")
    )
    assert match2 is not None
    assert len(client2.prompts) == 1
    assert "LANGUAGE PRIORITY" in client2.prompts[0]
    assert "even if it also matches another handler or FAQ" in client2.prompts[0]


def test_stage2_out_of_range_is_none():
    """An out-of-range stage-2 number gives no match."""
    client = _FakeLLMClient(replies=["INTERRUPT", "5"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    assert match_global_router(client, router, _ctx("whatever")) is None


def test_stage2_selects_faq_by_index():
    """Stage 2 can select an FAQ candidate by index."""
    client = _FakeLLMClient(replies=["INTERRUPT", "1"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[_faq_node()])
    match = match_global_router(client, router, _ctx("what are your hours"))
    kind, node = match
    assert kind == "faq"
    assert node.faq_id == "FAQ_HOURS"


def test_no_pending_question_in_prompts():
    """Without a pending question neither stage prompt mentions one."""
    client = _FakeLLMClient(replies=["INTERRUPT", "NONE"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    match_global_router(client, router, _ctx("whatever"))
    assert "The agent just asked" not in client.prompts[0]
    assert "The agent just asked" not in client.prompts[1]


def test_pending_question_is_included_in_both_stage_prompts_when_given():
    """
    Regression test: without the pending question's own text, the model

        has nothing to judge "is this clearly answering it" against — it can
            only compare the reply to candidate phrases in isolation, which
            reliably over-matches a short, on-topic answer against a semantically
            related trigger (confirmed on real content: "soy venezolana" answering
            a nationality question was matched to an unrelated "soy extranjero"
            FAQ). This only checks the prompt carries the context through; the
            actual judgment call is the model's, exercised live against real
            content, not unit-testable with a fake client.

        Returns:
            None.
    """
    client = _FakeLLMClient(replies=["INTERRUPT", "NONE"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    match_global_router(client, router, _ctx("soy venezolana", pending_question="¿Cuál es tu nacionalidad?"))
    assert "¿Cuál es tu nacionalidad?" in client.prompts[0]
    assert "¿Cuál es tu nacionalidad?" in client.prompts[1]


def test_stage_one_prompt_warns_against_treating_a_bare_short_reply_as_an_interrupt():
    """
    Regression test: even with the pending question grounding above, a

        bare "no" answering "¿Tienes idea de qué trata la gestación subrogada?"
            was still matched 6/6 live runs against handler H_NO_INT (triggers on
            "no me interesa", "no quiero continuar") — a single word is inherently
            ambiguous between "no [I don't know]" and "no [I'm not interested]", and
            no real trigger phrase in this agent's content is itself a bare single
            word, so a short reply should essentially never be judged an interrupt.
            Fixed with an explicit rule in Stage 1; only checks the prompt carries
            it, same caveat as above.

        Returns:
            None.
    """
    client = _FakeLLMClient(replies=["CONTINUE"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    match_global_router(client, router, _ctx("no sé"))
    assert "one- or two-word reply" in client.prompts[0]


def test_history_is_included_in_both_stage_prompts():
    """
    Requested directly, 2026-09-17 — a bare `pending_question` alone

        isn't enough context in every case; recent turns let the model see a
            reply continuing a topic raised a couple of turns back, not just the
            single most recent question.

        Returns:
            None.
    """
    client = _FakeLLMClient(replies=["INTERRUPT", "NONE"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    history = ["agent: ¿Cuál es tu nacionalidad?", "user: soy de Chile"]
    match_global_router(client, router, _ctx("algo mas", history=history))
    assert "agent: ¿Cuál es tu nacionalidad?" in client.prompts[0]
    assert "agent: ¿Cuál es tu nacionalidad?" in client.prompts[1]


def test_slots_are_included_in_both_stage_prompts():
    """
    `ctx.slots` (2026-09-17) — the router previously never saw known slot

        values at all, unlike almost every other runtime LLM decision; sharing
            one `LLMContext` type closes that gap for free.

        Returns:
            None.
    """
    client = _FakeLLMClient(replies=["INTERRUPT", "NONE"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    match_global_router(client, router, _ctx("algo mas", slots={"nationality": "chilena"}))
    assert "chilena" in client.prompts[0]
    assert "chilena" in client.prompts[1]


def test_uses_the_deterministic_default_temperature():
    """
    A routing match/no-match is a factual judgment call, not creative

        writing — relies on `complete()`'s new default (`temperature=0.0`,
            2026-09-17) rather than requesting one explicitly, since every caller
            but `render_say`'s SAY paraphrasing wants exactly that default.

        Returns:
            None.
    """
    client = _FakeLLMClient(replies=["CONTINUE"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    match_global_router(client, router, _ctx("whatever"))
    assert client.temperatures == [0.0]


# ---------------------------------------------------------------------------
# handle_global_router_match
# ---------------------------------------------------------------------------


def test_faq_static_resume_target():
    """An FAQ with a static resume target returns that target."""
    match = ("faq", _faq_node(resume_to="CLOSE"))
    target = handle_global_router_match(match, _ctx(""), resolve_edges=lambda edges, ctx: None)
    assert target == "CLOSE"


def test_faq_dynamic_resume_is_none():
    """An FAQ with a dynamic resume target resumes in place."""
    match = ("faq", _faq_node(resume_to="[current_state]"))
    target = handle_global_router_match(match, _ctx(""), resolve_edges=lambda edges, ctx: None)
    assert target is None


def test_faq_without_resume_is_none():
    """An FAQ without a resume target resumes in place."""
    match = ("faq", _faq_node(resume_to=None))
    target = handle_global_router_match(match, _ctx(""), resolve_edges=lambda edges, ctx: None)
    assert target is None


def test_handler_calls_on_say():
    """A matched handler calls on_say with its node and say lines."""
    seen = []
    match = ("handler", _handler_node(say=["Sure, repeating now."]))
    handle_global_router_match(
        match,
        _ctx(""),
        resolve_edges=lambda edges, ctx: None,
        on_say=lambda n, say: seen.append((n.node_id, say)),
    )
    assert seen == [("H_REPEAT", ["Sure, repeating now."])]


def test_handler_route_via_resolve_edges():
    """A matched handler's route is resolved through the injected resolver."""
    route_edges = [GraphEdge(target="OTHER_STATE", condition_text=None, is_mechanical=True)]
    match = ("handler", _handler_node(route=route_edges))
    target = handle_global_router_match(
        match, _ctx(""), resolve_edges=lambda edges, ctx: "OTHER_STATE" if edges is route_edges else None
    )
    assert target == "OTHER_STATE"


def test_handler_match_uses_the_matched_handler_s_own_goal_and_do_for_resolve_edges():
    """
    The `ctx` passed to `resolve_edges` for a matched handler must carry

        THAT handler's own `goal`/`do` (2026-09-17) — not the originating
            question node's, which `handle_global_router_match` never even sees.

        Returns:
            None.
    """
    route_edges = [GraphEdge(target="OTHER_STATE", condition_text=None, is_mechanical=True)]
    match = (
        "handler",
        _handler_node(route=route_edges, goal=["Handle a repeat request."], do=["Say it again."]),
    )
    seen_ctx = {}

    def resolve_edges(edges, ctx):
        seen_ctx["goal"] = ctx.goal
        seen_ctx["do"] = ctx.do
        return "OTHER_STATE"

    handle_global_router_match(
        match, _ctx("", pending_question="original question"), resolve_edges=resolve_edges
    )
    assert seen_ctx == {"goal": ["Handle a repeat request."], "do": ["Say it again."]}


def test_handler_uses_fallback_edges():
    """When the route resolves to nothing, the handler's fallback edges are used."""
    fallback_edges = [GraphEdge(target="FALLBACK_STATE", condition_text=None, is_mechanical=True)]
    match = ("handler", _handler_node(route=[], fallback=fallback_edges))
    target = handle_global_router_match(
        match,
        _ctx(""),
        resolve_edges=lambda edges, ctx: "FALLBACK_STATE" if edges is fallback_edges else None,
    )
    assert target == "FALLBACK_STATE"


def test_handler_dynamic_target_resumes():
    """A handler with a dynamic target resumes in place."""
    route_edges = [GraphEdge(target="[current_state]", condition_text=None, is_mechanical=True)]
    match = ("handler", _handler_node(route=route_edges))
    target = handle_global_router_match(match, _ctx(""), resolve_edges=lambda edges, ctx: "[current_state]")
    assert target is None


def test_handler_without_route_resumes():
    """A handler with no route resumes in place."""
    match = ("handler", _handler_node(route=[], fallback=[]))
    target = handle_global_router_match(match, _ctx(""), resolve_edges=lambda edges, ctx: None)
    assert target is None


def test_on_say_not_called_when_say_is_empty():
    """on_say is not called when the handler has nothing to say."""
    seen = []
    match = ("handler", _handler_node(say=[]))
    handle_global_router_match(
        match, _ctx(""), resolve_edges=lambda edges, ctx: None, on_say=lambda n, say: seen.append(1)
    )
    assert seen == []


# ---------------------------------------------------------------------------
# has_unanswered_side_question / UNANSWERED_QUESTION_ACK
# ---------------------------------------------------------------------------


def test_side_question_yes_reply():
    """A YES reply means there is an unanswered side question."""
    client = _FakeLLMClient(["YES"])
    assert (
        has_unanswered_side_question(client, _ctx("Soy pareja heterosexual. ¿Eso afecta el proceso?")) is True
    )


def test_side_question_no_reply():
    """A NO reply means there is no side question."""
    client = _FakeLLMClient(["NO"])
    assert has_unanswered_side_question(client, _ctx("Quiero saber si en pareja es mejor")) is False


def test_side_question_one_call():
    """The side-question check costs a single model call."""
    client = _FakeLLMClient(["NO"])
    has_unanswered_side_question(client, _ctx("¿Ok?"))
    assert len(client.prompts) == 1


def test_side_question_skips_plain_answers():
    """Plain answers skip the model in the side-question check."""
    client = _FakeLLMClient([])
    assert has_unanswered_side_question(client, _ctx("Sí, quiero continuar.")) is False
    assert has_unanswered_side_question(client, _ctx("Ok.")) is False
    assert has_unanswered_side_question(client, _ctx("en pareja")) is False
    assert client.prompts == []


def test_side_question_without_marks():
    """A question without question marks is still detected."""
    client = _FakeLLMClient(["YES"])
    assert has_unanswered_side_question(client, _ctx("cuanto cuesta el proceso")) is True


def test_side_question_prompt_contents():
    """The side-question prompt includes the pending question and its exclusions."""
    client = _FakeLLMClient(["NO"])
    has_unanswered_side_question(client, _ctx("¿yo? soy de Colombia", pending_question="¿De dónde eres?"))
    assert "¿De dónde eres?" in client.prompts[0]
    assert "even if phrased as a question" in client.prompts[0]


def test_question_ack_is_fixed_text():
    """The acknowledgement for an unanswered question is a fixed, non-empty say block."""
    assert UNANSWERED_QUESTION_ACK
    assert all(isinstance(line, str) and line for line in UNANSWERED_QUESTION_ACK)


def test_language_switch_still_checks_faqs():
    """A language switch detected by content still checks the FAQs."""
    language_handler = _handler_node(node_id="H_LANG_CHANGE", trigger=["hablame en español"])
    faq = _faq_node(match=["metodo ropa"])
    router = GlobalRouterDefinition(handlers=[language_handler], faqs=[faq])
    client = _FakeLLMClient(replies=["INTERRUPT", "1"])
    slots = {"preferred_language": "English"}

    match = match_global_router(
        client,
        router,
        _ctx("quiero saber mas del metodo ropa", slots=slots, pending_question="IVF or surrogacy?"),
    )

    assert slots["preferred_language"] == "Spanish"
    assert match is not None and match[0] == "faq"


def test_bare_yes_no_skips_model():
    """A bare yes or no continues without asking the model."""
    client = _FakeLLMClient(replies=["INTERRUPT"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    for reply in ("sí", "No", "claro, por favor"):
        assert match_global_router(client, router, _ctx(reply)) is None
    assert client.prompts == []


def test_bare_trigger_goes_to_model():
    """A bare reply that is also a trigger phrase still goes to the model."""
    handler = _handler_node(trigger=["no gracias"])
    client = _FakeLLMClient(replies=["CONTINUE"])
    match_global_router(client, GlobalRouterDefinition(handlers=[handler], faqs=[]), _ctx("No, gracias"))
    assert len(client.prompts) == 1


# ---------------------------------------------------------------------------
# router_for_state — a handler can be switched off inside a subflow or state
# ---------------------------------------------------------------------------


def test_router_drops_disabled_handlers():
    """A state's router drops handlers disabled in its subflow."""
    from agent_runtime.runtime.global_router import router_for_state

    schedule = _handler_node("H_SCHEDULE", disabled_in=["SC"])
    mgmt = _handler_node("H_MGMT")
    router = GlobalRouterDefinition(handlers=[schedule, mgmt], faqs=[])

    inside = router_for_state(router, "SC__SC_HOURS")
    assert [h.node_id for h in inside.handlers] == ["H_MGMT"]
    assert router_for_state(router, "OP__OP_HELLO") is router


def test_router_matches_exact_subflow():
    """A state's router matches its exact subflow, not a prefix lookalike."""
    from agent_runtime.runtime.global_router import router_for_state

    schedule = _handler_node("H_SCHEDULE", disabled_in=["SC__SC_HOURS"])
    router = GlobalRouterDefinition(handlers=[schedule], faqs=[])

    assert router_for_state(router, "SC__SC_HOURS").handlers == []
    assert router_for_state(router, "SC__SC_DAYS") is router
    assert router_for_state(router, "SC__SC_HOURS_EXTRA") is router


def test_handler_disabled_in_validation():
    """`disabled_in` is accepted and blank entries are rejected."""
    import pytest

    from agent_runtime.dsl.schemas import HandlerModel

    handler = HandlerModel(
        type="decision",
        wait="no",
        fallback=["GO_TO: SC__SC_S"],
        handler_id="H_X",
        trigger=["x"],
        disabled_in=["SC"],
    )
    assert handler.disabled_in == ["SC"]
    assert (
        HandlerModel(
            type="decision", wait="no", fallback=["GO_TO: SC__SC_S"], handler_id="H_X", trigger=["x"]
        ).disabled_in
        == []
    )
    with pytest.raises(ValueError):
        HandlerModel(
            type="decision",
            wait="no",
            fallback=["GO_TO: SC__SC_S"],
            handler_id="H_X",
            trigger=["x"],
            disabled_in=[" "],
        )


# ---------------------------------------------------------------------------
# GLOBAL_ROUTER_LANGUAGE_DETECTION — fixed phrases or the model decide a language change
# ---------------------------------------------------------------------------


def test_language_detection_default_rules(monkeypatch):
    """Language detection uses rules by default."""
    from agent_runtime.runtime.global_router import language_detection_by_model

    monkeypatch.delenv("GLOBAL_ROUTER_LANGUAGE_DETECTION", raising=False)
    assert language_detection_by_model() is False
    monkeypatch.setenv("GLOBAL_ROUTER_LANGUAGE_DETECTION", "True ")
    assert language_detection_by_model() is True
    monkeypatch.setenv("GLOBAL_ROUTER_LANGUAGE_DETECTION", "false")
    assert language_detection_by_model() is False


def test_language_request_by_rules(monkeypatch):
    """An explicit language request is caught by rules without the model."""
    monkeypatch.delenv("GLOBAL_ROUTER_LANGUAGE_DETECTION", raising=False)
    router = GlobalRouterDefinition(
        handlers=[_handler_node("H_LANG_CHANGE", trigger=["hablame en español"])], faqs=[]
    )
    client = _FakeLLMClient(replies=[])
    match = match_global_router(
        client,
        router,
        _ctx("háblame en español por favor", slots={"preferred_language": "English"}, pending_question="?"),
    )
    assert match is not None and match[1].node_id == "H_LANG_REASK"
    assert client.prompts == []


def test_language_request_by_model(monkeypatch):
    """In model mode the model decides an explicit language request."""
    monkeypatch.setenv("GLOBAL_ROUTER_LANGUAGE_DETECTION", "true")
    router = GlobalRouterDefinition(
        handlers=[_handler_node("H_LANG_CHANGE", trigger=["hablame en español"])], faqs=[]
    )
    client = _FakeLLMClient(replies=["LANGUAGE_CHANGE: Spanish"])
    slots = {"preferred_language": "English"}
    match = match_global_router(
        client, router, _ctx("quiero que me hables en español", slots=slots, pending_question="?")
    )
    assert len(client.prompts) == 1
    assert slots["preferred_language"] == "Spanish"
    assert match is not None and match[1].node_id == "H_LANG_REASK"


def test_bare_yes_no_en_pt():
    """Bare yes and no replies in English and Portuguese skip the model."""
    client = _FakeLLMClient(replies=["INTERRUPT"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    replies = (
        "yes please",
        "Yeah, sure",
        "no thanks",
        "of course",
        "sounds good",
        "go ahead",
        "absolutely",
        "sim, claro",
        "Não",
        "com certeza",
        "tudo bem",
        "pode ser",
        "Obrigada",
        "isso mesmo",
    )
    for reply in replies:
        assert match_global_router(client, router, _ctx(reply)) is None, reply
    assert client.prompts == []


def test_longer_reply_not_bare():
    """A longer English or Portuguese reply is not taken for a bare answer."""
    from agent_runtime.runtime.global_router import is_bare_yes_no

    assert not is_bare_yes_no("yes I want to talk to a human")
    assert not is_bare_yes_no("não, quero falar com uma pessoa")
    assert not is_bare_yes_no("no thanks I would rather book a call")


# ---------------------------------------------------------------------------
# respect filter — hate, vulgarity and disrespect are met with a reminder before the router runs
# ---------------------------------------------------------------------------


def test_disrespect_gets_reminder(monkeypatch):
    """A disrespectful reply gets the respect reminder and skips the router."""
    monkeypatch.setenv("GLOBAL_ROUTER_RESPECT_FILTER", "true")
    client = _FakeLLMClient(replies=["DISRESPECTFUL"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])

    match = match_global_router(
        client, router, _ctx("ustedes son unos inútiles de mierda", pending_question="Name?")
    )

    assert match is not None and match[0] == "handler" and match[1].node_id == "H_RESPECT"
    assert match[1].say and match[1].route == []
    assert len(client.prompts) == 1


def test_disrespect_uses_agent_handler(monkeypatch):
    """A disrespectful reply goes to the agent's own abuse handler when it has one."""
    monkeypatch.setenv("GLOBAL_ROUTER_RESPECT_FILTER", "true")
    client = _FakeLLMClient(replies=["DISRESPECTFUL"])
    safety = _handler_node(
        "H_SAFETY",
        trigger=["insults"],
        say=[],
        route=[GraphEdge(target="SM__SM_S", condition_text=None, is_mechanical=True)],
    )
    router = GlobalRouterDefinition(handlers=[_handler_node(), safety], faqs=[])

    match = match_global_router(client, router, _ctx("eres un idiota", pending_question="Name?"))

    assert match is not None and match[1].node_id == "H_SAFETY"
    assert len(client.prompts) == 1


def test_abuse_handler_not_a_candidate(monkeypatch):
    """The abuse handler is not a candidate the router model can pick."""
    monkeypatch.setenv("GLOBAL_ROUTER_RESPECT_FILTER", "true")
    client = _FakeLLMClient(replies=["OK", "INTERRUPT", "0"])
    safety = _handler_node("H_SAFETY", trigger=["insults"], say=[])
    router = GlobalRouterDefinition(handlers=[safety, _handler_node()], faqs=[])

    match = match_global_router(client, router, _ctx("esto es una estafa", pending_question="Name?"))

    assert match is not None and match[1].node_id == "H_REPEAT"
    assert "insults" not in client.prompts[-1]


def test_respectful_reply_continues(monkeypatch):
    """A respectful reply goes on to the continuation check."""
    monkeypatch.setenv("GLOBAL_ROUTER_RESPECT_FILTER", "true")
    client = _FakeLLMClient(replies=["OK", "CONTINUE"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])

    assert match_global_router(client, router, _ctx("me llamo Ana Pérez", pending_question="Name?")) is None
    assert len(client.prompts) == 2
    assert "DISRESPECTFUL" in client.prompts[0] and "CONTINUE" in client.prompts[1]


def test_the_respect_check_sees_only_the_end_of_a_long_agent_message(monkeypatch):
    """A long overview before the question made the model judge the topic, not the customer's words."""
    monkeypatch.setenv("GLOBAL_ROUTER_RESPECT_FILTER", "true")
    client = _FakeLLMClient(replies=["OK", "CONTINUE"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    overview = "SERVICE OVERVIEW " * 60
    pending = overview + "Which of these services are you interested in?"

    match_global_router(client, router, _ctx("esto es una estafa", pending_question=pending))

    prompt = client.prompts[0]
    assert "Which of these services are you interested in?" in prompt
    assert overview not in prompt
    assert "is a complaint about the thing, not an insult" in prompt


def test_bare_yes_no_skips_respect_filter(monkeypatch):
    """A bare yes or no is not sent to the respect filter."""
    monkeypatch.setenv("GLOBAL_ROUTER_RESPECT_FILTER", "true")
    client = _FakeLLMClient(replies=[])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    assert match_global_router(client, router, _ctx("sí")) is None
    assert client.prompts == []


def test_respect_filter_toggle(monkeypatch):
    """The respect filter can be switched off by configuration."""
    from agent_runtime.runtime.global_router import respect_filter_enabled

    monkeypatch.delenv("GLOBAL_ROUTER_RESPECT_FILTER", raising=False)
    assert respect_filter_enabled() is True
    monkeypatch.setenv("GLOBAL_ROUTER_RESPECT_FILTER", "false")
    assert respect_filter_enabled() is False


def test_other_language_reply_processed(monkeypatch):
    """A reply in another language is processed, not discarded."""
    monkeypatch.setenv("GLOBAL_ROUTER_LANGUAGE_DETECTION", "true")
    router = GlobalRouterDefinition(
        handlers=[_handler_node("H_LANG_CHANGE", trigger=["hablame en español"])], faqs=[]
    )
    client = _FakeLLMClient(replies=["LANGUAGE_CHANGE_ANSWER: Spanish"])
    slots = {"preferred_language": "English"}
    match = match_global_router(
        client, router, _ctx("donde atienden?", slots=slots, pending_question="Any questions?")
    )
    assert match is None
    assert slots["preferred_language"] == "Spanish"


def test_prompt_language_change_only_on_request(monkeypatch):
    """The prompt reserves a language change for explicit requests."""
    monkeypatch.setenv("GLOBAL_ROUTER_LANGUAGE_DETECTION", "true")
    router = GlobalRouterDefinition(
        handlers=[_handler_node("H_LANG_CHANGE", trigger=["hablame en español"])], faqs=[]
    )
    client = _FakeLLMClient(replies=["CONTINUE"])
    match_global_router(
        client, router, _ctx("hola", slots={"preferred_language": "English"}, pending_question="?")
    )
    assert "reply LANGUAGE_CHANGE_ANSWER: <LanguageName>" in client.prompts[0]


def test_language_request_is_a_change():
    """A language request is a language change, not content."""
    router = GlobalRouterDefinition(
        handlers=[_handler_node("H_LANG_CHANGE", trigger=["hablame en ingles"])], faqs=[]
    )
    client = _FakeLLMClient(replies=["LANGUAGE_CHANGE: English"])
    slots = {"preferred_language": "Spanish"}
    match = match_global_router(
        client, router, _ctx("¿puedes hablar en inglés?", slots=slots, pending_question="¿Alguna duda?")
    )
    assert slots["preferred_language"] == "English"
    assert match is not None and match[1].node_id == "H_LANG_REASK"


# ---------------------------------------------------------------------------
# GLOBAL_ROUTER_LANGUAGES — the languages a conversation may switch to
# ---------------------------------------------------------------------------


def test_default_languages(monkeypatch):
    """The default languages are those marked default-enabled."""
    from agent_runtime.runtime.global_router import supported_languages

    monkeypatch.delenv("GLOBAL_ROUTER_LANGUAGES", raising=False)
    assert supported_languages() == ("English", "Spanish", "Portuguese")


def test_languages_by_name_or_code(monkeypatch):
    """Allowed languages may be written by name or code in the environment."""
    from agent_runtime.runtime.global_router import supported_languages

    monkeypatch.setenv("GLOBAL_ROUTER_LANGUAGES", "English, es; Portuguese|fr, french, Klingon")
    # The order is the env's own; "Klingon" has no file in agent_runtime/languages/data, so it is ignored.
    assert supported_languages() == ("English", "Spanish", "Portuguese", "French")


def test_disallowed_language_not_resolved(monkeypatch):
    """A language the environment does not allow is not resolved."""
    from agent_runtime.runtime.global_router import _language_name_from_slots

    monkeypatch.setenv("GLOBAL_ROUTER_LANGUAGES", "English,Spanish")
    assert _language_name_from_slots({"preferred_language": "French"}, fallback="English") == "English"
    assert _language_name_from_slots({"preferred_language": "fr"}, fallback="English") == "English"
    monkeypatch.setenv("GLOBAL_ROUTER_LANGUAGES", "English,Spanish,French")
    assert _language_name_from_slots({"preferred_language": "French"}) == "French"
    assert _language_name_from_slots({"preferred_language": "fr"}) == "French"


def test_french_only_when_allowed(monkeypatch):
    """French is detected only when the environment allows it."""
    from agent_runtime.runtime.global_router import _detect_language_and_intent

    monkeypatch.setenv("GLOBAL_ROUTER_LANGUAGES", "English,Spanish,Portuguese")
    assert _detect_language_and_intent("en français s'il vous plaît", "English") == (None, "none")
    monkeypatch.setenv("GLOBAL_ROUTER_LANGUAGES", "English,Spanish,Portuguese,French")
    assert _detect_language_and_intent("en français s'il vous plaît", "English") == ("French", "explicit")
    assert _detect_language_and_intent("je ne parle pas anglais", "English") == ("French", "inability_clear")
    assert _detect_language_and_intent("Bonjour, je voudrais des informations", "English") == (
        "French",
        "content_answer",
    )
    assert _detect_language_and_intent("Bonjour, je voudrais des informations", "French") == (None, "none")


def test_prompt_follows_allowed_languages(monkeypatch):
    """The model prompt and decision follow the allowed languages."""
    monkeypatch.setenv("GLOBAL_ROUTER_LANGUAGE_DETECTION", "true")
    monkeypatch.setenv("GLOBAL_ROUTER_LANGUAGES", "English,Spanish,Portuguese,French")
    router = GlobalRouterDefinition(
        handlers=[_handler_node("H_LANG_CHANGE", trigger=["en français"])], faqs=[]
    )
    client = _FakeLLMClient(replies=["LANGUAGE_CHANGE: French"])
    slots = {"preferred_language": "Spanish"}
    match = match_global_router(
        client, router, _ctx("pouvez-vous me parler en français", slots=slots, pending_question="?")
    )
    assert "English, Spanish, Portuguese, or French" in client.prompts[0]
    assert "LANGUAGE_CHANGE: French" in client.prompts[0]
    assert slots["preferred_language"] == "French"
    assert match is not None and match[1].node_id == "H_LANG_REASK"


def test_language_menu_allowed_only(monkeypatch):
    """The language menu lists only the allowed languages."""
    from agent_runtime.runtime.global_router import _language_menu

    monkeypatch.delenv("GLOBAL_ROUTER_LANGUAGES", raising=False)
    assert _language_menu() == (
        "I can assist you in English, español or português. / Puedo atenderte en English, español o português. / "
        "Posso atendê-lo em English, español ou português."
    )
    monkeypatch.setenv("GLOBAL_ROUTER_LANGUAGES", "English,Spanish,Portuguese,French")
    menu = _language_menu()
    assert "Puedo atenderte en English, español, português o français." in menu
    assert menu.endswith("Je peux vous répondre en English, español, português ou français.")


def test_bare_yes_no_french():
    """Bare French replies skip the model."""
    client = _FakeLLMClient(replies=["INTERRUPT"])
    router = GlobalRouterDefinition(handlers=[_handler_node()], faqs=[])
    for reply in ("oui", "Non", "bien sûr", "d'accord", "oui, merci", "parfait"):
        assert match_global_router(client, router, _ctx(reply)) is None, reply
    assert client.prompts == []
