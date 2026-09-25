"""Guards for the narration the narrator returns: readability and novelty.

Mid-size models — Mistral's free tier in particular — sometimes answer a turn as
one wall of text: a chain of quoted lines and italicised inner thoughts with the
narration squeezed to a sentence here and there. The story rules ask for 3-9
paragraphs of prose with the dialogue carried inside it (see
`narrator_system.txt`), and a wall of fragments is painful to read in the feed,
so the engine measures the result and asks once for a rewrite.

The second guard is about novelty: small narrators keep replaying the same beat
— the same staged entrance, the same internal monologue, the same farewell —
turn after turn. The prompt already shows the last three turns, so the engine
compares the new narration against them and asks once for a rewrite there too.

The measuring is deliberately language-agnostic: Russian dialogue is written
with a leading dash, English with quotation marks, and both are counted.
"""

import re

# Only real turns are checked: a tense exchange or a quick transition may be
# deliberately short and sharp, and a single-paragraph vignette there is fine.
MIN_CHECK_CHARS = 700
MIN_PARAGRAPHS = 3
MAX_SPEECH_SHARE = 0.6
# A paragraph that carries this many quoted exchanges in a row is a wall of
# dialogue the player cannot read: the quotes have nowhere to breathe.
MAX_QUOTES_PER_PARAGRAPH = 5
# The repetition guard: a turn that re-uses a run of this many words, or a
# quoted line of this many characters, from the turns already shown in the
# prompt, is the "the AI writes the same scene over and over" complaint.
REPEAT_NGRAM = 8
REPEAT_QUOTE_CHARS = 8
# A one-word "Yes." / "Иди." is not a refrain; a stock line of two words or more
# that comes back word for word is.
REPEAT_QUOTE_MIN_WORDS = 2
# Below this the turn is too short for an overlap to mean anything (a two-line
# exchange can legitimately echo a name or a place from the previous turn).
MIN_REPEAT_CHECK_WORDS = 40

_QUOTED_SPANS = re.compile(r"\"[^\"]*\"|«[^»]*»|„[^“]*“|“[^”]*”")
_ITALIC_SPANS = re.compile(r"\*[^*\n]+\*")
_WORD = re.compile(r"[^\W\d_]+")
# A line that OPENS with a dash or a quotation mark is a dialogue line (the
# Russian dash convention and the English quotation convention alike).
_DIALOGUE_LINE = re.compile(r"^[—–-]|^[\"«„“]")


def paragraphs(narration: str) -> list[str]:
    """The blank-line separated paragraphs of a turn."""
    return [part.strip() for part in re.split(r"\n\s*\n", narration) if part.strip()]


def quotes_in(text: str) -> int:
    """How many quoted exchanges a piece of text carries.

    Italicised thoughts (`*«...»*`, `*"..."*`) are counted once, through the
    quote pattern alone — the italic wrapper is styling, not a second quote.
    """
    return len(_QUOTED_SPANS.findall(text))


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def _normalized_words(text: str) -> list[str]:
    """Case-folded word list, the unit the repetition guard compares."""
    return [word.lower() for word in _WORD.findall(text)]


def _shingles(words: list[str], size: int) -> set[tuple[str, ...]]:
    """Every run of `size` consecutive words (a phrase fingerprint)."""
    if len(words) < size:
        return set()
    return {tuple(words[index : index + size]) for index in range(len(words) - size + 1)}


def _quoted_lines(text: str) -> dict[str, str]:
    """Quoted speech and italic thoughts as {normalized: as written}.

    A line the narrator already used verbatim in an earlier turn ("Кто-то
    здесь", "Я не мог просто оставить тебя здесь одной") is the loudest
    repetition signal there is, and it is short — so it is measured on its own,
    separately from the prose shingles. The original wording is kept, because
    the complaint is handed back to the narrator and has to show the reuse.
    """
    lines: dict[str, str] = {}
    for span in _QUOTED_SPANS.findall(text):
        words = _normalized_words(span)
        key = " ".join(words)
        if len(words) >= REPEAT_QUOTE_MIN_WORDS and len(key) >= REPEAT_QUOTE_CHARS:
            lines[key] = span.strip().strip(",.—- ")[:60]
    return lines


def _speech_words(line: str) -> int:
    """Words of a line that sit inside quotes or italics (never both)."""
    spans = sorted(
        match.span()
        for pattern in (_QUOTED_SPANS, _ITALIC_SPANS)
        for match in pattern.finditer(line)
    )
    counted = 0
    last_end = -1
    for start, end in spans:
        start = max(start, last_end)
        if end <= start:
            continue
        counted += len(_words(line[start:end]))
        last_end = end
    return counted


def speech_word_share(narration: str) -> float:
    """Share of a turn's words that are spoken or thought, not narrated."""
    total = _words(narration)
    if not total:
        return 0.0
    speech = 0
    for line in narration.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _DIALOGUE_LINE.match(stripped):
            speech += len(_words(stripped))
        else:
            speech += _speech_words(stripped)
    return speech / len(total)


def narration_problems(narration: str) -> list[str]:
    """The format problems worth one rewrite; empty when the turn reads fine.

    The returned lines are written as instructions, because they are handed
    back to the narrator together with the retry request.
    """
    text = narration.strip()
    if len(text) < MIN_CHECK_CHARS:
        return []
    problems: list[str] = []
    blocks = paragraphs(text)
    if len(blocks) < MIN_PARAGRAPHS:
        problems.append(
            "NARRATION FORMAT: the turn came back as a single block of text. Write it as "
            f"{MIN_PARAGRAPHS}-9 paragraphs separated by blank lines (\\n\\n), each one "
            "narration in prose."
        )
    # A paragraph that keeps answering itself: «...» — сказал он. «...» — ответила
    # она. ... six, seven times. It may satisfy the paragraph count and still be
    # unreadable, because the player's eye loses the speaker on every quote.
    dense = max((quotes_in(block) for block in blocks), default=0)
    if dense > MAX_QUOTES_PER_PARAGRAPH:
        problems.append(
            "NARRATION FORMAT: a paragraph packs a whole chain of quoted exchanges "
            f"({dense} quotes) into one block, which reads as a wall of text. Break "
            "the dialogue apart: every reply starts its own paragraph (the quote, "
            "then one sentence of narration saying who spoke), and put a narration "
            "paragraph between longer exchanges — never more than two quoted lines "
            "in a row inside one paragraph."
        )
    if speech_word_share(text) > MAX_SPEECH_SHARE:
        problems.append(
            "NARRATION FORMAT: most of the turn's words are quoted lines and italicised "
            "thoughts. Keep the speech a minority and write the scene around it — what "
            "the characters do, see and feel between the lines — with every quoted line "
            "attributed by the narration."
        )
    return problems


def repetition_problems(narration: str, recent: list[str]) -> list[str]:
    """How much of this turn the narrator already wrote in the previous turns.

    `recent` holds the narrations of the turns the prompt shows to the model
    (the last three). The complaint is returned as an instruction, because it is
    handed back with the retry request, exactly like the format problems.

    Two independent signals, because the repetition the players report comes in
    both shapes: a whole paragraph re-used almost word for word, and a single
    stock line ("Кто-то здесь", "Это то, что мне нужно") repeated turn after
    turn. Names and places alone are never enough — an overlap has to be a run
    of `REPEAT_NGRAM` words or a quoted line of `REPEAT_QUOTE_CHARS` characters.
    """
    text = narration.strip()
    words = _normalized_words(text)
    if not recent or len(words) < MIN_REPEAT_CHECK_WORDS:
        return []

    previous = [turn for turn in recent if turn and turn.strip()]
    if not previous:
        return []

    problems: list[str] = []
    reused = _shingles(words, REPEAT_NGRAM) & set().union(
        *(_shingles(_normalized_words(turn), REPEAT_NGRAM) for turn in previous)
    )
    if reused:
        example = " ".join(sorted(reused)[0])
        problems.append(
            "REPEATED CONTENT: this turn re-uses wording from the turns already written "
            f'(for example: "…{example}…"). The story has already played that beat — '
            "write what happens NEXT: new information, a new obstacle, a consequence of "
            "what the hero just did. Never re-run a scene, a description or an internal "
            "monologue that an earlier turn already used."
        )
    quoted = _quoted_lines(text)
    earlier_quotes = {key for turn in previous for key in _quoted_lines(turn)}
    repeated_quotes = quoted.keys() & earlier_quotes
    if repeated_quotes:
        example = quoted[sorted(repeated_quotes)[0]]
        problems.append(
            f'REPEATED DIALOGUE: the line "{example}" was already said or thought in an '
            "earlier turn. Every quoted line and every italic thought must be new "
            "wording; if the same character would say the same thing again, give them a "
            "different reason to speak and different words."
        )
    return problems
