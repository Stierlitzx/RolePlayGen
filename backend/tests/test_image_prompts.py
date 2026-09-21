from app.services.image_service import (
    ImageGenerationError,
    assemble_positive_prompt,
    build_workflow,
    sanitize_tags,
)


def test_quality_prefix_is_added() -> None:
    prompt = assemble_positive_prompt("1girl, standing, forest")
    assert prompt == "masterpiece, best quality, amazing quality, general, 1girl, standing, forest, adult"


def test_banned_tokens_removed() -> None:
    tags = sanitize_tags("1girl, nsfw, explicit, questionable, sensitive, masterpiece, general, forest")
    assert tags == ["1girl", "forest"]


def test_case_insensitive_ban() -> None:
    tags = sanitize_tags("NSFW, Best Quality, forest")
    assert tags == ["forest"]


def test_adult_added_for_person_tags() -> None:
    prompt = assemble_positive_prompt("1girl, cloak, forest")
    assert "adult" in prompt
    prompt = assemble_positive_prompt("landscape, no humans, forest")
    assert "adult" not in prompt


def test_adult_not_duplicated() -> None:
    tags = sanitize_tags("1boy, adult, armor")
    assert tags.count("adult") == 1


def test_hero_tags_prepended() -> None:
    prompt = assemble_positive_prompt("standing, forest", hero_tags="1girl, green eyes, red coat")
    assert "general, 1girl, green eyes, red coat, standing, forest" in prompt


def test_workflow_nodes_filled() -> None:
    wf = build_workflow("wide", "test prompt", "story_1_2", seed=42)
    assert wf["6"]["inputs"]["text"] == "test prompt"
    assert wf["3"]["inputs"]["seed"] == 42
    assert wf["13"]["inputs"]["seed"] == 42
    assert wf["9"]["inputs"]["filename_prefix"] == "story_1_2"
    # untouched structure
    assert wf["4"]["inputs"]["ckpt_name"] == "waiIllustriousSDXL_v170.safetensors"
    assert wf["15"]["class_type"] == "LoraLoader"


def test_workflow_invalid_format_falls_back_to_wide() -> None:
    wf = build_workflow("panorama", "p", "x")
    assert wf["5"]["inputs"]["width"] == 1344  # wide workflow dims


def test_both_workflows_load_and_validate() -> None:
    for fmt in ("portrait", "wide"):
        wf = build_workflow(fmt, "p", "x")
        assert wf["6"]["class_type"] == "CLIPTextEncode"


def test_missing_workflow_file_fails_clearly(tmp_path, monkeypatch) -> None:
    import app.services.image_service as svc

    monkeypatch.setattr(svc, "WORKFLOWS_DIR", tmp_path)
    try:
        build_workflow("wide", "p", "x")
        raise AssertionError("should have raised")
    except ImageGenerationError as exc:
        assert "not found" in str(exc)
