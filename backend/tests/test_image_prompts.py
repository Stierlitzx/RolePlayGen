import pytest

from app.services import image_service
from app.services.image_service import (
    ImageGenerationError,
    assemble_edit_prompt,
    assemble_portrait_edit_prompt,
    assemble_positive_prompt,
    build_edit_workflow,
    build_workflow,
    group_scene_negative,
    sanitize_tags,
)


def _tags(prompt: str) -> list[str]:
    return [tag.strip() for tag in prompt.split(",") if tag.strip()]


def test_the_style_opens_and_closes_the_prompt() -> None:
    # A single style word buried in front of a long descriptive vocabulary loses:
    # an anime story came back photorealistic, and two people in one frame were
    # even drawn in different styles. The style anchors both ends now.
    scene = assemble_positive_prompt(
        "1girl, standing by river, dewy sheen, silky skin, overcast lighting",
        "1girl, red hair, adult",
        style_tags="anime style",
        world_tags="medieval fantasy",
    )
    assert scene.startswith("anime style, general,")
    assert scene.endswith("anime style")
    assert scene.count("anime style") == 2

    portrait = image_service.assemble_portrait_prompt(
        "1girl, brown hair, adult", style_tags="anime style"
    )
    assert portrait.startswith("anime style,")
    assert portrait.endswith("anime style")

    # No style configured (stories without the field): nothing is added.
    plain = assemble_positive_prompt("1girl, forest")
    assert plain == "general, 1girl, forest, adult"


def test_quality_prefix_is_only_the_rating_token() -> None:
    # on Qwen-Image-2.1 those tags produce the flat, cartoonish look the user
    # does not get in their own ComfyUI workflow. The rating token stays.
    prompt = assemble_positive_prompt("1girl, standing, forest")
    assert prompt == "general, 1girl, standing, forest, adult"
    assert "masterpiece" not in prompt and "best quality" not in prompt


def test_content_tags_pass_through() -> None:
    # Content filtering is off (DECISIONS 2026-09-25): the narrator's own
    # rating/nudity words reach the image model untouched. Only the quality
    # words the backend writes into its own prefix are dropped, so they cannot
    # be duplicated.
    tags = sanitize_tags("1girl, nsfw, explicit, questionable, sensitive, masterpiece, general, forest")
    assert tags == ["1girl", "nsfw", "explicit", "questionable", "sensitive", "forest"]


def test_quality_words_are_dropped_case_insensitively() -> None:
    tags = sanitize_tags("NSFW, Best Quality, forest")
    assert tags == ["NSFW", "forest"]


def test_adult_added_for_person_tags() -> None:
    prompt = assemble_positive_prompt("1girl, cloak, forest")
    assert "adult" in prompt
    prompt = assemble_positive_prompt("landscape, no humans, forest")
    assert "adult" not in prompt


def test_narrator_tags_contradicting_stored_appearance_are_stripped() -> None:
    # A small narrator invented a different look for the hero in the scene
    # tags (ponytail, long hair, green eyes) while the stored appearance says
    # wolfcut, short blonde hair, amber eyes. Scene tags lead the prompt, so
    # without the guard the hallucinated look would win.
    prompt = assemble_positive_prompt(
        "1girl, ponytail, long hair, green eyes, standing, forest",
        hero_tags="1girl, wolfcut, short hair, blonde hair, amber eyes",
    )
    for wrong in ("ponytail", "long hair", "green eyes"):
        assert wrong not in prompt
    # the stored anchors are spliced in and stay
    for anchor in ("wolfcut", "short hair", "blonde hair", "amber eyes"):
        assert anchor in prompt


def test_narrator_tags_matching_stored_appearance_are_kept() -> None:
    # The wide-shot rule ASKS the narrator to repeat key appearance anchors —
    # a matching restatement must survive (and a group the anchors do not
    # define, like the NPC's black hair, is untouched).
    prompt = assemble_positive_prompt(
        "1girl, ponytail, wolfcut, standing, forest",
        hero_tags="1girl, wolfcut, short hair, blonde hair",
    )
    assert "wolfcut" in prompt
    # anchors define a hairstyle (wolfcut): the contradicting ponytail goes
    assert "ponytail" not in prompt
    prompt = assemble_positive_prompt(
        "1girl, green eyes, standing, forest",
        hero_tags="1girl, wolfcut, short hair",
    )
    assert "green eyes" in prompt  # anchors define no eye color -> kept


def test_adult_not_duplicated() -> None:
    tags = sanitize_tags("1boy, adult, armor")
    assert tags.count("adult") == 1


def test_scene_tags_lead_appearance_tags() -> None:
    # The narrator's scene description must come first: earlier tokens dominate
    # the composition, and leading with the hero's look turns a thin scene
    # prompt into a character pin-up on an empty background.
    prompt = assemble_positive_prompt("standing, forest", hero_tags="1girl, green eyes, red coat")
    assert "general, standing, forest, 1girl, green eyes, red coat" in prompt


def test_workflow_nodes_filled() -> None:
    wf = build_workflow("wide", "test prompt", "story_1_2", seed=42)
    assert wf["6"]["inputs"]["prompt"] == "test prompt"
    assert wf["6"]["class_type"] == "TextEncodeQwenImage21"
    assert wf["8"]["inputs"]["seed"] == 42
    assert wf["8"]["class_type"] == "KSampler"
    assert wf["10"]["inputs"]["filename_prefix"] == "story_1_2"
    # untouched structure: single-pass Qwen-Image-2.1, no hires-fix
    assert wf["8"]["inputs"]["cfg"] == 1
    assert wf["1"]["inputs"]["unet_name"] == "qwen_image_2.1_int8_convrot.safetensors"
    assert wf["4"]["class_type"] == "LoraLoader"


def test_sampler_steps_are_configurable() -> None:
    # Generation time is roughly linear in the step count, and 12-16 is the
    # range where Qwen-Image still holds detail — so the step count is a setting,
    # not a constant baked into the workflow file.
    assert build_workflow("wide", "p", "prefix", steps=16)["8"]["inputs"]["steps"] == 16
    assert build_workflow("portrait", "p", "prefix", steps=16)["8"]["inputs"]["steps"] == 16
    # No steps given: the workflow file's own value survives.
    assert build_workflow("wide", "p", "prefix")["8"]["inputs"]["steps"] == 25


def test_workflow_invalid_format_falls_back_to_wide() -> None:
    wf = build_workflow("panorama", "p", "x")
    assert wf["7"]["inputs"]["width"] == 1568  # wide workflow dims


def test_both_workflows_load_and_validate() -> None:
    for fmt in ("portrait", "wide"):
        wf = build_workflow(fmt, "p", "x")
        assert wf["6"]["class_type"] == "TextEncodeQwenImage21"


def test_edit_workflow_wires_the_target_and_the_references() -> None:
    # The Qwen edit template sees its pictures as <image1>, <image2>, ... through
    # the TextEncodeQwenImage21 `images` input, so the graph has to carry a
    # LoadImage per slot and link them in that exact order.
    wf = build_edit_workflow(
        "wide", "put him from <image2> into <image1>", "roleplaygen/story_1/scene_3",
        target="hero.png", references=["npc_1.png", "npc_2.png"], seed=11, steps=16,
    )
    assert wf["6"]["inputs"]["images"] == [["100", 0], ["101", 0], ["102", 0]]
    assert wf["100"]["inputs"]["image"] == "hero.png"
    assert wf["101"]["inputs"]["image"] == "npc_1.png"
    assert wf["102"]["inputs"]["image"] == "npc_2.png"
    assert wf["6"]["inputs"]["prompt"].startswith("put him")
    assert wf["8"]["inputs"]["seed"] == 11
    assert wf["8"]["inputs"]["steps"] == 16
    assert wf["10"]["inputs"]["filename_prefix"] == "roleplaygen/story_1/scene_3"
    # A target means real image-to-image: the sampler starts from the encoded
    # target latent (switch=false picks `on_false`), not from an empty canvas.
    assert wf["9"]["inputs"]["switch"] is False
    assert wf["9"]["inputs"]["on_false"] == ["6", 2]


def test_edit_workflow_cap_is_ten_images() -> None:
    # The ComfyUI template exposes ten slots; anything beyond that is dropped
    # with a log line rather than silently producing a graph ComfyUI rejects.
    wf = build_edit_workflow(
        "portrait", "p", "prefix", target="hero.png",
        references=[f"ref_{index}.png" for index in range(20)],
    )
    assert len(wf["6"]["inputs"]["images"]) == 10
    assert wf["109"]["inputs"]["image"] == "ref_8.png"


def test_edit_workflow_without_a_target_starts_from_an_empty_canvas() -> None:
    # References alone (no picture to edit) must not leave the switch pointing at
    # an encoded image that does not exist.
    wf = build_edit_workflow("wide", "p", "prefix", target=None, references=["hero.png"])
    assert wf["6"]["inputs"]["images"] == [["100", 0]]
    assert wf["100"]["inputs"]["image"] == "hero.png"
    assert wf["9"]["inputs"]["switch"] is True


def test_edit_workflow_needs_at_least_one_image() -> None:
    with pytest.raises(ImageGenerationError, match="at least one image"):
        build_edit_workflow("wide", "p", "prefix")


def test_custom_size_overrides_the_target_canvas() -> None:
    wf = build_edit_workflow("wide", "p", "prefix", target="hero.png", custom_size=True)
    assert wf["9"]["inputs"]["switch"] is True
    assert wf["7"]["inputs"]["width"] == 1568


def test_edit_prompt_addresses_the_pictures_by_number() -> None:
    # The encoder reads the pictures, so the text has to say what each one IS;
    # a bare tag list would describe people who are not in the frame.
    prompt = assemble_edit_prompt("general, 1girl, forest, adult", "Mira", [(2, "Kaelen")])
    assert "<image1> is Mira" in prompt
    assert "<image2> is Kaelen" in prompt
    assert "forest" in prompt
    # No pictures at all: the tags are the prompt, exactly as before (modulo the
    # separator the edit model reads more easily than a bare tag string).
    assert assemble_edit_prompt("general, 1girl, forest, adult", None, []) == (
        "general, 1girl, forest, adult"
    )


def test_portrait_edit_prompt_says_keep_the_face_and_change_the_look() -> None:
    from_photo = assemble_portrait_edit_prompt("1girl, red cloak, adult", True)
    assert "own photograph" in from_photo
    assert "red cloak" in from_photo
    # The tags must not be allowed to repaint the person: the instruction says
    # they describe the clothes only.
    assert "ONLY the clothes" in from_photo
    assert from_photo.index("keep their") < from_photo.index("1girl"), (
        "the face instruction has to come before the tag list"
    )
    assert "earlier picture" in assemble_portrait_edit_prompt("1girl, red cloak, adult", False)


def test_the_hero_photo_from_setup_also_drives_their_portrait(
    db_session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The bug: the setup photo was image_1 for every SCENE, but the hero's own
    # portrait was still painted from tags — the player got their own face in
    # the story and a stranger on the character's card.
    from app.models import Character, Story

    story = Story(title="t", settings={"hero_image": "9/hero_photo.png"}, max_turns=None)
    db_session.add(story)
    db_session.flush()
    (tmp_path / "9").mkdir()
    (tmp_path / "9" / "hero_photo.png").write_bytes(b"\x89PNG the player's face")
    hero = Character(
        story_id=story.id, name="Lira", is_hero=True,
        appearance_tags="1girl, elf, adult", portrait_status="none",
    )
    npc = Character(
        story_id=story.id, name="Tarik", appearance_tags="1boy, adult", portrait_status="none"
    )
    db_session.add_all([hero, npc])
    db_session.commit()

    settings = image_service.Settings(image_dir=str(tmp_path), mock_images=False)
    data, label = image_service.portrait_edit_source(db_session, hero, settings)
    assert data == b"\x89PNG the player's face"
    assert "hero photo uploaded at setup" in label
    # The prompt for that source must insist on the player's own face.
    assert "own photograph" in image_service.assemble_portrait_edit_prompt("1girl, cloak", True)
    # An NPC without a picture of their own is unaffected.
    assert image_service.portrait_edit_source(db_session, npc, settings) is None


def test_every_picture_gets_a_log_even_an_old_one(
    db_session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A log written only at generation time is empty for most of an old story,
    # and an empty button looks broken. The prompt is rebuilt from the stored
    # scene prompt instead — possible precisely because the seed is fixed.
    from app.models import Character, Story, Turn
    from sqlalchemy.orm import sessionmaker

    story = Story(title="t", settings={"image_style": "Anime (default)",
                                      "age_rating": "18+", "explicit_sexual": True},
                  max_turns=None)
    db_session.add(story)
    db_session.flush()
    db_session.add(Turn(
        story_id=story.id, index=0, player_input_type="start", player_input_text=None,
        narration="Once upon a time.", choice=None, state={"scene": "River", "summary": "s",
                                                          "facts": []}, is_ending=False,
        image_prompt="1girl, standing by river, morning mist",
        image_status="done", image_path=f"{story.id}/1.png", image_build_log=None,
    ))
    db_session.add(Character(
        story_id=story.id, name="Lira", is_hero=True, appearance_tags="1girl, elf, adult",
        portrait_status="done", portrait_path=f"{story.id}/char_1.png", portrait_build_log=None,
    ))
    db_session.commit()

    settings = image_service.Settings(
        image_dir=str(tmp_path), image_generation_enabled=True, mock_llm=True
    )
    story = db_session.get(Story, story.id)
    image_service.ensure_build_logs(db_session, list(story.turns), settings)
    image_service.ensure_portrait_build_logs(list(story.characters), settings)

    turn_log = story.turns[0].image_build_log
    assert turn_log and "rebuilt from the stored scene prompt" in turn_log
    assert "anime" in turn_log
    assert f"seed: {settings.image_seed}" in turn_log
    assert "Standing by river" in turn_log  # the stored tag list is de-tagged
    assert story.characters[0].portrait_build_log
    assert "rebuilt from the stored look" in story.characters[0].portrait_build_log


def test_a_stored_age_reaches_the_picture_prompts() -> None:
    # "a woman in her fifties" has to travel all the way into the caption, or a
    # mother keeps being painted as a teenager.
    from app.models import Character

    mother = Character(
        id=1, story_id=1, name="Mara", is_hero=False,
        appearance_tags="a grey-haired woman in a plain dress", age="a woman in her fifties",
    )
    caption = image_service.assemble_portrait_caption(
        mother.appearance_tags, pose="standing by the door", expression="a tired smile",
        style="a modern anime illustration, cel shading", age=mother.age or "",
    )
    assert "a woman in her fifties" in caption
    assert "grey-haired woman" in caption
    assert caption.startswith("A modern anime illustration")
    assert image_service._look_with_age(mother) == (
        "A grey-haired woman in a plain dress, a woman in her fifties"
    )
    # A cat has no human age: nothing is added.
    cat = Character(id=2, story_id=1, name="Shadow", appearance_tags="a black cat", age=None)
    assert image_service._look_with_age(cat) == "A black cat"
    assert "years" not in image_service.assemble_portrait_caption(cat.appearance_tags)

    # Never shown to the player: the field is not part of the API schema.
    from app.schemas import CharacterRead

    assert "age" not in CharacterRead.model_fields


def test_the_build_log_says_what_the_picture_model_was_told() -> None:
    # The "Image log" button shows this verbatim, so it has to name the mode and
    # the references — that is how a player tells "the photo was ignored" from
    # "the photo was used and the result is simply different".
    log = image_service.format_build_log(
        "edit (image_1 = the player's photo)", "a woman in a cloak", 16, 42,
        ["hero_photo.png", "ref_7.png"],
    )
    assert "mode: edit (image_1 = the player's photo)" in log
    assert "steps: 16" in log
    assert "references: hero_photo.png, ref_7.png" in log
    assert log.endswith("prompt:\na woman in a cloak")
    assert "references: none" in image_service.format_build_log("text to image", "p", 25, 1)


def test_a_data_url_decodes_and_a_junk_one_is_rejected() -> None:
    data = image_service.decode_upload("data:image/png;base64,aGVsbG8=")
    assert data == b"hello"
    with pytest.raises(ImageGenerationError, match="data URL"):
        image_service.decode_upload("not-a-data-url")
    with pytest.raises(ImageGenerationError, match="Unsupported picture format"):
        image_service.decode_upload("data:image/tiff;base64,aGVsbG8=")
    with pytest.raises(ImageGenerationError, match="base64"):
        image_service.decode_upload("data:image/png;base64,!!!")


def test_missing_workflow_file_fails_clearly(tmp_path, monkeypatch) -> None:
    import app.services.image_service as svc

    monkeypatch.setattr(svc, "WORKFLOWS_DIR", tmp_path)
    try:
        build_workflow("wide", "p", "x")
        raise AssertionError("should have raised")
    except ImageGenerationError as exc:
        assert "not found" in str(exc)


def test_spliced_appearance_is_never_edited_for_an_explicit_nude_scene() -> None:
    # Content filtering is off: the "fully clothed" default is no longer dropped
    # even when an 18+ explicit story tags the scene as nude. The backend does
    # not edit content any more — the conflicting tags go to the model as stored.
    prompt = assemble_positive_prompt(
        "1girl, nude, medium shot, bedroom, warm lighting",
        hero_tags="1girl, platinum hair, red silk blouse, fully clothed",
        character_tags=["1boy, grey beard, black coat, fully clothed"],
        explicit=True,
    )
    assert "nude" in prompt
    assert "fully clothed" in prompt
    assert "platinum hair" in prompt and "grey beard" in prompt


def test_clothing_guard_kept_otherwise() -> None:
    # The spliced "fully clothed" default survives in every scene while content
    # filtering is off — explicit or not.
    prompt = assemble_positive_prompt(
        "1girl, nude, forest",
        hero_tags="1girl, red coat, fully clothed",
        explicit=False,
    )
    assert "fully clothed" in prompt

    prompt = assemble_positive_prompt(
        "1girl, standing, tavern",
        hero_tags="1girl, red coat, fully clothed",
        explicit=True,
    )
    assert "fully clothed" in prompt


def test_group_scene_becomes_a_two_shot_facing_each_other() -> None:
    # The narrator wrote a solo close-up at the camera although an enemy stands
    # right there: "solo"/"1girl" would delete him from the picture, "close-up"
    # would crop him out, "looking at viewer" would turn both faces to the lens.
    prompt = assemble_positive_prompt(
        "1girl, solo, adult, close-up, looking at viewer, inside a wooden hut, hearth fire, tense",
        hero_tags="1girl, platinum hair, amber eyes, white blouse",
        character_tags=["1boy, black hood, knife, angry"],
    )
    tags = _tags(prompt)
    assert "solo" not in tags
    assert "looking at viewer" not in tags
    assert "close-up" not in tags
    assert "1girl" in tags and "1boy" in tags
    assert "medium wide shot" in tags
    for interaction in ("two-shot", "facing each other", "looking at each other"):
        assert interaction in tags
    # The place keeps its place in the tag list, right after the two-shot block.
    assert "inside a wooden hut" in tags
    # One shot tag, and the interaction follows it.
    assert tags.index("medium wide shot") < tags.index("facing each other")


def test_single_character_scene_keeps_its_tight_framing() -> None:
    # The camera stays close for one character — that rule is untouched.
    prompt = assemble_positive_prompt(
        "1girl, solo, cowboy shot, looking at viewer, tavern",
        hero_tags="1girl, platinum hair",
    )
    tags = _tags(prompt)
    assert "cowboy shot" in tags
    assert "looking at viewer" in tags and "solo" in tags
    assert "facing each other" not in tags
    assert "two-shot" not in tags


def test_group_scene_keeps_the_wide_shot_it_was_given() -> None:
    prompt = assemble_positive_prompt(
        "1boy, 1girl, wide shot, looking at each other, harbor, sunrise",
        hero_tags="1girl, red hair",
        character_tags=["1boy, tricorn hat"],
    )
    tags = _tags(prompt)
    assert tags.count("wide shot") == 1
    assert "medium wide shot" not in tags
    assert tags.count("looking at each other") == 1  # never duplicated


def test_group_scene_without_a_shot_tag_still_gets_one() -> None:
    prompt = assemble_positive_prompt(
        "1girl, looking at viewer, throne room, candles",
        hero_tags="1girl, red hair",
        character_tags=["1boy, crown"],
    )
    tags = _tags(prompt)
    assert "medium wide shot" in tags
    assert "two-shot" in tags


def test_scene_characters_answer_for_anchors_that_are_not_there_yet() -> None:
    # characters_in_scene knows a second person is in the frame, even before
    # their appearance anchors exist: the frame still has to fit both.
    prompt = assemble_positive_prompt(
        "1girl, close-up, looking at viewer, hut",
        hero_tags="1girl, platinum hair",
        scene_characters=2,
    )
    tags = _tags(prompt)
    assert "medium wide shot" in tags and "facing each other" in tags
    assert "1girl" in tags  # only one gender is known, so no invented count tag


def test_group_scene_negative_only_for_several_characters() -> None:
    assert group_scene_negative(3) == "looking at viewer"
    assert group_scene_negative(1) == ""


def test_world_anchor_pins_the_era_after_the_place() -> None:
    prompt = assemble_positive_prompt(
        "wooden hut interior, log walls, hearth fire",
        hero_tags="1girl, red cloak",
        world_tags="medieval fantasy setting, rustic stone and timber architecture",
    )
    hut = prompt.index("wooden hut interior")
    anchor = prompt.index("medieval fantasy setting")
    hero = prompt.index("red cloak")
    assert hut < anchor < hero  # place first, era next, appearance after
    assert prompt.startswith("general, ")


def test_no_world_anchor_leaves_the_prompt_untouched() -> None:
    prompt = assemble_positive_prompt("standing, forest", hero_tags="1girl")
    assert "medieval" not in prompt
    assert group_scene_negative(None) == ""
