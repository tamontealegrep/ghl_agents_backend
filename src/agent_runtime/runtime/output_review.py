"""Output review: one last check of every message the agent is about to send.

The global router's respect filter looks at what the contact *writes*. This is its counterpart for what
the agent *says*: a model call, right before the message goes out, that is given the agent's output rules
(what a message must never say or imply) and its forbidden words, and either lets the message through as it
is or rewrites it so that it follows every rule and uses none of the words.

The rules and the words belong to the agent definition (`output_rules.yaml`, `forbidden_words.yaml`, listed
under `includes` in the manifest) and travel in the compiled bundle. The review is opt-in per deployment with
`GLOBAL_ROUTER_OUTPUT_REVIEW`, and an agent that declares neither rules nor words is never reviewed.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from agent_runtime.runtime.llm_client import LLMClient

logger = logging.getLogger(__name__)

OUTPUT_REVIEW_ENV = "GLOBAL_ROUTER_OUTPUT_REVIEW"
"""`true` reviews every message the agent sends against its output rules and forbidden words; `false` (the
default) skips the review. Set per company, next to `GLOBAL_ROUTER_RESPECT_FILTER`."""


def output_review_enabled() -> bool:
    """True only when the environment turns the output review on."""
    return os.environ.get(OUTPUT_REVIEW_ENV, "false").strip().lower() in {"true", "1", "yes", "on"}


def _fold(text: str) -> str:
    """
    `text` lower-cased and without accents, so "Gestación" and "gestacion" compare equal.

    Folded one character at a time, so the result is as long as `text` and a position in one is a position in the other.
    """
    out: list[str] = []
    for char in text:
        base = "".join(c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c)).lower()
        out.append(base if len(base) == 1 else char.lower() if len(char.lower()) == 1 else char)
    return "".join(out)


@dataclass(frozen=True, slots=True)
class ForbiddenTerm:
    """One forbidden word or phrase, compiled for matching."""

    word: str
    use_instead: str | None
    reason: str | None
    pattern: re.Pattern[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ForbiddenTerm:
        word = str(data["word"]).strip()
        # A trailing `*` stands for any ending of the word ("reclut*" is reclutar, reclutamiento, ...).
        stem = _fold(word.rstrip("*"))
        body = r"\s+".join(re.escape(part) for part in stem.split())
        tail = r"\w*" if word.endswith("*") else ""
        return cls(
            word=word,
            use_instead=(data.get("use_instead") or None),
            reason=(data.get("reason") or None),
            pattern=re.compile(rf"(?<!\w){body}{tail}(?!\w)"),
        )


@dataclass(frozen=True, slots=True)
class OutputReview:
    """The rules and words of one agent, and the review itself."""

    rules: tuple[str, ...]
    terms: tuple[ForbiddenTerm, ...]

    @classmethod
    def from_artifact(cls, artifact: Any) -> OutputReview | None:
        """The review for `artifact`, or `None` when it is off or the agent declares neither rules nor words."""
        if not output_review_enabled():
            return None
        rules = tuple(getattr(artifact, "output_rules", None) or ())
        terms = tuple(ForbiddenTerm.from_dict(w) for w in (getattr(artifact, "forbidden_words", None) or ()))
        if not rules and not terms:
            return None
        return cls(rules=rules, terms=terms)

    # -- word check ---------------------------------------------------------

    def find_forbidden(self, text: str) -> list[ForbiddenTerm]:
        """
        Every listed term `text` contains (ignoring case and accents).

        Presence is not a violation: any word can be used to answer, quote or deny ("it is not a business"). The
        check only tells the review model where to look; whether a use breaks a rule is the model's judgment.
        """
        folded = _fold(text)
        return [term for term in self.terms if term.pattern.search(folded)]

    # -- model part ---------------------------------------------------------

    def _prompt(
        self, text: str, language: str | None, found: list[ForbiddenTerm], retry: bool, asked: str = ""
    ) -> str:
        rules = "\n".join(f"- {rule}" for rule in self.rules) or "- (none)"
        words = "\n".join(
            f"- \"{t.word}\"" + (f" -> prefer: {t.use_instead}" if t.use_instead else "") + (f" ({t.reason})" if t.reason else "")
            for t in self.terms
        ) or "- (none)"
        found_block = (
            "A word check found these listed words in the message: "
            + ", ".join(f'"{t.word}"' for t in found)
            + ". Look at how each one is used and decide by its meaning.\n\n"
            if found
            else ""
        )
        retry_block = (
            "Your previous rewrite still contains listed words. Remove each one that is used to describe, offer or "
            "promise something about the program.\n\n"
            if retry
            else ""
        )
        asked_block = (
            "WHAT THE CONTACT JUST WROTE (the message below is the reply to it; it shows whether the assistant is "
            f"answering her or bringing the subject up itself):\n{asked.strip()[:600]}\n\n"
            if asked.strip()
            else ""
        )
        in_language = f" The message is written in {language}; keep it in that language." if language else " Keep the message in its own language."
        return (
            "You are the final compliance reviewer of an assistant's messages. Decide whether the MESSAGE below "
            "can be sent to the contact as it is.\n\n"
            f"OUTPUT RULES (the message must follow every one):\n{rules}\n\n"
            "WATCH LIST (words and phrases, in any inflection or translation, that often signal a problem):\n"
            f"{words}\n\n"
            "HOW TO DECIDE: every rule and every listed word exists to stop one IDEA from reaching the contact (the "
            "reason shown next to each word says which). Judge whether the message CONVEYS that idea, never whether a "
            "listed word appears. A word can appear in a message that conveys a completely different idea, and then "
            "nothing is wrong: for example when the message answers a question about the contact's own life, refers "
            "to her own words, or denies the forbidden idea. Leave such a message exactly as it is, listed word "
            "included, and never swap a word for another one just to avoid it. Rewrite only when the message itself "
            "conveys the forbidden idea. When in doubt, reply OK.\n\n"
            f"{found_block}{retry_block}"
            "Answer in this format. First, one line for each listed word the message contains and for each rule "
            "that could apply: - \"<word or rule>\": <in a few words, what the message actually tells the contact "
            "with it, and whether that is the forbidden idea> => IDEA (the message conveys the forbidden idea) or "
            "OTHER (the word is there but the message conveys something else, or the rule does not apply). Think "
            "about what is being said, not about the word: telling someone she may keep something she already has is "
            "not the same as presenting the program as that thing. Then a last line that is exactly one of:\n"
            "VERDICT: OK   (every line is OTHER, or nothing applies)\n"
            "VERDICT: REWRITE   (at least one line is IDEA) followed, from the next line on, by the corrected "
            "message, ready to send. Change as little as possible: keep the meaning, the tone, the structure and the line "
            "breaks. Remove or replace only what breaks a rule (preferring the suggested wording), and delete a "
            "whole phrase when a rule forbids the idea itself (an amount of money, say), so that the sentence "
            "still reads naturally. Keep every placeholder like <LIST_1>, <NUM_2> or <CONTACT_NAME> exactly as "
            "written. Never add information, never add a question, and never mention this review."
            f"{in_language}\n\n"
            f"{asked_block}"
            f"MESSAGE:\n{text}"
        )

    def review(
        self,
        llm_client: LLMClient,
        text: str,
        *,
        language: str | None = None,
        required_tokens: Iterable[str] = (),
        node_id: str = "",
        asked: str = "",
    ) -> str:
        """
        `text` as the agent may send it: unchanged when it follows every rule, rewritten otherwise.

        The model decides by meaning, so an "OK" is final even when a listed word is present. A rewrite that
        still contains listed words is checked once more by the model, which either approves those uses or
        removes them. `required_tokens` are the placeholders (dates, times, contact values) a rewrite must keep,
        because code wrote them; a rewrite that loses one, asks more questions than the original or comes back
        empty is thrown away. The message is never held back.
        """
        if not text.strip():
            return text
        required = [t for t in required_tokens if t in text]
        current = text
        retry = False
        for _ in range(2):
            found = self.find_forbidden(current)
            decision = llm_client.complete(self._prompt(current, language, found, retry, asked), temperature=0.0).strip()
            candidate = _parse_rewrite(decision)
            if candidate is None:
                return current  # OK (or nothing usable): nothing to change.
            if not _acceptable(text, candidate, required):
                logger.warning("output review: discarded a rewrite of %s (lost a placeholder or added a question)", node_id)
                return current
            current = candidate
            if not self.find_forbidden(current):
                logger.info("output review: rewrote %s", node_id)
                return current
            retry = True
        logger.info(
            "output review: %s rewritten; listed words remain after the second pass: %s",
            node_id or "a message",
            [t.word for t in self.find_forbidden(current)],
        )
        return current


def _parse_rewrite(decision: str) -> str | None:
    """The corrected message when the model answered REWRITE; `None` when it said OK or answered nothing usable."""
    # The model first writes its analysis, then a `VERDICT: OK` / `VERDICT: REWRITE` line (the last one counts).
    verdicts = list(re.finditer(r"(?im)^[ \t>*`]*verdict[ \t*`]*:[ \t*`]*(ok|rewrite)\b[ \t*`]*([^\n]*)", decision))
    if verdicts:
        last = verdicts[-1]
        if last.group(1).lower() == "ok":
            return None
        body = (last.group(2) + "\n" + decision[last.end():]).strip()
        return _without_label(body) or None
    # A bare answer without the analysis: "OK", or "REWRITE" and the message.
    first, _, rest = decision.partition("\n")
    if first.strip().strip("*`\"' .:").upper().startswith("REWRITE"):
        inline = first.strip()[len("REWRITE"):].lstrip(" :-\t")
        return _without_label((rest or inline).strip()) or None
    return None


def _without_label(body: str) -> str:
    """`body` without a leading "MESSAGE:" label the model sometimes copies from the prompt."""
    return re.sub(r"(?i)^[ \t*`]*message[ \t*`]*:[ \t*`]*", "", body, count=1).strip()


def _acceptable(original: str, candidate: str, required: list[str]) -> bool:
    """A rewrite keeps every code-written placeholder and does not ask more than the original."""
    return bool(candidate.strip()) and candidate.count("?") <= original.count("?") and all(t in candidate for t in required)
