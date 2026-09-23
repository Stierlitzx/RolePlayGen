> **Historical document.** This task spec is fully implemented and kept for history only. The current truth is in `docs/FEATURES.md` (feature status, code locations) and `docs/ARCHITECTURE.md` (how it works). The specs it references (`IMAGE_FEATURE.md`, `FEATURE_SETUP_CHARACTERS.md`) predate the repository's git history and are not archived here.


# Task: longer setup fields, age rating with 18+ sub-options, image style picker, in-app lightbox, image cleanup on story delete

Read this whole file before changing anything. Also read `CLAUDE.md`, `SPEC.md`, `ARCHITECTURE.md` and the previously implemented specs (`IMAGE_FEATURE.md`, `FEATURE_SETUP_CHARACTERS.md`) before touching code — this feature builds on all of them. Names of modules/components below are suggestions: adapt to what already exists, but keep the described behavior.

This spec covers six independent changes, in a sensible implementation order:

1. Longer freeform text limits on the setup screen (Hero role especially).
2. Age rating per story (PEGI-like), with extra explicit-content options unlocked at 18+.
3. Intro-exposition checkbox default flipped to ON.
4. Image style picker per story + setting-coherence fix for image prompts (the "medieval armor in a Star Wars story / two portraits in different art styles" bug).
5. In-app fullscreen lightbox for images (scene illustrations AND character portraits, including the Characters tab).
6. Deleting a story also deletes its image files from disk.
7. Character portraits that evolve with the story (update / revert-to-previous look).
8. Much stronger scene prompting: deliberate camera shots, composition, varied expressions, full-body portrait framing.

---

## 1. Longer text limits

Current limits are too tight for users who describe their hero/plot in detail. New limits:

| Field | Old max | New max | UI change |
| --- | --- | --- | --- |
| `hero_role` | 200 | 1000 | becomes a multi-line `<textarea>` |
| `custom_setting` | 300 | 1000 | becomes a `<textarea>` |
| `content_restrictions` | 500 | 2000 | textarea (already is) |
| `custom_details` | 2000 | 5000 | textarea (already is) |
| `hero_name` | 100 | 200 | input (unchanged widget) |

Update the Pydantic `StoryCreate` schema limits and the `maxLength` attributes in the setup form to match. No other behavior changes. Old stories are unaffected (limits only apply at write time).

---

## 2. Age rating + 18+ sub-options

### 2a. Setup field

Add an `age_rating` dropdown to the setup screen, served from the backend like every other option list (`GET /api/setup-options` gains `age_ratings`). Values, PEGI-style:

`["3+", "7+", "12+", "16+", "18+"]`

Default for new stories: **"12+"**. The rating is stored in the story's settings JSON like every other setup field.

### 2b. 18+ sub-options

When (and only when) `age_rating == "18+"`, two extra independent checkboxes appear under it, both **default off**:

- **"Explicit sexual content"** (`explicit_sexual`) — the story may go all the way: porn-parody/hentai-level explicitness, not just fade-to-black romance.
- **"Graphic violence and gore"** (`graphic_violence`) — detailed blood, injury and brutality.

Rationale: an 18+ story is not automatically porn — it can be gory horror, a grimdark war story, a dark psychological drama, or explicit erotica. The two checkboxes let the player say which kind(s) they actually want; with both off, 18+ means "adult themes handled without explicit sexual detail or gore" (strong language, dark themes, non-graphic references are allowed).

Backend validation: `explicit_sexual` or `graphic_violence` set to `true` while `age_rating != "18+"` must be rejected with 422 (these flags are meaningless below 18+ and silently ignoring them would hide UI bugs).

### 2c. Narrator prompt changes

Add an AGE RATING section to `narrator_system.txt` fed from the story settings, with per-rating guidance, e.g.:

- `3+`/`7+`: wholesome; no violence beyond cartoonish, no romance beyond innocent, no swearing, scary moments stay mild.
- `12+`: teen adventure level — action violence without gore, romance without sexual content, mild language.
- `16+`: mature themes allowed — realistic violence (not lingering gore), sexual references/fade-to-black, stronger language.
- `18+`, both flags off: unrestricted adult themes, but no explicit sexual detail and no graphic gore.
- `18+` + `explicit_sexual`: explicit sexual content is permitted and expected when the story calls for it.
- `18+` + `graphic_violence`: graphic depictions of violence/gore are permitted and expected when the story calls for it.

Three rules stay absolute regardless of rating and must be stated in the prompt: every character in sexual or romantic content is an adult; the player's `content_restrictions` still override everything; the rating governs content, not prose quality (don't turn crude just because the ceiling is high).

**Backward compatibility:** stories created before this field have no `age_rating` in their settings. When it is missing, do not add any rating line to the narrator prompt at all — old stories keep their current voice exactly.

### 2d. Images and rating

The image pipeline today hardcodes `general` into the quality prefix and strips rating tokens. Change that coupling minimally:

- Ratings below 18+, and 18+ with `explicit_sexual` off: unchanged behavior — prefix contains `general`, rating tokens are stripped. Nothing changes for almost all stories.
- 18+ with `explicit_sexual` on: the rating token in the prefix becomes `explicit` instead of `general`, and `questionable`/`explicit` are no longer stripped from narrator tags. Everything else (quality prefix, `adult` enforcement when person tags appear, one-job-at-a-time queue) is unchanged. The **adults-only rule for depicted people stays absolute at every rating** — it is a safety property of the image pipeline, not a content preference.

Keep this mapping in one place on the backend (next to the existing prompt-assembly helpers), not scattered.

### 2e. Rating also gates the genre list, and images follow the rating

- Raise the genre combination limit from 3 to **5**: `MAX_GENRES` constant, `StoryCreate.genres` max length, and verify the frontend really reads `max_genres` from setup-options (it does by design — confirm, don't re-hardcode).
- `setup-options` gains a separate `adult_genres` list (e.g. "Hentai", "Erotica", "Slasher / gore", "Extreme horror"). The frontend shows these in the genre picker **only while `age_rating == "18+"`**; below 18+ they are hidden. Backend validation mirrors the checkbox rule: a story below 18+ containing an adult genre is rejected with 422.
- Restate 2d here for the implementer: the age rating governs **images as strictly as text**. An 18+ story with `explicit_sexual` off still gets `general`-rated images; only 18+ + explicit flips the image rating token.

---

## 3. Intro-exposition default ON

Flip the default of the existing "Explain the world and the hero before the story begins" checkbox: it must be **checked by default** on the setup screen (new stories only). Change the `StoryCreate.intro_exposition` schema default to `true` as well so API-created stories match the UI. Stories already created keep their stored flag — nothing retroactive.

---


## 4. Image style picker + setting coherence

### 4a. The bug this fixes

Observed in a real playthrough (Star Wars story): two character portraits came out in visibly different art styles (one clean anime cel-shading, one semi-realistic), and the second character wore medieval plate armor in a space-fantasy setting. Root causes:

1. Nothing pins the art style — each image is a fresh roll of the model's style dice.
2. `appearance_tags` and portrait prompts carry no setting/genre context, so a tag like "armor" drifts to whatever "armor" most often means in the checkpoint's training data (medieval plate).

### 4b. `image_style` setup field

Add an `image_style` dropdown to setup, served from the backend (`setup-options` gains `image_styles`). Each option maps to a fixed pair of tag strings in backend config (same file as the other setup lists):

```python
IMAGE_STYLE_TAGS = {
    "Anime (default)":      {"positive": "anime style, anime coloring", "negative": "realistic, photorealistic"},
    "Semi-realistic":       {"positive": "semi-realistic, painterly",   "negative": ""},
    "Cinematic realistic":  {"positive": "realistic, cinematic lighting, film still", "negative": "anime, cartoon"},
    "Comic book":           {"positive": "comic book art, bold outlines, flat colors", "negative": "photorealistic"},
    "Watercolor storybook": {"positive": "watercolor painting, storybook illustration, soft colors", "negative": "photorealistic"},
}
```

Exact tag strings are tunable later — what matters is the mechanism. Default: the first entry (matches the checkpoint the user already runs).

### 4c. Where style tags are applied

In the existing prompt-assembly helpers (`assemble_positive_prompt`, `assemble_portrait_prompt`): append the style's **positive** tags after the quality prefix for every image of that story (scenes and portraits alike). If the style has **negative** tags, extend `build_workflow` to also append them to the existing negative-prompt text of node `7` (append, comma-separated — never replace the user's workflow negative). The style comes from the story's settings; jobs need access to it (either passed into the job payload or looked up from the story row in the worker — pick whichever fits the current code with the least churn).

Stories created before this field have no `image_style` → no style tags are added (identical behavior to today).

### 4d. Setting coherence

Fix the anachronism half of the bug in the narrator prompt (`narrator_system.txt`), not with more backend string surgery:

- Instruct the narrator that all image tags (`image_prompt` and `appearance_tags`) must match the story's setting and genre: clothing, armor, weapons, technology and backgrounds must belong to the established world (e.g. in a space opera, "armor" means sci-fi armor — say "futuristic armor, sci-fi", never bare "armor" that resolves to medieval plate).
- Instruct it not to emit style words ("anime", "realistic", "oil painting") in tags at all — style is injected by the backend from `image_style` now.

### 4e. Face artifacts in wide shots (documentation only)

Faces of distant characters in wide/establishing shots render as smeared artifacts — this is a known checkpoint limitation (SDXL-class models cannot resolve a face that occupies a few dozen pixels), not a prompt bug. Handle it as follows:

- Document in `README.md` (image section) that the recommended fix is adding a FaceDetailer/ADetailer node to the ComfyUI workflow files (`comfy_workflows/wide.json`, optionally `portrait.json`). Such a node needs no inputs from the backend — if it is present in the workflow graph it just runs, so **no backend change is required**; the node-map convention stays as is. Note the extra VRAM cost against the 8 GB budget.
- No code change for this item beyond the README paragraph. Do not try to fix small faces with prompt tags — it does not work reliably.

### 4f. Portrait framing: full figure, varied poses and expressions

Current portraits are framed too tightly: the suffix `portrait, close-up, looking at viewer, simple background` makes the face fill the whole frame. Change `PORTRAIT_SUFFIX` to a full-figure presentation, e.g. `full body, standing, looking at viewer, simple background` — the whole character from head to feet must fit in the frame. The portrait workflow is 4:5 (1024x1344), which suits full-body framing fine. Update the suffix constant and its tests.

Pose and expression are NOT part of the fixed `appearance_tags` — they vary per portrait. The narrator supplies short `pose` and `expression` tag strings with every portrait request (first appearance and every update, see §7), e.g. `"pose": "one hand on hip, leaning on railing"`, `"expression": "confident smirk"`. The portrait prompt becomes: quality prefix + appearance tags + pose + expression + framing suffix. Default to a simple standing pose and a character-appropriate expression when the narrator omits them — but never a neutral poker face as the universal default; expressions must vary with the character and the moment.

---

## 5. In-app lightbox for all images

Today scene illustrations and inline introduction portraits open in a new browser tab showing the raw file URL, and portraits in the Characters tab are not clickable at all. Replace all of that with one shared lightbox:

- New `Lightbox` (or `ZoomableImage`) component: clicking any image opens a fullscreen overlay (fixed position, dimmed backdrop) showing the image at up to ~95vw/95vh.
- Zoom: clicking the opened image toggles between fit-to-screen and actual-size (actual size scrollable/pannable); mouse-wheel zoom is a nice-to-have, click-to-zoom is the requirement.
- Close: `Esc` key, clicking the dimmed backdrop, or an explicit ✕ button. While open, lock body scroll and keep focus inside the overlay (basic dialog semantics, `role="dialog"`, `aria-label`).
- Apply it in all three places: `ImageBlock` (scene illustrations), `IntroducedCharacters` (inline portraits in the feed), and `CharactersPanel` — both the card grid and the detail view (a click on a card still opens the detail view as today; the portrait inside the detail view opens the lightbox; optionally a small zoom affordance on grid portraits too, but the detail view is the required path).
- Remove the `<a target="_blank">` wrappers this replaces. The "open raw file in a new tab" behavior goes away entirely.

---

## 6. Delete story → delete its images

`DELETE /api/stories/{id}` currently removes only the database rows; the PNGs under `IMAGE_DIR/{story_id}/` (scene images and `char_*.png` portraits) stay on disk forever. Fix:

- After the story row is deleted and committed, recursively delete `IMAGE_DIR/{story_id}/` (`shutil.rmtree(..., ignore_errors=True)` or equivalent). Failures must be logged, never fatal — a missing/locked folder must not turn a successful DB delete into an error response.
- Do NOT delete anything outside `IMAGE_DIR/{story_id}/`; resolve and verify the target stays inside `IMAGE_DIR` before deleting (defensive path check).
- Only the delete-story endpoint does this. No background cleanup, no startup sweep — keep it scoped.

---

## 7. Character portraits that evolve with the story

A character's look can change mid-story (disguise, new outfit, armor donned, an injury) and later change back ("took off the disguise and put the old coat on again"). Support both directions without wasting GPU:

### 7a. Turn contract additions

`CharacterReport` gains optional fields (everything stays optional; old stories unaffected):

- `portrait_update`: present when the character's look meaningfully and persistently changes from this turn on. Carries the NEW complete `appearance_tags` plus optional `pose`/`expression` for the new portrait (see 4f).
- `portrait_revert`: `true` when the character returns to their previous look.

Narrator guidance (add to `narrator_system.txt`): use these rarely and only when the story itself changes the look — never for one-scene details. `portrait_revert` means "back to the immediately previous look" (a history stack, not a free choice). Never send update and revert for the same character in one turn.

### 7b. Backend: portrait history per character

Give `Character` a small version history — a JSON list column on the character row is enough: entries `{appearance_tags, pose, expression, portrait_path, turn_id}`. The latest entry is the current look. Initialize history from the existing single-version data so old characters behave exactly as today.

- `portrait_update`: append the new entry, make it current, enqueue ONE portrait job with the new tags (same queue, same one-job-at-a-time rule). The character's `appearance_tags` (used for scene splicing via `characters_in_scene`) switch to the new tags from this turn on — scene images follow outfit changes too.
- `portrait_revert`: if a previous history entry exists, make it current and point `portrait_path` at its already-generated file — **no GPU job at all**, the revert is instant and free. If there is no previous entry, ignore the revert and log a warning.
- `portrait_status` / `portrait_error` always describe the current version. The Characters tab and the inline feed need no structural change — they show whatever `portrait_url` currently points to.

---

## 8. Much stronger scene prompting (camera, composition, emotion)

The quality prefix (`masterpiece, best quality, amazing quality, general`) and the user's negative prompt in node 7 stay as the base — what must improve is what the narrator adds on top. Rewrite the IMAGE FIELDS section of `narrator_system.txt` to require, for every `image_prompt`:

- **Camera shot, always, chosen deliberately** — exactly one: `close-up` (an emotion is the point), `medium shot` / `cowboy shot` (dialogue, one-two characters), `medium wide shot` (the default for scenes with people: wide enough for context, close enough that faces survive — wide shots should lean closer, not farther), `wide shot` (landscapes and establishing shots only; accept tiny faces there).
- **Camera angle when it adds drama**: `dutch angle`, `low angle`, `from behind`, `over-the-shoulder shot` — sparingly, when the moment calls for it.
- **Composition and subject**: one clear focal subject, what they are doing, where they are in the frame (`looking at viewer`, `facing away`, `in foreground`).
- **Emotion, always**: at least one expression tag per visible character (`determined expression`, `forced smile`, `angry`, `worried`, `laughing`), varying turn to turn and matching the text. A static neutral face on every image is a defect.
- **Light and atmosphere**: 1-2 lighting tags (`backlighting`, `neon glow`, `overcast`) plus a mood tag (`tense`, `melancholic`).
- Keep all existing rules: English danbooru-style tags, no sentences, no quality/rating/style words, no appearance re-description (the backend splices appearance), setting-coherent content (§4d), adults only.
- When the point of the scene is a character's reaction, prefer `image_format: "portrait"` or a medium shot over a wide one — this is also the cheap mitigation for the small-face artifact problem (§4e).

---

## Non-negotiable rules

- All new setup fields (`age_rating`, `explicit_sexual`, `graphic_violence`, `image_style`) are optional/nullable with defaults that reproduce today's behavior for stories created before this change: missing `age_rating` → no rating text in the narrator prompt; missing `image_style` → no style tags; `intro_exposition` stored per story, old stories untouched.
- Adults-only depiction in images and adults-only sexual/romantic content in text are absolute at every rating, including 18+ explicit.
- The single-worker, one-job-at-a-time ComfyUI queue constraint is unchanged.
- Option lists (`age_ratings`, `image_styles` and their tag mappings) live in backend config and are served via `/api/setup-options` — nothing hardcoded in the frontend.
- The rating governs text AND images consistently: below-18+ stories keep `rating: general` images no matter what the narrator emits.

## Tests

- Backend unit: new field limits (accept at new max, 422 above); `explicit_sexual`/`graphic_violence`/adult genres all rejected below 18+; genre limit is 5; prompt assembly includes style tags (scene and portrait) and appends negative style tags to node `7`; rating-token mapping (`general` by default, `explicit` only for 18+ + `explicit_sexual`, adults-only tag rule intact); portrait prompt uses the full-body framing suffix and includes narrator-supplied pose/expression; `portrait_update` appends a history entry, switches `appearance_tags` and enqueues exactly one job; `portrait_revert` switches back to the previous file with **zero** jobs enqueued; revert with no history is ignored; delete-story removes the story's image folder and tolerates a missing folder; old-story settings (no rating/style/history fields) produce byte-identical prompt assembly to before.
- Backend endpoint: setup-options serves the new lists (`age_ratings`, `image_styles`, `adult_genres`, `max_genres`); story create/update round-trips the new fields.
- Frontend: setup screen shows the 18+ checkboxes AND the adult genres only when 18+ is selected; genre picker allows up to 5; intro-exposition checkbox is checked by default; lightbox opens from `ImageBlock`/`IntroducedCharacters`/character detail, closes on Esc and backdrop click, zoom toggle switches fit/actual size.

## Manual test plan

1. Create a story with a ~600-character Hero role (multi-line) — saves fine and shows up in the narrator's hero portrayal.
2. Create a 12+ story and an 18+ story with both flags on; confirm the tone/content ceiling differs accordingly and that the 18+ one keeps every depicted character adult.
3. Confirm the intro checkbox is checked by default, and that unchecking it still gives an in-medias-res opening.
4. Same setting, two image styles (Anime vs Cinematic realistic): portraits and scenes visibly follow the chosen style, and a sci-fi story no longer produces medieval armor on characters.
5. Click a scene image, an inline introduction portrait, and a portrait in the Characters tab detail view: fullscreen overlay opens, zoom toggles, Esc closes; no new browser tab anywhere.
6. Delete a story that has generated images: the story's folder under `IMAGE_DIR` is gone; deleting a story with no images still returns 204.
7. With 18+ selected, the genre picker shows the adult genres (Hentai etc.) and allows up to 5 genres; below 18+ neither is available, and forcing an adult genre via API is rejected.
8. New portraits show the full figure head-to-feet (not a face close-up), and two portraits generated in one story show different poses/expressions, not identical poker faces.
9. Play a story where a character changes outfit and later changes back: a new portrait is generated on the change; on the return, the previous portrait reappears instantly (watch the backend log — no new ComfyUI job), and scene images during the outfit episode use the temporary look.
10. Scene images across a few turns: camera shots vary deliberately, faces in people-scenes are large enough to be clean, and expressions match the text.

## Definition of done

Tests pass, all ten manual checks behave as described, `README.md` documents the new setup fields (rating, 18+ options, adult genres, style picker, longer fields), the lightbox, portrait evolution and image cleanup, and `SPEC.md`/`ARCHITECTURE.md` are updated (new settings fields, style-tag prompt assembly, rating-token mapping, portrait history contract, new prompting rules, lightbox behavior, delete-cleanup flow, and the FaceDetailer recommendation for wide-shot faces). Report which files changed and anything that could not be done.

## Do not

Do not let 18+ flags relax the adults-only rules or the player's `content_restrictions`. Do not replace the negative prompt in node `7` — only append style negatives. Do not add style words to the narrator's own tag instructions beyond "don't emit style words". Do not delete files outside the story's own image folder. Do not keep the raw-file new-tab behavior anywhere once the lightbox exists. Do not enqueue a ComfyUI job for a portrait revert — it reuses an existing file. Do not let pose/expression tags leak into the fixed `appearance_tags` used for scene splicing (they are per-portrait only). Do not change behavior of stories created before this feature ships.

