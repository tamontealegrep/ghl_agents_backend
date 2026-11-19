"""Drafts the data file of a new language with a model, so adding one is a command and a review.

    python scripts/add_language.py it Italian
    python scripts/add_language.py it Italian --env-file companies/family_aims/.env

The model gets `en.yaml` (every field is explained there) and writes the same file in the new language. The draft
is validated by the registry's own loader and sent back to the model with the error until it loads (3 tries). The
result is `src/agent_runtime/languages/data/<code>.yaml`: read it (the phrases the router listens for are the part
worth a native speaker), then put the language in `GLOBAL_ROUTER_LANGUAGES`. Nothing else in the code changes.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_runtime.languages import registry  # noqa: E402
from agent_runtime.runtime.llm_client import OpenAILLMClient  # noqa: E402

ATTEMPTS = 3

PROMPT = """\
Below is the language data file of a text-messaging assistant, written for English. Write the same file for \
{name} (code `{code}`). Keep exactly the same structure, keys and comments' meaning; translate and adapt every value \
the way a native speaker would write it, do not translate the keys.

Rules:
- `code: {code}`, `name: {name}` (English name), `native_name` is the language's own name for itself, \nwritten as the language writes it (lowercase when it does not capitalize language names); `default_enabled: false`.
- `aliases`: other spellings or ISO codes a CRM may send, without accents is fine; leave out the code and the names.
- `calendar`: real names written as the language writes them in a sentence (lowercase if it does not capitalize \ndays and months), Monday first; the order of day, month and weekday in every format follows the language (the English \nfile puts the month first, most languages do not); `formats` use the placeholders as in the English file and must read naturally \
('{{weekday}} {{day}} de {{month}}' style, whatever {name} uses); `clock` 12 or 24 as is usual for e-mails in {name}.
- `messages`: natural, polite equivalents; `menu_offer` keeps the `{{languages}}` placeholder.
- `router.explicit_phrases`: 8-12 ways to ask to continue in {name} ("speak {name}", "in {name} please"...), \
in {name} and in English; `inability_phrases`: ways to say "I don't speak English"; `content_words`: 12-20 common words \
that show a message is in {name} and rarely in other languages; `topic_words`: fertility-clinic words ("I would like", \
"surrogacy"...); `bare_reply_words`: single words for yes, no, ok, thanks, of course, please...
- `scheduling`: how people say today, tomorrow, the day after tomorrow, the parts of the day and the ordinals \
(first, last, second to last, second to fifth, plus short forms like 1st), with the inflected forms a speaker uses.
- Output only the YAML, without comments, code fences or explanations.

{previous_error}English file:
{template}
"""


def _clean(reply: str) -> str:
    return re.sub(r"^```(?:ya?ml)?\s*|\s*```\s*$", "", reply.strip())


def _load_env(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if match:
            os.environ.setdefault(match.group(1), match.group(2).strip("\"'"))


def _validate(code: str, text: str) -> str | None:
    """None when `text` loads as the language `code`, else the loader's complaint."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"{code}.yaml"
        path.write_text(text, encoding="utf-8")
        try:
            registry._build(path)
        except Exception as error:  # noqa: BLE001 - any failure is feedback for the model
            return f"{type(error).__name__}: {error}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("code", help="two-letter language code, e.g. it")
    parser.add_argument("name", help="the language's English name, e.g. Italian")
    parser.add_argument("--env-file", type=Path, help="a .env with OPENAI_API_KEY (default: the process environment)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args()

    code = args.code.strip().lower()
    target = registry.DATA_DIR / f"{code}.yaml"
    if target.exists() and not args.force:
        print(f"{target} already exists (use --force to replace it)", file=sys.stderr)
        return 1
    if args.env_file:
        _load_env(args.env_file)
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set (use --env-file)", file=sys.stderr)
        return 1

    template = (registry.DATA_DIR / "en.yaml").read_text(encoding="utf-8")
    client = OpenAILLMClient()
    error = ""
    for attempt in range(1, ATTEMPTS + 1):
        previous = f"Your previous attempt failed to load with: {error}\nFix it.\n\n" if error else ""
        draft = _clean(client.complete(PROMPT.format(code=code, name=args.name, template=template, previous_error=previous)))
        error = _validate(code, draft) or ""
        if not error:
            target.write_text(draft + "\n", encoding="utf-8")
            print(f"Wrote {target} (attempt {attempt}).")
            print(f"Review it, then add '{args.name}' to GLOBAL_ROUTER_LANGUAGES.")
            return 0
        print(f"Attempt {attempt} did not load: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
