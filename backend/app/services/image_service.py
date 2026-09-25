"""Background scene illustrations via a local ComfyUI server.

One in-process queue with a single worker: jobs run strictly one at a time.
Failures never propagate into the text flow — they are stored on the turn.
"""

import base64
import binascii
import copy
import json
import logging
import queue
import random
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..db import SessionLocal
from ..models import Character, Story, Turn
from ..setup_options import image_style_tags, images_are_explicit, setting_anchor
from .character_matching import find_character

logger = logging.getLogger(__name__)

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "comfy_workflows"
FORMATS = ("portrait", "wide")
# Qwen-Image-2.1, single pass (no hires-fix): one TextEncode node carries the
# prompt (positive + an unused negative input), one sampler, one SaveImage.
REQUIRED_NODES = {"6": "TextEncodeQwenImage21", "8": "KSampler", "10": "SaveImage"}

# The SDXL-era quality prefix ("masterpiece, best quality, amazing quality") is
# GONE. Qwen-Image-2.1 reads natural language and those tags dragged it into the
# flat, oversaturated, cartoonish look of an old SDXL anime checkpoint, which is
# not what the user's own ComfyUI workflow produces. What remains is the rating
# token — the rating stays the backend's decision, never the narrator's.
QUALITY_TOKENS_SET = {"masterpiece", "best quality", "amazing quality", "general"}
# Portrait framing: a reference card is head-to-thighs so the face keeps detail
# (deliberate, see DECISIONS 2026-09-23). The POSE is not the backend's to
# choose: hardcoding "standing, looking at viewer" made every character of every
# story come out in the same pose and overrode the narrator's own per-portrait
# tags. The framing is added only when the character's own tags do not name a
# shot, and the pose/gaze are only a fallback for a portrait the narrator left
# blank.
PORTRAIT_SUFFIX = ["cowboy shot", "simple background"]
PORTRAIT_FALLBACK_POSE = "standing"
PORTRAIT_FALLBACK_GAZE = "looking at viewer"
# A portrait is the character's reference card, so the FACE has to be visible. A
# narrator pose like "glancing over her shoulder" — or a stray "from behind" —
# renders her back to the camera and the card is worthless: portraits came out
# showing her back even though "looking at viewer" was in the prompt, because
# the narrator's own tag contradicted it. These tags are dropped from a portrait
# look (never from a scene) and the frontal gaze is restored.
BACK_TURNED_TAGS = re.compile(
    r"from behind|from the back|back view|seen from behind|back to ?(?:the )?viewer|"
    r"back turned|facing away|facing back|facing the other way|turning away|turned away|"
    r"looking back|glancing back|over (?:her|his|their|the) shoulder|looking over shoulder",
    re.IGNORECASE,
)
# A gaze the narrator DID state is kept, even an averted one: the face is still
# visible in a three-quarter view, and the character's own mood wins.
AVERTED_GAZE_TAGS = {
    "looking away", "glancing away", "looking to the side", "sideways glance",
    "looking down", "looking up", "eyes closed", "eyes looking away",
}
# Content tag filtering is DISABLED for now (see DECISIONS 2026-09-25): the
# narrator's own nudity and rating words (nsfw, explicit, nude, ...) reach the
# image model untouched, and the backend no longer edits the content of a
# prompt. The only vocabulary it still drops is the quality/rating vocabulary it
# writes itself, so a narrator repeating it cannot duplicate it.
PERSON_TAGS = {"1girl", "1boy", "2girls", "2boys", "1other", "multiple girls", "multiple boys"}
# The nudity DETECTOR — not a filter. These tokens are the text model's only
# channel to say "this character really is naked in the story right now", and
# they decide one thing: whether a portrait may be rated explicit
# (see portrait_wants_nudity). Nothing is stripped because of them.
NUDITY_TOKENS = {
    "nude", "naked", "topless", "bottomless", "undressing", "nipples",
    "pussy", "penis", "erection", "breasts out", "clothes aside", "sex",
    "cum", "nsfw", "explicit", "questionable",
}

# --- Group-scene composition guard -------------------------------------------
# The narrator writes the framing, but a wall of "1girl, solo, cowboy shot,
# looking at viewer" tags survives even when two characters are standing in the
# same scene: "solo" and the single person tag push the second character out of
# the frame, the tight crop cuts them away, and "looking at viewer" turns every
# face in the picture towards the lens. The scene tags lead the prompt (and the
# narrator has no memory between generations), so the backend rewrites them
# deterministically instead of hoping the model obeys.
SHOT_TAGS = (
    "extreme close-up", "close-up", "upper body", "portrait",
    "cowboy shot", "medium shot", "medium wide shot", "wide shot", "full body",
)
GROUP_SHOT = "medium wide shot"
# The widest shot a group scene may be pulled back to when it wrote its own;
# anything tighter is replaced, so nobody is cropped out of the picture.
GROUP_KEEP_SHOTS = {"medium wide shot", "wide shot"}
GROUP_INTERACTION_TAGS = ["two-shot", "facing each other", "looking at each other"]
# Tags that turn the whole frame towards the lens — dropped from a group scene.
DIRECT_ADDRESS_TAGS = {
    "looking at viewer", "looking at camera", "facing viewer", "eye contact with viewer",
}
# Single-person tags contradict a scene with several people in it.
LONE_PERSON_TAGS = {"solo", "1girl", "1boy", "1other"}
GROUP_SCENE_NEGATIVE = "looking at viewer"
_GIRL_TAGS = {"1girl", "2girls", "multiple girls"}
_BOY_TAGS = {"1boy", "2boys", "multiple boys"}

# Words that name a PLACE. They are what tells a location tag ("dark forest
# background with twisted trees") apart from the tags describing people, light,
# mood or action — see previous_scene_negative. Composition words that add no
# location of their own ("background", "foreground") are deliberately absent:
# "Garret in the background with knife" is a character tag, and negating it
# would push that character out of the new scene.
PLACE_WORDS = {
    "alley", "balcony", "bank", "beach", "bridge", "building",
    "cabin", "camp", "castle", "cave", "cavern", "ceiling", "chamber", "church",
    "city", "clearing", "cliff", "corridor", "cottage", "courtyard", "deck",
    "desert", "dungeon", "field", "floor", "forest", "garden", "ground",
    "grove", "hall", "hill", "hut", "inn", "interior", "jungle", "kitchen",
    "lake", "market", "meadow", "mountain", "palace", "path", "plain", "plaza",
    "pool", "port", "road", "roof", "room", "ruins", "sea", "shore", "square",
    "stable", "street", "swamp", "tavern", "temple", "tent", "tower", "town",
    "trail", "tree", "trees", "tunnel", "valley", "village", "wall", "walls",
    "window", "woods", "yard",
}
# A left-behind scene never needs more than a handful of negated tags; a long
# negative list starts to fight the story's own setting.
MAX_PREVIOUS_SCENE_NEGATIVES = 4

# Identity attribute groups: when the stored appearance tags define a value in
# a group, the narrator's scene tags may not contradict it. Small narrators
# routinely invent a different hairstyle or eye color in image_prompt
# ("ponytail" when the hero's stored look is a wolfcut), and because scene
# tags deliberately lead the prompt (see assemble_positive_prompt), the
# hallucinated look would otherwise win over the spliced anchors.
_HAIR_COLOR_WORDS = {
    "blonde", "platinum", "black", "brown", "red", "ginger", "auburn",
    "white", "silver", "grey", "gray", "blue", "green", "pink", "purple",
    "orange", "golden", "ash", "scarlet", "crimson", "cyan", "teal",
    "lavender", "dark", "light",
}
_HAIR_LENGTH_TOKENS = {
    "short hair", "medium hair", "long hair", "very long hair",
    "absurdly long hair", "shoulder-length hair",
}
_HAIR_STYLE_TOKENS = {
    "ponytail", "high ponytail", "side ponytail", "twintails", "twin braids",
    "single braid", "braid", "braided ponytail", "wolfcut", "wolf cut",
    "bob cut", "pixie cut", "hime cut", "hair bun", "double bun", "odango",
    "drill hair", "ringlets", "dreadlocks", "afro", "mohawk", "undercut",
    "messy hair", "wavy hair", "curly hair", "straight hair",
}


def _hair_color(tag: str) -> str | None:
    match = re.fullmatch(r"(.+?) hair", tag)
    if match and any(word in match.group(1).split() for word in _HAIR_COLOR_WORDS):
        return match.group(1)
    return None


def _eye_color(tag: str) -> str | None:
    match = re.fullmatch(r"(.+?) eyes", tag)
    return match.group(1) if match else None


def _strip_appearance_conflicts(narrator_tags: list[str], anchor_tags: str) -> list[str]:
    """Drop narrator scene tags that contradict the stored appearance anchors
    on identity attributes (hair color/length/style, eye color). Only groups
    the anchors actually define are enforced, and a narrator token that matches
    an anchor value is kept (repeating the right look is fine — the wide-shot
    anchor rule asks for it)."""
    anchors = [tag.strip().lower() for tag in anchor_tags.split(",") if tag.strip()]
    anchor_hair = {color for tag in anchors if (color := _hair_color(tag))}
    anchor_eyes = {color for tag in anchors if (color := _eye_color(tag))}
    anchor_lengths = {tag for tag in anchors if tag in _HAIR_LENGTH_TOKENS}
    anchor_styles = {tag for tag in anchors if tag in _HAIR_STYLE_TOKENS}
    kept: list[str] = []
    for tag in narrator_tags:
        low = tag.lower()
        if (color := _hair_color(low)) and anchor_hair and color not in anchor_hair:
            continue
        if (color := _eye_color(low)) and anchor_eyes and color not in anchor_eyes:
            continue
        if low in _HAIR_LENGTH_TOKENS and anchor_lengths and low not in anchor_lengths:
            continue
        if low in _HAIR_STYLE_TOKENS and anchor_styles and low not in anchor_styles:
            continue
        kept.append(tag)
    dropped = len(narrator_tags) - len(kept)
    if dropped:
        logger.info("stripped %d scene tag(s) contradicting the stored appearance", dropped)
    return kept


def _ollama_unload(settings: Settings) -> None:
    """Ask Ollama to drop the text model from VRAM (keep_alive: 0).

    Best-effort: a non-Ollama endpoint answers 404, a stopped server times
    out — both are logged and ignored, the image job proceeds regardless.
    """
    base = (settings.openai_base_url or "").strip().rstrip("/")
    if not base:
        return
    if base.endswith("/v1"):
        base = base[:-3]
    try:
        httpx.post(
            f"{base}/api/generate",
            json={"model": settings.openai_model, "keep_alive": 0},
            timeout=10.0,
        )
        logger.info("VRAM conductor: asked the text model server to unload %s", settings.openai_model)
    except httpx.HTTPError as exc:
        logger.warning("VRAM conductor: could not unload the text model: %s", exc)


def _comfyui_free(settings: Settings) -> None:
    """Ask ComfyUI to drop its model cache after a job (POST /free)."""
    try:
        httpx.post(
            f"{settings.comfyui_url.rstrip('/')}/free",
            json={"unload_models": True, "free_memory": True},
            timeout=10.0,
        )
        logger.info("VRAM conductor: ComfyUI model cache freed")
    except httpx.HTTPError as exc:
        logger.warning("VRAM conductor: could not free ComfyUI memory: %s", exc)


def _quality_prefix(explicit: bool) -> list[str]:
    """The rating token only — the narrator's quality words are dropped, the
    prefix never adds any (see the comment on QUALITY_TOKENS_SET)."""
    return ["explicit" if explicit else "general"]


class ImageGenerationError(RuntimeError):
    pass


def sanitize_tags(image_prompt: str, allow_explicit: bool = False) -> list[str]:
    """Split the narrator's tag string, trim it and drop the backend's own
    quality/rating words (it writes that prefix itself, so a narrator repeating
    it would only duplicate it).

    Content is NOT filtered while filtering is off (see DECISIONS 2026-09-25):
    a nudity or rating tag the narrator wrote reaches the image model as it is.
    `allow_explicit` is kept for signature compatibility.
    """
    del allow_explicit  # the rating token is added by _quality_prefix, not here
    tags: list[str] = []
    for raw in image_prompt.split(","):
        tag = raw.strip()
        if tag and tag.lower() not in QUALITY_TOKENS_SET:
            tags.append(tag)
    return tags


def _anchor_gender(anchor_tags: str) -> str | None:
    """The gender one character's stored appearance tags state, if they do."""
    for tag in anchor_tags.split(","):
        low = tag.strip().lower()
        if low in _GIRL_TAGS:
            return "girl"
        if low in _BOY_TAGS:
            return "boy"
    return None


def _group_person_tags(anchor_groups: list[str]) -> list[str]:
    """The person-count tags a two-shot needs, taken from the stored anchors.

    Empty when the genders in frame are unknown: those tags dominate the
    composition, so a wrong count is worse than no count at all.
    """
    genders = [gender for gender in (_anchor_gender(tags) for tags in anchor_groups) if gender]
    if len(genders) < 2:
        return []
    girls, boys = genders.count("girl"), genders.count("boy")
    tags: list[str] = []
    if girls >= 2:
        tags.append("2girls")
    elif girls == 1:
        tags.append("1girl")
    if boys >= 2:
        tags.append("2boys")
    elif boys == 1:
        tags.append("1boy")
    return tags


def _group_scene_tags(narrator_tags: list[str], anchor_groups: list[str]) -> list[str]:
    """Rewrite the narrator's scene tags for a frame shared by several people.

    Drops what deletes or hides the other people ("solo", a lone "1girl"/"1boy",
    "looking at viewer"), keeps at most one shot tag and never one tighter than
    a medium wide shot, and states the interaction the player should see: the
    characters face and look at EACH OTHER, not both into the lens.
    """
    rewritten: list[str] = []

    def keep(tag: str) -> None:
        """Add a tag unless the same tag is already in the rewritten list."""
        if tag.lower() in {existing.lower() for existing in rewritten}:
            return
        rewritten.append(tag)

    shot_done = False
    for tag in narrator_tags:
        low = tag.lower()
        if low in LONE_PERSON_TAGS or low in DIRECT_ADDRESS_TAGS:
            continue
        if low in SHOT_TAGS:
            if shot_done:
                continue
            shot_done = True
            keep(tag if low in GROUP_KEEP_SHOTS else GROUP_SHOT)
            for interaction in GROUP_INTERACTION_TAGS:
                keep(interaction)
            continue
        keep(tag)
    if not shot_done:
        rewritten = [GROUP_SHOT, *GROUP_INTERACTION_TAGS, *rewritten]
    return [*_group_person_tags(anchor_groups), *rewritten]


def group_scene_negative(scene_characters: int | None) -> str:
    """Negative tag for a frame with several characters in it.

    The prompt rewrite already asks for "looking at each other"; the negative
    stops a stubborn sampler from turning both faces back to the camera.
    """
    return GROUP_SCENE_NEGATIVE if (scene_characters or 0) >= 2 else ""


def _style_wrap(parts: list[str], style_tags: str) -> list[str]:
    """The story's art style opens AND closes the prompt.

    Qwen-Image is a natural-language model, and a single style word is easily
    outvoted by a long descriptive vocabulary: with "anime style" buried in
    front of a wall of photographic tags ("dewy sheen, silky skin, natural
    makeup, overcast lighting") the picture came back photorealistic, and the two
    people in one frame were even drawn in different styles. Repeating the style
    at the end anchors the medium from the other side, which is how diffusion
    models are usually steered.
    """
    style = style_tags.strip()
    if not style:
        return parts
    return [style, *parts, style]


def assemble_positive_prompt(
    image_prompt: str,
    hero_tags: str = "",
    character_tags: list[str] | None = None,
    style_tags: str = "",
    explicit: bool = False,
    scene_characters: int | None = None,
    world_tags: str = "",
) -> str:
    """Scene prompt: quality prefix (with the story's rating token), then the
    art style tags, then the narrator's scene tags, then the known appearance
    tags (hero first, then the other characters in scene order).

    Appearance is spliced in by the backend so a character keeps the same look
    across turns even though the text model has no memory between generations.
    It deliberately goes AFTER the narrator's scene tags: earlier tokens
    dominate the composition, and leading with the hero's appearance turns a
    thin scene prompt into a character pin-up on an empty background — the
    shot, place and action must come first.

    Clothing defaults ("fully clothed") and every other spliced tag are kept as
    stored while content filtering is off (DECISIONS 2026-09-25): the backend
    does not edit the scene's content any more.

    `scene_characters` is how many characters share the frame (from
    `characters_in_scene`); when it is omitted the spliced appearance anchors
    answer instead. With two or more, the narrator's scene tags go through the
    group-scene rewrite first, so a two-shot of characters facing each other
    replaces a tight single-person crop and both of them staring into the lens.
    """
    narrator_tags = sanitize_tags(image_prompt, allow_explicit=explicit)
    anchor_groups = [part for part in [hero_tags, *(character_tags or [])] if part.strip()]
    anchor_all = ", ".join(anchor_groups)
    narrator_tags = _strip_appearance_conflicts(narrator_tags, anchor_all)
    if scene_characters is None:
        scene_characters = len(anchor_groups)
    if scene_characters >= 2:
        narrator_tags = _group_scene_tags(narrator_tags, anchor_groups)
    parts: list[str] = _quality_prefix(explicit)
    tags = narrator_tags
    lowered = {t.lower() for t in tags}
    if lowered & PERSON_TAGS and "adult" not in lowered:
        tags.append("adult")
    parts.extend(tags)
    if world_tags.strip():
        # The story's WORLD anchors the picture: the narrator's place tags lead
        # the composition, but they do not pin the era — a medieval scene came
        # back with a modern house because "wooden hut" reads as any hut.
        parts.append(world_tags.strip())
    if hero_tags.strip():
        parts.append(hero_tags.strip())
    for ctags in character_tags or []:
        if ctags.strip():
            parts.append(ctags.strip())
    parts = _style_wrap(parts, style_tags)
    prompt = ", ".join(parts)
    logger.debug("image prompt: %s", prompt)
    return prompt


def portrait_wants_nudity(appearance_tags: str, pose: str = "", expression: str = "") -> bool:
    """True when the narrator deliberately described this look as nude/sexual.

    The signal is explicit nudity tags in the narrator's own tags — the only
    channel the text model has to say "this character is actually naked in the
    story right now". Combined with the story's explicit flag by the caller.
    """
    combined = f"{appearance_tags},{pose},{expression}"
    return any(tag.lower() in NUDITY_TOKENS for tag in sanitize_tags(combined, allow_explicit=True))


def assemble_portrait_prompt(
    appearance_tags: str,
    pose: str = "",
    expression: str = "",
    style_tags: str = "",
    explicit: bool = False,
    world_tags: str = "",
    age: str = "",
) -> str:
    """Portrait prompt: quality prefix + style + the character's own tags +
    this portrait's pose/expression + the reference-card framing.

    The pose, the gaze and the camera side belong to the character: whatever the
    narrator sent is kept — except a tag that turns her back to the camera
    (see BACK_TURNED_TAGS), because a reference card with no face on it is
    useless. A gaze the narrator did state wins; a look that names no gaze is
    given the frontal default. The head-to-thighs framing is added only when
    neither the appearance tags nor the pose already name a shot, so a narrator
    that wants a full-body card can ask for one.

    The rating token is still the backend's decision, not the narrator's: a
    portrait is general-rated unless the caller passes explicit=True, which
    happens only for an 18+ explicit story whose narrator tagged this look as
    nude (see portrait_wants_nudity). While content filtering is off
    (DECISIONS 2026-09-25) the narrator's own nudity tags are NOT stripped — a
    non-explicit portrait simply keeps the general rating token next to them.
    """
    parts: list[str] = _quality_prefix(explicit)
    tags = _drop_back_turned(sanitize_tags(appearance_tags, allow_explicit=explicit))
    # The age goes right after the look: without it a mother comes back as a
    # teenager, because "1girl, adult" says nothing about how old she is. A
    # creature with no human age simply has none stored and adds nothing.
    if age.strip():
        tags.append(age.strip())
    lowered = {t.lower() for t in tags}
    if lowered & PERSON_TAGS and "adult" not in lowered:
        tags.append("adult")
    parts.extend(tags)
    if world_tags.strip():
        # The world carries into the card too: a portrait rendered its own
        # background room, and that room has to belong to the story's era.
        parts.append(world_tags.strip())
    pose_tags: list[str] = []
    for extra in (pose, expression):
        cleaned = _drop_back_turned(sanitize_tags(extra, allow_explicit=explicit))
        pose_tags.extend(cleaned)
        if cleaned:
            parts.append(", ".join(cleaned))
    parts.extend(_portrait_framing(lowered, pose_tags))
    parts = _style_wrap(parts, style_tags)
    prompt = ", ".join(parts)
    logger.debug("portrait prompt: %s", prompt)
    return prompt


def _drop_back_turned(tags: list[str]) -> list[str]:
    """Drop tags that turn the character's back to the camera (portraits only)."""
    kept = [tag for tag in tags if not BACK_TURNED_TAGS.search(tag)]
    if len(kept) != len(tags):
        logger.debug("dropped back-turned portrait tag(s): %s", ", ".join(set(tags) - set(kept)))
    return kept


def _portrait_framing(character_tags: set[str], pose_tags: list[str]) -> list[str]:
    """Framing/fallback tail of a portrait prompt.

    `cowboy shot` (head to thighs) is the reference-card framing, but a
    character or pose tag that already picks a shot wins — a narrator asking for
    `full body` or `upper body` must not end up with the default on top of it.
    """
    stated = character_tags | {tag.lower() for tag in pose_tags}
    framing = [] if stated & set(SHOT_TAGS) else [PORTRAIT_SUFFIX[0]]
    fallback_pose = [] if pose_tags else [PORTRAIT_FALLBACK_POSE]
    # The face must be visible on the reference card: a gaze the narrator stated
    # (frontal or averted) wins; when the look names no gaze at all the frontal
    # default is added, because "arms crossed" alone left the model free to turn
    # the character away from the camera.
    gaze_stated = bool(stated & (DIRECT_ADDRESS_TAGS | AVERTED_GAZE_TAGS))
    fallback_gaze = [] if gaze_stated else [PORTRAIT_FALLBACK_GAZE]
    return [*framing, *fallback_pose, *fallback_gaze, PORTRAIT_SUFFIX[1]]


def load_workflow(image_format: str) -> dict[str, Any]:
    if image_format not in FORMATS:
        image_format = "wide"
    path = WORKFLOWS_DIR / f"{image_format}.json"
    if not path.exists():
        raise ImageGenerationError(f"Workflow file not found: {path}")
    workflow = json.loads(path.read_text(encoding="utf-8"))
    for node_id, class_type in REQUIRED_NODES.items():
        node = workflow.get(node_id)
        if node is None or node.get("class_type") != class_type:
            raise ImageGenerationError(
                f"Workflow {path.name} is missing required node {node_id} ({class_type})"
            )
    return workflow


def build_workflow(
    image_format: str,
    positive_prompt: str,
    filename_prefix: str,
    seed: int | None = None,
    negative_extra: str = "",
    steps: int | None = None,
) -> dict[str, Any]:
    workflow = copy.deepcopy(load_workflow(image_format))
    seed = seed if seed is not None else random.randint(0, 2**31 - 1)
    # Qwen-Image-2.1 (single-pass, cfg=1): one TextEncode node carries both
    # conditionings; the sampler's negative input is wired to the encoder's
    # negative output, so there is no separate negative-prompt node to fill.
    workflow["6"]["inputs"]["prompt"] = positive_prompt
    workflow["8"]["inputs"]["seed"] = seed
    if steps is not None:
        # Sampler steps are the only real cost knob: time grows roughly linearly,
        # and 12-16 is where Qwen-Image still holds detail (see IMAGE_STEPS).
        workflow["8"]["inputs"]["steps"] = steps
    workflow["10"]["inputs"]["filename_prefix"] = filename_prefix
    if negative_extra.strip():
        # Kept for API compatibility (style negatives, nsfw guard,
        # group-scene and previous-place guards): the callers still compute
        # it, but with cfg=1 the sampler output equals the positive
        # conditioning, so the text is intentionally not written anywhere.
        logger.debug(
            "negative_extra ignored by the Qwen-Image-2.1 workflow (cfg=1): %s",
            negative_extra.strip(),
        )
    return workflow


# The edit ("image -> image") graph takes its references through
# TextEncodeQwenImage21's autogrow `images` input: image_1 is the picture being
# edited, image_2..image_10 are references. The node sees up to 16, and the
# ComfyUI template ships 10 LoadImage slots; 10 is the number the backend wires.
EDIT_IMAGE_SLOTS = 10
# Node ids for the injected LoadImage nodes (one per image slot). High ids, so
# they never collide with the workflow file's own nodes.
EDIT_LOAD_NODE_BASE = 100


def build_edit_workflow(
    image_format: str,
    positive_prompt: str,
    filename_prefix: str,
    target: str | None = None,
    references: list[str] | None = None,
    seed: int | None = None,
    steps: int | None = None,
    custom_size: bool = False,
) -> dict[str, Any]:
    """The Qwen-Image-2.1 edit graph: one picture in, one picture out.

    `target` becomes image_1 (the picture that is edited) and `references`
    become image_2..image_N (up to EDIT_IMAGE_SLOTS - 1 of them). The prompt
    must address them the way the ComfyUI template does — "keep the face from
    <image1>, put him in the scene from <image2>" — because the encoder sees
    them as `<image1>`, `<image2>`, ... rather than as description text.

    With a target the canvas follows the target's own size (the switch feeds the
    encoded image_1 latent into the sampler); `custom_size` forces the
    workflow's own resolution instead. Without a target this is a plain
    text-to-image job that happens to carry references.
    """
    references = references or []
    if image_format not in FORMATS:
        image_format = "wide"
    path = WORKFLOWS_DIR / f"{image_format}_edit.json"
    if not path.exists():
        raise ImageGenerationError(f"Edit workflow file not found: {path}")
    workflow = json.loads(path.read_text(encoding="utf-8"))
    for node_id, class_type in REQUIRED_NODES.items():
        node = workflow.get(node_id)
        if node is None or node.get("class_type") != class_type:
            raise ImageGenerationError(
                f"Workflow {path.name} is missing required node {node_id} ({class_type})"
            )

    slots = ([target] if target else []) + references
    if len(slots) > EDIT_IMAGE_SLOTS:
        logger.info(
            "edit job takes %d image(s); only the first %d are used", len(slots), EDIT_IMAGE_SLOTS
        )
        slots = slots[:EDIT_IMAGE_SLOTS]
    if not slots:
        raise ImageGenerationError("An edit workflow needs at least one image")

    links: list[list[Any]] = []
    for index, filename in enumerate(slots):
        node_id = str(EDIT_LOAD_NODE_BASE + index)
        workflow[node_id] = {"class_type": "LoadImage", "inputs": {"image": filename}}
        links.append([node_id, 0])
    workflow["6"]["inputs"]["images"] = links
    workflow["6"]["inputs"]["prompt"] = positive_prompt
    # switch=true picks the empty latent of the workflow's own size; false keeps
    # the encoded target latent, so the picture starts from the target itself.
    workflow["9"]["inputs"]["switch"] = bool(custom_size or not target)
    workflow["8"]["inputs"]["seed"] = seed if seed is not None else random.randint(0, 2**31 - 1)
    if steps is not None:
        workflow["8"]["inputs"]["steps"] = steps
    workflow["10"]["inputs"]["filename_prefix"] = filename_prefix
    return workflow


def negative_extra_for(style_negative: str, explicit: bool) -> str:
    """Negative-prompt additions for a story: the style's negative tags, plus
    an `nsfw` guard for every story that is not explicit 18+. Only 18+ stories
    with explicit sexual content enabled skip it.

    NOTE: the Qwen-Image-2.1 workflow runs the sampler at cfg=1, so there is
    no negative-prompt node anymore — `build_workflow` accepts this text for
    API compatibility but intentionally does not write it anywhere."""
    parts = [style_negative.strip()] if style_negative.strip() else []
    if not explicit:
        parts.append("nsfw")
    return ", ".join(parts)


def _client(settings: Settings) -> httpx.Client:
    return httpx.Client(base_url=settings.comfyui_url, timeout=30.0)


def submit_job(client: httpx.Client, workflow: dict[str, Any]) -> str:
    try:
        response = client.post("/prompt", json={"prompt": workflow, "client_id": str(uuid.uuid4())})
    except httpx.HTTPError as exc:
        raise ImageGenerationError("Image generator is not running") from exc
    if response.status_code != 200:
        raise ImageGenerationError(f"ComfyUI rejected the job ({response.status_code}): {response.text[:300]}")
    prompt_id = response.json().get("prompt_id")
    if not prompt_id:
        raise ImageGenerationError("ComfyUI did not return a prompt_id")
    return str(prompt_id)


def cancel_job(client: httpx.Client, prompt_id: str) -> None:
    """Best-effort cancel of a job we gave up on, so ComfyUI does not keep
    burning GPU on it and block every later job behind the stale backlog.
    Never raises — cancellation is a cleanup, not part of the job result."""
    try:
        client.post("/queue", json={"delete": [prompt_id]})
        running = client.get("/queue").json().get("queue_running", [])
        if any(len(entry) > 1 and str(entry[1]) == prompt_id for entry in running):
            client.post("/interrupt")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("could not cancel ComfyUI job %s: %s", prompt_id, exc)


def render_job(
    client: httpx.Client,
    workflow: dict[str, Any],
    settings: Settings,
    persist_prompt_id: Any,
) -> bytes:
    """Run one job end to end and return the image bytes.

    An edit job needs more VRAM than a text-to-image one (the reference is
    encoded and lives in the sampler's context), and on a shared 8 GB card it
    can die with "VRAM grow failed" while the models of the previous job are
    still cached. When that happens the cache is freed and the job is submitted
    ONCE more, instead of leaving the player a dead picture and a guess.
    """
    for attempt in range(2):
        if attempt == 0:
            # An edit job needs the model in VRAM plus the encoded reference; on a
            # shared card the models of whatever ran last (often the player's own
            # manual ComfyUI job) are still cached and the sampler then dies with
            # "VRAM grow failed". Freeing the cache first is cheap and best-effort.
            _comfyui_free(settings)
        prompt_id = submit_job(client, workflow)
        persist_prompt_id(prompt_id)
        try:
            return download_image(client, wait_for_result(client, prompt_id, settings.image_timeout_seconds))
        except ImageGenerationError as exc:
            if "VRAM" not in str(exc) or attempt == 1:
                raise
            logger.warning("image job %s ran out of VRAM; freeing the cache and retrying once", prompt_id)
            _comfyui_free(settings)
    raise ImageGenerationError("Image generation failed")  # pragma: no cover - loop returns


def _history_failure(entry: dict[str, Any]) -> str:
    """Why a finished ComfyUI job produced no picture, in plain words.

    ComfyUI keeps the cause in `status.messages` as an `execution_error` entry
    (node type + the exception text). "VRAM grow failed" on an 8 GB card is the
    common one, and it is worth naming: the player can free the GPU, lower
    IMAGE_STEPS, or retry — none of which is guessable from "no image".
    """
    status = entry.get("status") or {}
    for message in status.get("messages") or []:
        value = message.get("value") if isinstance(message, dict) else None
        if not (isinstance(value, list) and value and value[0] in ("execution_error", "execution_interrupted")):
            continue
        error = value[1] if len(value) > 1 and isinstance(value[1], dict) else {}
        if value[0] == "execution_interrupted":
            return (
                "ComfyUI interrupted the job (another job was running, or the queue was "
                "cleared). Wait for the other picture to finish and press Retry."
            )
        node = error.get("node_type") or f"node {error.get('node_id', '?')}"
        reason = str(error.get("exception_message") or "").strip() or "unknown error"
        first_line = reason.splitlines()[0]
        if "vram" in first_line.lower() or "out of memory" in first_line.lower():
            return (
                f"The image model ran out of VRAM at {node} ({first_line}). Close other "
                "GPU-heavy programs, lower IMAGE_STEPS, or press Retry."
            )
        return f"ComfyUI failed at {node}: {first_line}"
    return "ComfyUI finished but produced no image"


def wait_for_result(client: httpx.Client, prompt_id: str, timeout_seconds: int) -> dict[str, str]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = client.get(f"/history/{prompt_id}")
        except httpx.HTTPError as exc:
            raise ImageGenerationError("Image generator is not running") from exc
        if response.status_code == 200:
            history = response.json()
            if prompt_id in history:
                entry = history[prompt_id]
                outputs = entry.get("outputs", {})
                images = outputs.get("10", {}).get("images", [])
                if images:
                    return images[0]
                # ComfyUI records a failed run (out of VRAM, a bad node input, a
                # missing model) in the history entry. Saying "no image" and
                # hiding the reason is what made a dead portrait unexplainable,
                # so the real message is passed on to the player.
                raise ImageGenerationError(_history_failure(entry))
        time.sleep(1.5)
    cancel_job(client, prompt_id)
    raise ImageGenerationError(f"Image generation timed out after {timeout_seconds}s")


def download_image(client: httpx.Client, image_info: dict[str, str]) -> bytes:
    try:
        response = client.get("/view", params={
            "filename": image_info["filename"],
            "subfolder": image_info.get("subfolder", ""),
            "type": image_info.get("type", "output"),
        })
    except httpx.HTTPError as exc:
        raise ImageGenerationError("Image generator is not running") from exc
    if response.status_code != 200:
        raise ImageGenerationError(f"Could not download image ({response.status_code})")
    return response.content


# ---------------------------------------------------------------------------
# Optional reference images (character portraits fed back into the workflow)
# ---------------------------------------------------------------------------

def reference_node_ids(settings: Settings) -> list[str]:
    return [node.strip() for node in settings.image_reference_nodes.split(",") if node.strip()]


def upload_reference_image(client: httpx.Client, data: bytes, filename: str) -> str:
    """Upload a reference image to ComfyUI, returns the stored file name."""
    try:
        response = client.post(
            "/upload/image",
            files={"image": (filename, data, "image/png")},
            data={"overwrite": "true"},
        )
    except httpx.HTTPError as exc:
        raise ImageGenerationError("Image generator is not running") from exc
    if response.status_code != 200:
        raise ImageGenerationError(f"ComfyUI refused the reference image ({response.status_code})")
    name = response.json().get("name")
    if not name:
        raise ImageGenerationError("ComfyUI did not return a name for the uploaded reference")
    return str(name)


# Node ids used by the auto-injected img2img reference chain:
# LoadImage -> ImageScale (to the scene resolution) -> VAEEncode -> the first
# sampler's latent input. High ids so they never collide with workflow nodes.
REFERENCE_LOAD_NODE = "90"
REFERENCE_SCALE_NODE = "91"
REFERENCE_VAE_NODE = "92"


def _inject_img2img_chain(workflow: dict[str, Any], reference_name: str, settings: Settings) -> None:
    """Wire a reference portrait into the first sampler as an img2img latent.

    The workflow file itself stays txt2img (latent from EmptyLatentImage), so
    generations without a usable reference are completely unaffected; only when
    a reference is actually applied do we inject the chain and rewire. The
    reference is center-cropped/scaled to the EmptyLatentImage resolution so
    the latent size matches what the workflow was built for.
    """
    latent = workflow.get("7", {}).get("inputs", {})
    width = int(latent.get("width", 1568))
    height = int(latent.get("height", 880))
    workflow[REFERENCE_LOAD_NODE] = {"class_type": "LoadImage", "inputs": {"image": reference_name}}
    workflow[REFERENCE_SCALE_NODE] = {
        "class_type": "ImageScale",
        "inputs": {
            "upscale_method": "bicubic",
            "width": width,
            "height": height,
            "crop": "center",
            "image": [REFERENCE_LOAD_NODE, 0],
        },
    }
    workflow[REFERENCE_VAE_NODE] = {
        "class_type": "VAEEncode",
        "inputs": {"pixels": [REFERENCE_SCALE_NODE, 0], "vae": ["3", 0]},
    }
    workflow["8"]["inputs"]["latent_image"] = [REFERENCE_VAE_NODE, 0]
    workflow["8"]["inputs"]["denoise"] = settings.image_reference_denoise


def apply_reference_images(
    workflow: dict[str, Any],
    uploaded_names: list[str],
    settings: Settings,
    as_latent: bool = True,
) -> int:
    """Point the configured LoadImage nodes at the uploaded references.

    One node per reference slot; extra references are dropped, missing or
    non-LoadImage nodes are skipped with a warning (generation continues
    without a reference rather than failing the job). In "img2img" mode the
    first reference additionally feeds the first sampler through the injected
    LoadImage/ImageScale/VAEEncode chain and the sampler's denoise is lowered,
    so the reference drives the look — no hand-edited workflow nodes needed.

    `as_latent=False` keeps that chain out (the sampler stays txt2img) while the
    configured nodes still receive the picture. Portrait jobs want
    `as_latent=True` (the reference has the portrait's own frame shape); a scene
    wants it only when the story opted in via `IMAGE_SCENE_REFERENCE`, because
    the portrait's frame is not the scene's frame.
    """
    applied = 0
    for node_id, name in zip(reference_node_ids(settings), uploaded_names):
        node = workflow.get(node_id)
        if node is None or node.get("class_type") != "LoadImage":
            logger.warning("reference node %s is missing or not a LoadImage node; skipping", node_id)
            continue
        node.setdefault("inputs", {})["image"] = name
        applied += 1
    if uploaded_names and settings.image_reference_mode == "img2img" and as_latent:
        _inject_img2img_chain(workflow, uploaded_names[0], settings)
        applied = max(applied, 1)
    if len(uploaded_names) > applied:
        logger.info("dropped %d reference image(s): not enough reference slots", len(uploaded_names) - applied)
    return applied


def _reference_images_for_turn(db: Any, turn: Turn, settings: Settings) -> list[tuple[str, bytes]]:
    """Portraits of the characters in this scene, hero first, as (name, bytes)."""
    if settings.image_reference_mode == "off":
        return []
    node_count = len(reference_node_ids(settings))
    # img2img scene references are opt-in: the auto-injected chain would start
    # the scene sampler from a portrait, which forces the portrait's crop, pose
    # and single-character frame onto the scene (see `image_scene_reference`).
    if settings.image_reference_mode == "img2img" and settings.image_scene_reference:
        node_count = max(node_count, 1)
    if node_count == 0:
        return []
    characters = db.query(Character).filter(
        Character.story_id == turn.story_id,
        Character.portrait_status == "done",
        Character.portrait_path.isnot(None),
    ).all()
    if not characters:
        return []
    ordered: list[Character] = []
    hero = next((c for c in characters if c.is_hero), None)
    names = turn.characters_in_scene or []
    # Narrators (especially small free models) often list the hero by name
    # instead of the "__hero__" sentinel. The hero must still lead: in img2img
    # mode the FIRST reference drives the whole scene's latent, so an NPC
    # landing in slot one would paint the scene off the wrong face.
    hero_named = hero is not None and any(
        str(name).strip().casefold() == hero.name.strip().casefold() for name in names
    )
    if hero and (not names or "__hero__" in names or hero_named):
        ordered.append(hero)
    for name in names:
        if str(name).strip() == "__hero__":
            continue
        character = find_character(characters, str(name))
        if character and character not in ordered:
            ordered.append(character)
    if not names and hero is None:
        ordered = characters  # no scene info: fall back to any known portraits
    references: list[tuple[str, bytes]] = []
    for character in ordered[:node_count]:
        path = Path(settings.image_dir) / str(character.portrait_path)
        try:
            references.append((f"ref_{character.id}.png", path.read_bytes()))
        except OSError:
            logger.warning("portrait file missing for character %s: %s", character.id, path)
    return references


def _mock_png(path: Path) -> None:
    """Tiny valid 1x1 PNG placeholder written without extra dependencies."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x40\x30\x50")
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    )


def save_image(data: bytes, settings: Settings, story_id: int, turn_id: int) -> str:
    directory = Path(settings.image_dir) / str(story_id)
    directory.mkdir(parents=True, exist_ok=True)
    relative = f"{story_id}/{turn_id}.png"
    (Path(settings.image_dir) / relative).write_bytes(data)
    return relative


def _portrait_filename(character_id: int, version: int) -> str:
    """Version 1 keeps the legacy char_{id}.png name; later versions get
    char_{id}_v{n}.png so a portrait_update never overwrites the previous look."""
    return f"char_{character_id}.png" if version <= 1 else f"char_{character_id}_v{version}.png"


# Uploads (the hero photo from the setup form, a character's picture from the
# Characters tab) travel as data URLs in the JSON body: the app is local, one
# request is simpler than multipart plumbing, and the size cap keeps a stray
# huge photo from filling memory.
UPLOAD_MIME_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def decode_upload(data_url: str) -> bytes:
    """Bytes of a `data:image/...;base64,…` URL, or a clear error."""
    header, separator, payload = data_url.partition(",")
    if not separator or ";base64" not in header:
        raise ImageGenerationError("The picture must be sent as a base64 data URL")
    mime = header.split(":", 1)[-1].split(";", 1)[0].strip().lower()
    if mime not in UPLOAD_MIME_TYPES:
        raise ImageGenerationError(
            f"Unsupported picture format {mime!r}; use PNG, JPEG or WebP"
        )
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageGenerationError("The uploaded picture is not valid base64 data") from exc


def save_upload(
    data: bytes, settings: Settings, story_id: int, name: str
) -> str:
    """Write an uploaded picture under IMAGE_DIR/{story_id}/ and return its path."""
    directory = Path(settings.image_dir) / str(story_id)
    directory.mkdir(parents=True, exist_ok=True)
    relative = f"{story_id}/{name}"
    (Path(settings.image_dir) / relative).write_bytes(data)
    return relative


def read_image_file(settings: Settings, relative_path: str | None) -> bytes | None:
    """Bytes of a stored image, or None when it is missing/unreadable."""
    if not relative_path:
        return None
    try:
        return (Path(settings.image_dir) / relative_path).read_bytes()
    except OSError:
        logger.warning("stored image missing: %s", relative_path)
        return None


def save_portrait(
    data: bytes, settings: Settings, story_id: int, character_id: int, version: int = 1
) -> str:
    """Save a portrait version; old versions' files survive (the history
    gallery and revert rely on them)."""
    directory = Path(settings.image_dir) / str(story_id)
    directory.mkdir(parents=True, exist_ok=True)
    relative = f"{story_id}/{_portrait_filename(character_id, version)}"
    (Path(settings.image_dir) / relative).write_bytes(data)
    return relative


# ---------------------------------------------------------------------------
# Queue with a single worker thread (one ComfyUI job at a time).
# Jobs are (job_type, ref_id): ("scene", turn_id), ("portrait", character_id),
# or the same ids as ("resume_scene", ...) / ("resume_portrait", ...) when the
# job was interrupted by a restart and has to be picked back up.
# ---------------------------------------------------------------------------

_JOB_STOP = ("stop", -1)
_job_queue: queue.Queue[tuple[str, int]] = queue.Queue()
_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_worker_running = False


def enqueue_turn_image(turn_id: int) -> None:
    _job_queue.put(("scene", turn_id))


def enqueue_portrait(character_id: int) -> None:
    _job_queue.put(("portrait", character_id))


def enqueue_resume_turn_image(turn_id: int) -> None:
    _job_queue.put(("resume_scene", turn_id))


def enqueue_resume_portrait(character_id: int) -> None:
    _job_queue.put(("resume_portrait", character_id))


def start_worker() -> None:
    global _worker_thread, _worker_running
    with _worker_lock:
        if _worker_running:
            return
        _worker_running = True
        _worker_thread = threading.Thread(target=_worker_loop, name="image-worker", daemon=True)
        _worker_thread.start()


def stop_worker() -> None:
    global _worker_running
    with _worker_lock:
        _worker_running = False
    _job_queue.put(_JOB_STOP)  # wake the worker so it can exit


def _worker_loop() -> None:
    while _worker_running:
        job = _job_queue.get()
        if job == _JOB_STOP:
            break
        job_type, ref_id = job
        try:
            if job_type == "portrait":
                process_character_portrait(ref_id)
            elif job_type == "resume_scene":
                resume_turn_image(ref_id)
            elif job_type == "resume_portrait":
                resume_character_portrait(ref_id)
            else:
                process_turn_image(ref_id)
        except Exception:
            logger.exception("image job failed: %s %s", job_type, ref_id)
        finally:
            _job_queue.task_done()


def _get_with_retry(db: Any, model: type, row_id: int) -> Any:
    """Jobs are enqueued just before the turn transaction commits, so the row
    may not be visible to the worker's session yet — wait briefly for it."""
    for attempt in range(10):
        row = db.get(model, row_id)
        if row is not None:
            return row
        if attempt < 9:
            time.sleep(0.3)
    return None


def _current_look(character: Character) -> tuple[str, str, str]:
    """(appearance_tags, pose, expression) of the character's current version."""
    if character.portrait_history:
        current = character.portrait_history[-1]
        return (
            current.get("appearance_tags") or character.appearance_tags or "",
            current.get("pose") or "",
            current.get("expression") or "",
        )
    return character.appearance_tags or "", "", ""


def _story_image_params(db: Any, story_id: int) -> tuple[str, str, bool, str]:
    """(style positive tags, style negative tags, explicit, world anchor tags)."""
    story = db.get(Story, story_id)
    params = story.settings if story and story.settings else {}
    style = image_style_tags(params.get("image_style"))
    return (
        style["positive"],
        style["negative"],
        images_are_explicit(params),
        setting_anchor(params.get("setting"), params.get("custom_setting")),
    )


# ---------------------------------------------------------------------------
# Prompt and reference picking for the edit ("image -> image") graph.
# The Qwen encoder sees the pictures as `<image1>`, `<image2>`, ... and READS
# them, so the text has to be an instruction about those pictures, not a
# danbooru tag list describing somebody who is not in the frame.
# ---------------------------------------------------------------------------


def assemble_edit_prompt(
    scene_prompt: str,
    hero_name: str | None,
    others: list[tuple[int, str]],
) -> str:
    """Instruction text for a scene built around the uploaded pictures.

    `hero_name` is the person in image_1 (the player's own photo of the hero);
    `others` pairs each further reference picture with the character's name, in
    image order (image_2, image_3, …). Without any reference the tags are used
    as they are, so a story with no photos behaves exactly as before.
    """
    tags = ", ".join(tag.strip() for tag in scene_prompt.split(",") if tag.strip())
    if hero_name is None and not others:
        return tags
    parts = [f"A scene: {tags}."]
    if hero_name:
        parts.append(
            f"<image1> is {hero_name}, the main character — keep their face, hair and "
            "build exactly as in the picture, in the same art style."
        )
    for index, name in others:
        parts.append(
            f"<image{index}> is {name} — keep their face and outfit, and place them in "
            "the same scene and art style."
        )
    return " ".join(parts)


def scene_edit_references(db: Any, turn: Turn, settings: Settings) -> list[tuple[str, bytes, str]]:
    """(filename, bytes, character name) of the pictures a scene carries.

    The hero is NOT here: the hero's own photo is image_1 (the picture the
    scene is built from), so these are the OTHER people of the scene, in the
    order they are given to the model — image_2, image_3, … Each character's
    player upload wins over the portrait the generator painted for them, and
    the list stops at EDIT_IMAGE_SLOTS - 1 entries.
    """
    characters = db.query(Character).filter(Character.story_id == turn.story_id).all()
    ordered: list[Character] = []
    for name in turn.characters_in_scene or []:
        if str(name).strip() == "__hero__":
            continue
        found = find_character(characters, str(name))
        if found and not found.is_hero and found not in ordered:
            ordered.append(found)

    references: list[tuple[str, bytes, str]] = []
    for character in ordered:
        if len(references) >= EDIT_IMAGE_SLOTS - 1:
            break
        data = read_image_file(settings, character.photo_path) or read_image_file(
            settings, character.portrait_path if character.portrait_status == "done" else None
        )
        if data:
            references.append((f"ref_{character.id}.png", data, character.name))
    return references


def format_build_log(
    mode: str,
    prompt: str,
    steps: int,
    seed: int,
    references: list[str] | None = None,
    extra: list[str] | None = None,
) -> str:
    """The record the "Image log" button shows: what the picture model was told.

    Deliberately plain text — the player is debugging a picture, and the
    answer is the exact prompt plus how it was generated, not a JSON blob.
    """
    lines = [
        f"mode: {mode}",
        f"steps: {steps}",
        f"seed: {seed}",
        f"references: {', '.join(references) if references else 'none'}",
    ]
    lines.extend(extra or [])
    lines.append("prompt:")
    lines.append(prompt)
    return "\n".join(lines)


def assemble_portrait_edit_prompt(portrait_prompt: str, from_player_photo: bool) -> str:
    """Instruction text for a portrait that is an edit of an existing picture.

    The tags in `portrait_prompt` describe the look the narrator wants, but for
    an EDIT job they must never be allowed to win over the face: the model reads
    a tag list as a full description and repaints the person from scratch. So the
    instruction leads with what to keep, states that the tags only describe the
    clothing and the pose, and explicitly forbids changing the face. When image_1
    is the player's own photo, that face is the whole point and the wording says
    so twice.
    """
    if from_player_photo:
        keep = (
            "<image1> is this character's own photograph. It is the same person: keep their "
            "face, their facial features, their hair and their skin tone EXACTLY as they are. "
            "Do not invent a different person — the photograph is the identity, and only "
            "the clothes and the pose may change."
        )
    else:
        keep = (
            "<image1> is this character from an earlier picture. It is the same person: keep "
            "their face, their facial features and their skin tone exactly as they are. Only "
            "the clothes and the pose may change."
        )
    return (
        f"{keep} Repaint the same person in the following outfit and pose: {portrait_prompt}. "
        "The tag list describes ONLY the clothes, the pose and the framing — never the face. "
        "Keep the same art style, keep them an adult, and keep the picture a full-body "
        "reference portrait of the person from the photograph."
    )


def portrait_edit_source(
    db: Any, character: Character, settings: Settings
) -> tuple[bytes, str] | None:
    """The picture a portrait is edited from, and what that picture is.

    In order: the character's own upload (Characters tab), the HERO PHOTO uploaded
    at story setup, then the previous portrait. The setup photo used to be
    invisible here — the hero's picture was built from tags while every scene was
    built from the photo, so the player got their own face in the story and a
    stranger on the character's card.
    """
    own = read_image_file(settings, character.photo_path)
    if own:
        return own, "the player's photo for this character"
    if character.is_hero:
        story = db.get(Story, character.story_id) if db is not None else None
        setup_photo = (
            read_image_file(settings, (story.settings or {}).get("hero_image"))
            if story
            else None
        )
        if setup_photo:
            return setup_photo, "the hero photo uploaded at setup"
    previous = _previous_portrait_reference(character, settings)
    return (previous[1], "the previous look") if previous else None


def portrait_edit_reference(character: Character, settings: Settings) -> bytes | None:
    """The picture a portrait is edited from: the player's own upload first,
    then the previous portrait (what the img2img chain used to drive from)."""
    own = read_image_file(settings, character.photo_path)
    if own:
        return own
    previous = _previous_portrait_reference(character, settings)
    return previous[1] if previous else None


def ensure_build_logs(db: Any, turns: list[Turn], settings: Settings) -> None:
    """Fill in a build log for every picture, including old ones.

    The log is written when a picture is drawn, so pictures made before the
    feature existed have none — and a button that is empty for most of a story
    looks broken. Because the seed is fixed (IMAGE_SEED) the prompt can be
    assembled again from the stored scene prompt and the stored appearance tags,
    which reproduces exactly what the current code would send. Such a log says
    so, instead of pretending to be the historical record.
    """
    for turn in turns:
        if turn.image_build_log or not (turn.image_prompt or "").strip():
            continue
        if not settings.image_generation_enabled:
            continue
        try:
            hero_tags, character_tags = _scene_appearance_tags(db, turn)
            style_pos, style_neg, explicit, world_tags = _story_image_params(db, turn.story_id)
            visible = len(turn.characters_in_scene or [])
            anchored = (1 if hero_tags.strip() else 0) + len(
                [tags for tags in character_tags if tags.strip()]
            )
            prompt = assemble_positive_prompt(
                turn.image_prompt, hero_tags, character_tags,
                style_tags=style_pos, explicit=explicit,
                scene_characters=max(visible, anchored), world_tags=world_tags,
            )
            turn.image_build_log = format_build_log(
                "text to image (rebuilt from the stored scene prompt with today's "
                "settings — this picture was drawn before logging existed)",
                prompt,
                settings.image_steps,
                settings.image_seed,
            )
        except Exception as exc:  # noqa: BLE001 - a log must never break a page
            logger.warning("could not rebuild the image log of turn %s: %s", turn.id, exc)


def ensure_portrait_build_logs(characters: list[Character], settings: Settings) -> None:
    """Same idea for portraits: a card always has something to show in its log."""
    for character in characters:
        if character.portrait_build_log or not (character.appearance_tags or "").strip():
            continue
        if not settings.image_generation_enabled:
            continue
        try:
            character.portrait_build_log = format_build_log(
                "portrait (rebuilt from the stored look with today's settings — this "
                "picture was drawn before logging existed)",
                assemble_portrait_prompt(character.appearance_tags or ""),
                settings.image_steps,
                settings.image_seed,
            )
        except Exception as exc:  # noqa: BLE001 - a log must never break a page
            logger.warning("could not rebuild the portrait log of %s: %s", character.id, exc)


def process_turn_image(turn_id: int, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    db = SessionLocal()
    try:
        turn = _get_with_retry(db, Turn, turn_id)
        if turn is None or not turn.image_prompt:
            return
        turn.image_status = "generating"
        turn.image_error = None
        db.commit()
        conductor = settings.gpu_vram_conductor and not settings.mock_images
        if conductor:
            _ollama_unload(settings)
        try:
            if settings.mock_images:
                time.sleep(3)
                directory = Path(settings.image_dir) / str(turn.story_id)
                directory.mkdir(parents=True, exist_ok=True)
                relative = f"{turn.story_id}/{turn.id}.png"
                _mock_png(Path(settings.image_dir) / relative)
            else:
                hero_tags, character_tags = _scene_appearance_tags(db, turn)
                style_pos, style_neg, explicit, world_tags = _story_image_params(db, turn.story_id)
                negative_extra = negative_extra_for(style_neg, explicit)
                # How many people share the frame: the narrator's list, and the
                # appearance anchors that are actually spliced in (the hero is
                # spliced even when the list forgets them). Two or more means a
                # two-shot facing each other instead of a solo close-up.
                visible = len(turn.characters_in_scene or [])
                anchored = (1 if hero_tags.strip() else 0) + len(
                    [tags for tags in character_tags if tags.strip()]
                )
                scene_characters = max(visible, anchored)
                group_negative = group_scene_negative(scene_characters)
                if group_negative:
                    negative_extra = (
                        f"{negative_extra}, {group_negative}" if negative_extra else group_negative
                    )
                # When the story has moved on, the previous location must not
                # survive into the picture (see previous_scene_negative).
                carryover = previous_scene_negative(db, turn, turn.image_prompt)
                if carryover:
                    logger.info(
                        "turn %s: negating the previous scene's place tags: %s",
                        turn.id, carryover,
                    )
                    negative_extra = f"{negative_extra}, {carryover}" if negative_extra else carryover
                # The player's own photo of the hero (uploaded at setup) turns the
                # scene into an EDIT job: image_1 is that photo, the other people
                # of the scene follow as image_2..N, and the prompt addresses the
                # pictures by number. Without a photo this is the old tag-only
                # job, so stories that never uploaded one are untouched.
                story_row = db.get(Story, turn.story_id)
                hero_photo = (
                    read_image_file(settings, (story_row.settings or {}).get("hero_image"))
                    if story_row
                    else None
                )
                with _client(settings) as client:
                    build_mode = "text to image"
                    reference_names: list[str] = []
                    if hero_photo:
                        hero_name = None
                        if story_row:
                            hero_row = next(
                                (c for c in story_row.characters if c.is_hero), None
                            )
                            hero_name = hero_row.name if hero_row else None
                        references = scene_edit_references(db, turn, settings)
                        uploaded = [
                            upload_reference_image(client, data, filename)
                            for filename, data, _name in references
                        ]
                        workflow = build_edit_workflow(
                            turn.image_format or "wide",
                            assemble_edit_prompt(
                                assemble_positive_prompt(
                                    turn.image_prompt, hero_tags, character_tags,
                                    style_tags=style_pos, explicit=explicit,
                                    scene_characters=scene_characters, world_tags=world_tags,
                                ),
                                hero_name,
                                [
                                    (index, name)
                                    for index, (_f, _d, name) in enumerate(references, start=2)
                                ],
                            ),
                            filename_prefix=f"roleplaygen/story_{turn.story_id}/scene_{turn.id}",
                            target=upload_reference_image(client, hero_photo, "hero_photo.png"),
                            references=uploaded,
                            steps=settings.image_steps,
                            # One seed for every picture (IMAGE_SEED): the same
                            # prompt then reproduces the same picture.
                            seed=settings.image_seed,
                            # A photo is portrait-shaped; the canvas stays the
                            # workflow's own 16:9, so the result is a scene and
                            # not a crop of the upload.
                            custom_size=True,
                        )
                        logger.info(
                            "turn %s: edit scene from the hero photo + %d character picture(s)",
                            turn.id, len(uploaded),
                        )
                        build_mode = "edit (image_1 = the hero's photo, canvas 16:9)"
                        reference_names = ["hero_photo.png", *uploaded]
                    else:
                        workflow = build_workflow(
                            turn.image_format or "wide",
                            assemble_positive_prompt(
                                turn.image_prompt, hero_tags, character_tags,
                                style_tags=style_pos, explicit=explicit,
                                scene_characters=scene_characters, world_tags=world_tags,
                            ),
                            # ComfyUI writes into output/roleplaygen/story_<id>/, so the
                            # raw output folder stays readable instead of collecting
                            # every story's scenes and portraits in one flat list.
                            filename_prefix=f"roleplaygen/story_{turn.story_id}/scene_{turn.id}",
                            negative_extra=negative_extra,
                            steps=settings.image_steps,
                            seed=settings.image_seed,
                        )
                        references = _reference_images_for_turn(db, turn, settings)
                        if references:
                            uploaded = [
                                upload_reference_image(client, data, filename)
                                for filename, data in references
                            ]
                            applied = apply_reference_images(
                                workflow, uploaded, settings,
                                # A scene canvas is 16:9 and a portrait is 4:5: using
                                # the portrait as the sampler's starting latent
                                # forces its crop, its pose and its single person
                                # onto the scene. Only an explicit opt-in does that.
                                as_latent=settings.image_scene_reference,
                            )
                            logger.info(
                                "turn %s: %d reference image(s) applied, scene driven by %s",
                                turn.id, applied, uploaded[0],
                            )
                        else:
                            logger.info(
                                "turn %s: no portrait reference applied (mode=%s)",
                                turn.id, settings.image_reference_mode,
                            )
                    # What the picture model was told, kept for the "Image log"
                    # button: a wrong-looking picture has to be traceable to the
                    # exact prompt that produced it.
                    turn.image_build_log = format_build_log(
                        build_mode,
                        str(workflow["6"]["inputs"].get("prompt", "")),
                        int(workflow["8"]["inputs"].get("steps", 0)),
                        int(workflow["8"]["inputs"].get("seed", 0)),
                        reference_names,
                    )

                    def remember(prompt_id: str, turn: Any = turn, db: Any = db) -> None:
                        # Persisted BEFORE waiting: if the app dies while ComfyUI is
                        # still drawing, the next start adopts this job instead of
                        # discarding the picture and offering a Retry (see
                        # reset_interrupted_turns).
                        turn.image_prompt_id = prompt_id
                        db.commit()

                    data = render_job(client, workflow, settings, remember)
                relative = save_image(data, settings, turn.story_id, turn.id)
            turn.image_status = "done"
            turn.image_path = relative
            turn.image_prompt_id = None
        except ImageGenerationError as exc:
            turn.image_status = "failed"
            turn.image_error = str(exc)
            turn.image_prompt_id = None
        finally:
            if conductor:
                _comfyui_free(settings)
        db.commit()
    finally:
        db.close()


def _scene_appearance_tags(db: Any, turn: Turn) -> tuple[str, list[str]]:
    """Hero tags plus the tags of every named character in the scene.

    With no `characters_in_scene` this falls back to hero-only, exactly the
    behavior before character tracking existed.
    """
    characters = db.query(Character).filter(Character.story_id == turn.story_id).all()
    hero = next((c for c in characters if c.is_hero), None)
    # The age rides along with the look: a mother in the scene must look her age,
    # not like a teenager. A creature without a human age adds nothing.
    hero_tags = _look_with_age(hero) if hero else ""
    names = turn.characters_in_scene or []
    if not names:
        return hero_tags, []
    npcs = [c for c in characters if not c.is_hero]
    tags: list[str] = []
    seen_ids: set[int] = set()
    for name in names:
        if str(name) == "__hero__":
            continue  # hero tags are already first
        # The shared fuzzy matcher resolves loose narrator variants
        # ("Странник в чёрном" for "Тайный странник") to the stored character.
        character = find_character(npcs, str(name))
        if character and character.appearance_tags and character.id not in seen_ids:
            seen_ids.add(character.id)
            tags.append(_look_with_age(character))
    return hero_tags, tags


def _look_with_age(character: Character) -> str:
    """A character's stored look plus their age, in one tag string."""
    look = (character.appearance_tags or "").strip()
    age = (character.age or "").strip()
    if not age:
        return look
    return f"{look}, {age}" if look else age


def _prompt_words(text: str) -> set[str]:
    """All lowercase words of a prompt/tag list."""
    return set(re.findall(r"[a-z]+", text.lower()))


def _place_words(text: str) -> list[str]:
    """The words of a tag list that name a place, in the order they appear."""
    return [word for word in re.findall(r"[a-z]+", text.lower()) if word in PLACE_WORDS]


def _scene_word_roots(scene_name: str) -> set[str]:
    """Significant words of a narrator scene name (lowercase, 3+ letters)."""
    return {word for word in re.findall(r"[^\W\d_]+", scene_name.lower()) if len(word) >= 3}


def _same_root(left: str, right: str) -> bool:
    """True when two scene-name words share a root ("избушка" ~ "избушки",
    "лес" ~ "лесная"): inflected forms are compared on their first letters,
    which is why the guard stays conservative on purpose."""
    length = min(len(left), len(right), 4)
    return left[:length] == right[:length]


def _scene_moved(previous_scene: str, current_scene: str) -> bool:
    """True when the narrator's scene NAME points at a different place.

    Deliberately conservative: it reports a move only when none of the two
    names' words share a root. A renamed wording of the SAME place must never
    trigger the guard, because a false positive would fight the real setting.
    """
    previous, current = _scene_word_roots(previous_scene), _scene_word_roots(current_scene)
    if not previous or not current:
        return False
    return not any(_same_root(left, right) for left in previous for right in current)


def previous_scene_negative(db: Any, turn: Turn, current_prompt: str) -> str:
    """Place words of the previous scene that the story has just left behind.

    The scene reference is a character portrait: in img2img mode the first
    sampler starts from it, so a place survives into the next picture far more
    easily than any other tag — the story moves into a hut and the picture is
    still a forest. The narrator re-uses the previous location out of habit
    too. The place words of the previous turn that the new prompt does not use
    are therefore negated, so the NEW location wins — and only when the scene
    name actually changed, so the guard never fights a scene that stayed where
    it was.

    Only the plain place WORDS are negated, never whole tags: a compound tag
    like "mysterious shadowy figure in black cloak between trees" also carries
    the character, and negating it would repaint the stranger.
    """
    if not current_prompt.strip():
        return ""
    previous = (
        db.query(Turn)
        .filter(Turn.story_id == turn.story_id, Turn.index < turn.index)
        .order_by(Turn.index.desc())
        .first()
    )
    if previous is None or not previous.image_prompt:
        return ""
    previous_state = previous.state if isinstance(previous.state, dict) else {}
    current_state = turn.state if isinstance(turn.state, dict) else {}
    if not _scene_moved(
        str(previous_state.get("scene", "")), str(current_state.get("scene", ""))
    ):
        return ""
    current_words = _prompt_words(current_prompt)
    kept: list[str] = []
    seen: set[str] = set()
    for tag in sanitize_tags(previous.image_prompt):
        for word in _place_words(tag):
            if word in current_words or word in seen:
                continue
            seen.add(word)
            kept.append(word)
            if len(kept) >= MAX_PREVIOUS_SCENE_NEGATIVES:
                return ", ".join(kept)
    return ", ".join(kept)


def _previous_portrait_reference(character: Character, settings: Settings) -> tuple[str, bytes] | None:
    """The character's current portrait file, fed back into a portrait
    regeneration as the img2img reference.

    Without it an evolving look (portrait_update) is repainted from tags alone
    and the face drifts into a different person; with the previous portrait
    driving the first sampler at the reference denoise, the new outfit or
    detail lands on the SAME character. First-ever portraits have no file yet
    and stay pure txt2img.
    """
    if settings.image_reference_mode == "off" or not character.portrait_path:
        return None
    path = Path(settings.image_dir) / str(character.portrait_path)
    try:
        return f"ref_{character.id}.png", path.read_bytes()
    except OSError:
        logger.warning("previous portrait file missing for character %s: %s", character.id, path)
        return None


def process_character_portrait(character_id: int, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    db = SessionLocal()
    try:
        character = _get_with_retry(db, Character, character_id)
        if character is None or not character.appearance_tags:
            return
        character.portrait_status = "generating"
        character.portrait_error = None
        db.commit()
        conductor = settings.gpu_vram_conductor and not settings.mock_images
        if conductor:
            _ollama_unload(settings)
        try:
            if settings.mock_images:
                time.sleep(3)
                version = max(1, len(character.portrait_history or []))
                relative = f"{character.story_id}/{_portrait_filename(character.id, version)}"
                directory = Path(settings.image_dir) / str(character.story_id)
                directory.mkdir(parents=True, exist_ok=True)
                _mock_png(Path(settings.image_dir) / relative)
            else:
                style_pos, style_neg, story_explicit, world_tags = _story_image_params(
                    db, character.story_id
                )
                tags, pose, expression = _current_look(character)
                # Clothed by default at every rating; explicit only when the
                # story allows it AND the narrator deliberately tagged this
                # look as nude (e.g. a plot-driven portrait_update).
                explicit = story_explicit and portrait_wants_nudity(tags, pose, expression)
                prompt_text = assemble_portrait_prompt(
                    tags, pose=pose, expression=expression,
                    style_tags=style_pos, explicit=explicit, world_tags=world_tags,
                    age=character.age or "",
                )
                filename_prefix = f"roleplaygen/story_{character.story_id}/portrait_{character.id}"
                with _client(settings) as client:
                    source = portrait_edit_source(db, character, settings)
                    build_mode = "text to image"
                    if source is not None:
                        reference_bytes, source_label = source
                        # "Image from image": the new portrait is an EDIT of the
                        # picture the character already has — the player's own
                        # upload, the setup photo of the hero, or the previous
                        # portrait. The face therefore survives a new outfit
                        # instead of being invented again.
                        is_player_photo = source_label != "the previous look"
                        workflow = build_edit_workflow(
                            "portrait",
                            assemble_portrait_edit_prompt(prompt_text, is_player_photo),
                            filename_prefix,
                            target=upload_reference_image(
                                client, reference_bytes, f"portrait_base_{character.id}.png"
                            ),
                            steps=settings.image_steps,
                            # A portrait keeps the shape of the picture it is
                            # edited from, which is what a portrait card needs.
                            custom_size=False,
                            seed=settings.image_seed,
                        )
                        build_mode = f"edit (image_1 = {source_label})"
                        logger.info(
                            "character %s: portrait edited from %s",
                            character.id,
                            source_label,
                        )
                    else:
                        reference_bytes = None
                        workflow = build_workflow(
                            "portrait",
                            prompt_text,
                            filename_prefix,
                            negative_extra=negative_extra_for(style_neg, explicit=explicit),
                            steps=settings.image_steps,
                            seed=settings.image_seed,
                        )
                    # The same record as for scenes, shown in the character card.
                    character.portrait_build_log = format_build_log(
                        build_mode,
                        str(workflow["6"]["inputs"].get("prompt", "")),
                        int(workflow["8"]["inputs"].get("steps", 0)),
                        int(workflow["8"]["inputs"].get("seed", 0)),
                        [f"portrait_base_{character.id}.png"] if reference_bytes else [],
                    )

                    def remember(prompt_id: str, character: Any = character, db: Any = db) -> None:
                        # Persisted before waiting, exactly like a scene job: a
                        # restart mid-render must adopt this portrait, not repaint it.
                        character.portrait_prompt_id = prompt_id
                        db.commit()

                    data = render_job(client, workflow, settings, remember)
                relative = save_portrait(
                    data, settings, character.story_id, character.id,
                    version=max(1, len(character.portrait_history or [])),
                )
            character.portrait_status = "done"
            character.portrait_path = relative
            character.portrait_prompt_id = None
            if character.portrait_history:
                history = [dict(entry) for entry in character.portrait_history]
                history[-1]["portrait_path"] = relative
                character.portrait_history = history
        except ImageGenerationError as exc:
            character.portrait_status = "failed"
            character.portrait_error = str(exc)
            character.portrait_prompt_id = None
        finally:
            if conductor:
                _comfyui_free(settings)
        db.commit()
    finally:
        db.close()


def _history_image(client: httpx.Client, prompt_id: str) -> dict[str, str] | None:
    """The saved image of a FINISHED job, or None while it is not finished."""
    response = client.get(f"/history/{prompt_id}")
    if response.status_code != 200:
        return None
    entry = response.json().get(prompt_id)
    if not isinstance(entry, dict):
        return None
    images = entry.get("outputs", {}).get("10", {}).get("images", [])
    return images[0] if images else None


def _job_known(client: httpx.Client, prompt_id: str) -> bool:
    """True while ComfyUI still has the job running or waiting in its queue."""
    queue = client.get("/queue").json()
    entries = [*(queue.get("queue_running") or []), *(queue.get("queue_pending") or [])]
    return any(len(entry) > 1 and str(entry[1]) == prompt_id for entry in entries)


def job_recovery_state(client: httpx.Client, prompt_id: str) -> str:
    """What a job id from a previous run means now.

    "done"  — the picture exists on the ComfyUI side and can be adopted;
    "alive" — still running or queued, so the app keeps waiting for it;
    "lost"  — ComfyUI does not know it any more (its own restart, cancellation).
    """
    try:
        if _history_image(client, prompt_id) is not None:
            return "done"
    except (httpx.HTTPError, ValueError):
        return "alive"  # server unreachable or wedged: do not discard the job
    try:
        return "alive" if _job_known(client, prompt_id) else "lost"
    except (httpx.HTTPError, ValueError):
        return "alive"


def wait_for_resumed_result(
    client: httpx.Client, prompt_id: str, timeout_seconds: int
) -> dict[str, str]:
    """Adopt a job this app submitted before a restart.

    The ComfyUI job outlived the app, so the picture is not lost: poll its
    history and hand the result back (unlike `wait_for_result`, nothing is
    cancelled on timeout — the job is no longer ours to kill). A job ComfyUI no
    longer knows about fails right away instead of burning the whole timeout.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            image = _history_image(client, prompt_id)
            if image is not None:
                return image
            if not _job_known(client, prompt_id):
                raise ImageGenerationError("The interrupted image job is gone from the generator")
        except httpx.HTTPError as exc:
            raise ImageGenerationError("Image generator is not running") from exc
        time.sleep(2.0)
    raise ImageGenerationError(f"Image generation timed out after {timeout_seconds}s")


def _adopt_turn_image(db: Any, client: httpx.Client, turn: Turn, settings: Settings) -> None:
    """Save a scene the generator finished while the app was down."""
    image_info = wait_for_resumed_result(
        client, str(turn.image_prompt_id), settings.image_timeout_seconds
    )
    data = download_image(client, image_info)
    turn.image_path = save_image(data, settings, turn.story_id, turn.id)
    turn.image_status = "done"
    turn.image_error = None
    turn.image_prompt_id = None
    logger.info(
        "turn %s: adopted the interrupted scene image %s", turn.id, image_info.get("filename")
    )


def resume_turn_image(turn_id: int, settings: Settings | None = None) -> None:
    """Pick a scene back up after a restart (worker job "resume_scene")."""
    settings = settings or get_settings()
    db = SessionLocal()
    try:
        turn = _get_with_retry(db, Turn, turn_id)
        if turn is None or not turn.image_prompt_id:
            return
        turn.image_status = "generating"
        db.commit()
        try:
            with _client(settings) as client:
                _adopt_turn_image(db, client, turn, settings)
        except ImageGenerationError as exc:
            turn.image_status = "failed"
            turn.image_error = str(exc)
            turn.image_prompt_id = None
            logger.warning("turn %s: could not adopt the interrupted image: %s", turn.id, exc)
        db.commit()
    finally:
        db.close()


def resume_character_portrait(character_id: int, settings: Settings | None = None) -> None:
    """Pick a portrait back up after a restart (worker job "resume_portrait")."""
    settings = settings or get_settings()
    db = SessionLocal()
    try:
        character = _get_with_retry(db, Character, character_id)
        if character is None or not character.portrait_prompt_id:
            return
        character.portrait_status = "generating"
        db.commit()
        try:
            with _client(settings) as client:
                image_info = wait_for_resumed_result(
                    client, str(character.portrait_prompt_id), settings.image_timeout_seconds
                )
                data = download_image(client, image_info)
            relative = save_portrait(
                data, settings, character.story_id, character.id,
                version=max(1, len(character.portrait_history or [])),
            )
            character.portrait_status = "done"
            character.portrait_path = relative
            character.portrait_error = None
            character.portrait_prompt_id = None
            if character.portrait_history:
                history = [dict(entry) for entry in character.portrait_history]
                history[-1]["portrait_path"] = relative
                character.portrait_history = history
            logger.info("character %s: adopted the interrupted portrait", character.id)
        except ImageGenerationError as exc:
            character.portrait_status = "failed"
            character.portrait_error = str(exc)
            character.portrait_prompt_id = None
            logger.warning(
                "character %s: could not adopt the interrupted portrait: %s", character.id, exc
            )
        db.commit()
    finally:
        db.close()


def reset_interrupted_turns(settings: Settings | None = None) -> int:
    """On startup: pick interrupted image jobs back up instead of discarding them.

    A turn or character stuck in queued/generating was interrupted by the app's
    restart, but the ComfyUI job itself keeps running. Its persisted job id says
    which case it is: an output that already exists on the generator's side is
    adopted, and a job that is still queued or running is waited for — the card
    keeps saying "Drawing…" instead of offering a Retry that would paint a
    SECOND picture while the first one is still being drawn. Only a job ComfyUI
    no longer knows about becomes failed; a file already on disk heals to done.
    """
    settings = settings or get_settings()
    db = SessionLocal()
    client: httpx.Client | None = None
    try:
        if settings.image_generation_enabled:
            client = _client(settings)
        try:
            recovered = 0
            for turn in db.query(Turn).filter(
                Turn.image_status.in_(["queued", "generating"])
            ).all():
                recovered += 1
                if _image_file_exists(turn.image_path, settings):
                    turn.image_status = "done"
                    turn.image_error = None
                    continue
                state = (
                    job_recovery_state(client, str(turn.image_prompt_id))
                    if client is not None and turn.image_prompt_id
                    else "lost"
                )
                if state in ("done", "alive"):
                    turn.image_status = "queued"
                    turn.image_error = None
                    enqueue_resume_turn_image(turn.id)
                    continue
                turn.image_status = "failed"
                turn.image_error = "Interrupted"
                turn.image_prompt_id = None
            for character in db.query(Character).filter(
                Character.portrait_status.in_(["queued", "generating"])
            ).all():
                recovered += 1
                if _image_file_exists(character.portrait_path, settings):
                    character.portrait_status = "done"
                    character.portrait_error = None
                    continue
                state = (
                    job_recovery_state(client, str(character.portrait_prompt_id))
                    if client is not None and character.portrait_prompt_id
                    else "lost"
                )
                if state in ("done", "alive"):
                    character.portrait_status = "queued"
                    character.portrait_error = None
                    enqueue_resume_portrait(character.id)
                    continue
                character.portrait_status = "failed"
                character.portrait_error = "Interrupted"
                character.portrait_prompt_id = None
            db.commit()
            return recovered
        finally:
            if client is not None:
                client.close()
    finally:
        db.close()


def _image_file_exists(relative_path: str | None, settings: Settings | None = None) -> bool:
    """True when the generated file is actually on disk under IMAGE_DIR."""
    if not relative_path:
        return False
    try:
        return (Path((settings or get_settings()).image_dir) / relative_path).is_file()
    except OSError:
        return False


def retry_turn_image(turn_id: int) -> Turn:
    db = SessionLocal()
    try:
        turn = db.get(Turn, turn_id)
        if turn is None:
            raise ImageGenerationError("Turn not found")
        if turn.image_status != "failed":
            raise ImageGenerationError("Only a failed image can be retried")
        # If the file is actually on disk (a stale timeout or a restart marked
        # the turn failed after the download finished), heal the status instead
        # of burning GPU time on an identical regeneration.
        if _image_file_exists(turn.image_path):
            turn.image_status = "done"
            turn.image_error = None
            db.commit()
            db.refresh(turn)
            return turn
        # A retry is a NEW job: the old job id (of the interrupted attempt) must
        # not be adopted on top of it.
        turn.image_prompt_id = None
        turn.image_status = "queued"
        turn.image_error = None
        db.commit()
        enqueue_turn_image(turn.id)
        db.refresh(turn)
        return turn
    finally:
        db.close()


def retry_character_portrait(character_id: int) -> Character:
    db = SessionLocal()
    try:
        character = db.get(Character, character_id)
        if character is None:
            raise ImageGenerationError("Character not found")
        if character.portrait_status != "failed":
            raise ImageGenerationError("Only a failed portrait can be retried")
        # Same heal-first rule as scenes: an existing file means no GPU work.
        if _image_file_exists(character.portrait_path):
            character.portrait_status = "done"
            character.portrait_error = None
            db.commit()
            db.refresh(character)
            return character
        character.portrait_prompt_id = None  # a retry is a new job, not an adoption
        character.portrait_status = "queued"
        character.portrait_error = None
        db.commit()
        enqueue_portrait(character.id)
        db.refresh(character)
        return character
    finally:
        db.close()


