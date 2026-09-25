"""Deterministic tag handling for image prompts.

Two jobs the backend does itself instead of asking the text model nicely:

* the player's freeform hero description often states proportions that the
  narrator then drops while compressing the look into tags (a described "большая
  грудь" came back as a flat chest), so a small phrase -> tag map guarantees them
  (`ensure_trait_tags`);
* the image model reads English danbooru tags, so a tag string the narrator
  answered in Russian is detected here (`has_cyrillic`) and re-emitted in English
  by the caller (`llm.translate_image_tags`).
"""

import re

# Any Cyrillic letter (Russian, plus the Kazakh/Ukrainian letters a translation
# pass should also recognize). Latin/punctuation strings return False.
_CYRILLIC = re.compile(r"[А-Яа-яЁёІіЇїЄєҒғҚқҢңӨөҰұҺһ]")


def has_cyrillic(text: str | None) -> bool:
    """True when the string contains Cyrillic letters (i.e. is not English)."""
    return bool(text) and bool(_CYRILLIC.search(str(text)))


def _size_part(size: str, part: str) -> re.Pattern[str]:
    """A size word and a body part within two words of each other, either order
    ("огромная грудь", "грудь просто огромная", "huge breasts")."""
    return re.compile(
        rf"(?:{size})[\s-]+(?:\w+[\s-]+){{0,2}}(?:{part})"
        rf"|(?:{part})[\s-]+(?:\w+[\s-]+){{0,2}}(?:{size})",
        re.IGNORECASE,
    )


_CHEST = r"груд\w*|breasts?|boobs?|bust"
_HIPS = r"б[её]др\w*|hips?"
_WAIST = r"тали\w*|waist"
_LEGS = r"ног\w*|legs?"
_THIGHS = r"ляжк\w*|б[её]др\w*|thighs?"
_HUGE = r"огромн\w*|гигантск\w*|huge|gigantic|enormous|(?:very|extremely)[\s-]+large"
_LARGE = r"больш\w*|large|big|ample|full"
_SMALL = r"маленьк\w*|небольш\w*|small|tiny|flat"
_WIDE = r"широк\w*|wide|broad"
_NARROW = r"тонк\w*|узк\w*|narrow|slim"
_LONG = r"длинн\w*|long"
_THICK = r"полн\w*|толст\w*|thick"

# Chest size is one exclusive group: the first matching size wins, so
# "небольшая" (small) is never read as "большая" (large) and "огромная" is
# never reduced to merely large.
_CHEST_SIZES: tuple[tuple[re.Pattern[str], str], ...] = (
    (_size_part(_HUGE, _CHEST), "huge breasts"),
    (_size_part(_SMALL, _CHEST), "small breasts"),
    (_size_part(_LARGE, _CHEST), "large breasts"),
)

# Every other proportion stands on its own.
_OTHER_TRAITS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (_size_part(_WIDE, _HIPS), ("wide hips",)),
    (_size_part(_NARROW, _WAIST), ("narrow waist",)),
    (_size_part(_THICK, _THIGHS), ("thick thighs",)),
    (_size_part(_LONG, _LEGS), ("long legs",)),
    (re.compile(r"идеальн\w*[\s-]+фигур|hourglass figure|песочные часы", re.IGNORECASE), ("hourglass figure",)),
    (re.compile(r"стройн\w*|slender|slim figure", re.IGNORECASE), ("slim",)),
    (re.compile(r"спортивн\w*|накачанн\w*|мускулист\w*|muscular|athletic build", re.IGNORECASE), ("muscular",)),
    (re.compile(r"пышн\w*[\s-]+форм|фигурист\w*|curvy", re.IGNORECASE), ("curvy",)),
    (re.compile(r"высокого роста|высокая (?:девушка|женщина)|tall (?:woman|girl)", re.IGNORECASE), ("tall",)),
    (re.compile(r"невысок\w*|миниатюрн\w*|petite", re.IGNORECASE), ("petite",)),
)


def missing_trait_tags(description: str, tags: str) -> list[str]:
    """Tags for proportions the player's description states but `tags` lack.

    Only ADDS what the description says: a description that mentions no chest
    size leaves whatever the narrator decided alone, and a stated size is never
    contradicted.
    """
    text = description or ""
    if not text.strip():
        return []
    present = {tag.strip().lower() for tag in (tags or "").split(",") if tag.strip()}
    missing: list[str] = []
    for pattern, tag in _CHEST_SIZES:
        if pattern.search(text):
            if tag.lower() not in present:
                missing.append(tag)
                present.add(tag.lower())
            break
    for pattern, wanted in _OTHER_TRAITS:
        if not pattern.search(text):
            continue
        for tag in wanted:
            if tag.lower() not in present:
                missing.append(tag)
                present.add(tag.lower())
    return missing


def clean_tag_string(raw: str | None) -> str:
    """Strip JSON formatting, markdown, quotes and brackets that an LLM may output.

    Sometimes models emit `{"tags": ["1girl", "huge breasts"]}` or markdown
    lists despite being asked for plain comma-separated tags. This flattens any
    such output back into pure `1girl, huge breasts`.
    """
    if not raw:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    # Strip markdown code blocks
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    # If the text is wrapped in JSON or contains array brackets, extract elements
    # Remove braces and keys like {"tags": ...}
    text = re.sub(r'\{\s*"?tags"?\s*:\s*\[?', "", text, flags=re.IGNORECASE)
    text = re.sub(r"[{}\[\]]", " ", text)
    # Remove quotes around individual tokens
    text = re.sub(r'["\']', " ", text)
    # Split by comma or newline, clean tokens
    tokens: list[str] = []
    for part in re.split(r"[,\n]+", text):
        clean = " ".join(part.strip().split())
        # Drop JSON artifacts like 'tags:' or stray punctuation
        clean = re.sub(r"^tags\s*:\s*", "", clean, flags=re.IGNORECASE)
        clean = clean.strip(":,; ")
        if clean:
            tokens.append(clean)
    return ", ".join(tokens)



def ensure_trait_tags(description: str, tags: str) -> str:
    """Append the description's stated proportions to a hero's appearance tags."""
    missing = missing_trait_tags(description, tags)
    if not missing:
        return (tags or "").strip()
    base = (tags or "").strip().rstrip(",")
    return f"{base}, {', '.join(missing)}" if base else ", ".join(missing)
