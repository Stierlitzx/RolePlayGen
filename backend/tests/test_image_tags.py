"""Deterministic tag intelligence: Cyrillic detection, trait guards, JSON cleanup."""

from app.services.image_tags import (
    clean_tag_string,
    ensure_trait_tags,
    has_cyrillic,
    missing_trait_tags,
)


def test_a_plain_tag_list_is_left_alone() -> None:
    assert clean_tag_string("1girl, long hair, adult") == "1girl, long hair, adult"
    assert clean_tag_string("  1girl ,  adult  ") == "1girl, adult"


def test_json_shaped_tag_output_is_flattened() -> None:
    # A model that answers with JSON instead of a tag list used to have that JSON
    # pasted straight into the image prompt (a real bug: the JSON text landed in
    # the Qwen encoder and the picture came out wrong).
    raw = '{ "tags": [ "1girl, solo", "huge_breasts, ample_breasts", "adult" ] }'
    assert clean_tag_string(raw) == "1girl, solo, huge_breasts, ample_breasts, adult"


def test_markdown_fences_quotes_and_keys_are_stripped() -> None:
    assert clean_tag_string('```json\n"1girl", "red hair"\n```') == "1girl, red hair"
    assert clean_tag_string("tags: 1girl, red hair") == "1girl, red hair"
    assert clean_tag_string("") == ""
    assert clean_tag_string(None) == ""


def test_has_cyrillic_detects_russian_and_kazakh() -> None:
    assert has_cyrillic("тёмный лес, 1girl")
    assert has_cyrillic("қара орман")
    assert not has_cyrillic("1girl, dark forest, standing")
    assert not has_cyrillic("")
    assert not has_cyrillic(None)


def test_stated_chest_size_is_guaranteed() -> None:
    # A described large chest that the tag conversion dropped is put back;
    # the same for the other sizes.
    assert missing_trait_tags("1girl, elf", "1girl, elf") == []
    assert missing_trait_tags(
        "Эльфийка с большой грудью", "1girl, elf"
    ) == ["large breasts"]
    assert missing_trait_tags(
        "She has huge breasts", "1girl, adult"
    ) == ["huge breasts"]
    assert missing_trait_tags(
        "девушка с маленькой грудью", "1girl, adult"
    ) == ["small breasts"]
    # ...and a size that is already there is never duplicated.
    assert missing_trait_tags("большая грудь", "1girl, large breasts") == []
    # "небольшая" is small, not "большая": order matters.
    assert missing_trait_tags("небольшая грудь", "1girl") == ["small breasts"]
    # "огромная" is huge, never merely large.
    assert missing_trait_tags("огромная грудь", "1girl, large breasts") == ["huge breasts"]


def test_other_proportions_are_guareded_too() -> None:
    assert missing_trait_tags("тонкая талия, широкие бёдра", "1girl") == [
        "wide hips", "narrow waist",
    ]
    assert missing_trait_tags("высокая девушка, длинные ноги", "1girl") == ["long legs", "tall"]
    # No stated proportions: the narrator's tags are left alone.
    assert missing_trait_tags("A mysterious stranger", "1boy, cloak, adult") == []


def test_ensure_trait_tags_appends_without_changing_the_base() -> None:
    assert ensure_trait_tags(
        "Эльфийка с большой грудью", "1girl, elf ears, adult"
    ) == "1girl, elf ears, adult, large breasts"
    assert ensure_trait_tags("elf", "1girl, elf") == "1girl, elf"
