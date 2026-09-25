# Specification

## Concept

The player configures a story, the AI narrates it turn by turn, and the player makes decisions. Stories are saved and can be resumed later.

## Screens

Home. A list of saved stories (title, genre, number of turns, date) and a "New story" button. A story can be resumed or deleted with a confirmation.

Setup. A form with the parameters described below and a "Start" button. If the AI key is not configured, show a clear message with instructions instead of crashing.

Story. The main screen. A title and an exit button to the home screen at the top. In the middle, a feed of turns: the narrator text and, under it, the choice the player made. At the bottom, the active choice for the current turn. While waiting for the AI, show a loading indicator and block input.

Ending. When `is_ending` is `true`, show the story summary and the buttons "New story" and "Home".

## Story management

While a story has only its opening turn, the story screen offers "Change beginning" (edit the setup, backed by `PATCH /api/stories/{id}`) and "Regenerate opening" (`regenerate-start`, rerolls the prologue). After that, the header shows "Redo last turn" (`regenerate-last`): the last turn is deleted and its stored player input replayed — this works on finished stories too, so a bad ending can be redone. Characters introduced on the deleted turn are removed with it, portrait updates from it are rolled back, and its image file is deleted best-effort. The narrator style can be changed mid-story from the story screen header and applies from the next turn.

## Setup parameters

Setting: a list of presets (medieval kingdom, space station, modern city, post-apocalypse, wizard school, Wild West, underwater world, cyberpunk metropolis, high fantasy epic, noir detective city, horror mansion, historical drama, superhero city, fairy tale kingdom, pirate seas, dystopia, steampunk, wuxia, survival island, cosmic horror, slice-of-life school) and a "Custom" option with a multi-line text field (up to 1000 characters). A "Random" option is available and picks uniformly among all presets except Custom.

Genre: fantasy, science fiction, detective, horror, adventure, romance, thriller, comedy, drama, action, mystery, slice of life, historical, psychological, mythology, cyberpunk, dark fantasy, survival, political intrigue, tragedy. The player can combine up to five. A "Random" option is available. While the age rating is 18+, the picker also shows the adult genres (Hentai, Erotica, Slasher / gore, Extreme horror); below 18+ they are hidden, and the backend rejects a story below 18+ containing an adult genre with 422.

Tone: dark, serious, light, ironic, epic, cozy. One option or "Random".

Hero role: optional multi-line field (up to 1000 characters). Empty means the AI invents the role.

Hero name: optional text field (up to 200 characters).

Hero appearance: optional multi-line field (up to 1000 characters) describing how the hero looks. It is passed to the narrator with the other story parameters, so the narration, the hero's `appearance_tags` and every portrait/scene image follow the player's description. Empty means the AI invents the look.

Hero gender: Unspecified / Female / Male, default Unspecified. It is shown in the turn prompt (`Hero gender:`) and maps to the `1girl`/`1boy` appearance tags for portraits and scenes.

Length: short (50 turns), medium (100), long (no limit), or a custom count (50-500).

Text model source: "Gemini (cloud)", "Groq (cloud)", "OpenRouter (cloud)", "Mistral (cloud)" or "Local model" (the OpenAI-compatible server from `.env`), picked per story and stored as `llm_provider` in the story settings. With Gemini, a model dropdown is served from the backend; the other providers use the model configured in `.env` (`GROQ_MODEL`, `OPENROUTER_MODEL`, `MISTRAL_MODEL`, `OPENAI_MODEL`). A story without the field follows the server-wide `LLM_PROVIDER` default.

Custom details: optional multi-line field (up to 5000 characters) for anything the preset does not cover — plot premise, tone details, characters the player wants present, relationships, factions, a starting conflict. Concatenated into the world-building part of the narrator prompt, clearly separated from the preset description.

Content restrictions: optional text field (up to 2000 characters), for example "no violent scenes". Unlike Custom details, this field is exclusionary and overrides everything else, including the age rating.

Age rating: a PEGI-style dropdown (`3+`, `7+`, `12+`, `16+`, `18+`), default `12+`. The rating governs both the narration and the images. When (and only when) `18+` is selected, two independent checkboxes appear under it, both default off: "Explicit sexual content" and "Graphic violence and gore". With both off, 18+ means adult themes handled without explicit sexual detail or gore. Setting either flag below 18+ is rejected with 422. Three rules stay absolute at every rating: every character in sexual or romantic content is an adult; the player's content restrictions override everything; the rating sets the content ceiling, not the prose quality. Stories created before this field have no rating in their settings, and the narrator prompt gets no rating section for them at all — their voice is unchanged.

Narrator style: a dropdown (Classic, Noir, Epic saga, Light and witty, Gothic dread, Disco Elysium) that sets the narrator's voice via a prompt fragment. It can be changed mid-story from the story screen header and applies from the next turn.

Image style: a dropdown (Anime default, Semi-realistic, Cinematic realistic, Comic book, Watercolor storybook) that pins one art style for every image of the story. Each option maps to a fixed pair of positive/negative tag strings in backend config; the positive tags are appended after the quality prefix of every scene and portrait prompt, and the negative tags are appended (never replacing) to the negative prompt of the ComfyUI workflow. Stories without the field get no style tags. The narrator is instructed never to emit style words in image tags and to keep all tags coherent with the story's setting and genre (in a space opera, "armor" means sci-fi armor).

Story language: Russian, English, Kazakh. Russian by default. Controls only the language the narration and UI text are written in.

Setting culture: a separate dropdown (Match story language, Slavic/Russian, Western European, East Asian, Norse/Scandinavian, Middle Eastern, South Asian, Latin American, African, Generic/international fantasy, Custom). Controls naming conventions for people and places, social customs and cultural details — independently of the story language. "Match story language" is the neutral default and reproduces the old behavior, so stories created before this field existed are unaffected.

Character naming culture: optional override that pins character names to a specific culture when it should differ from the general setting culture. Empty falls back to the setting culture.

Intro exposition: a checkbox, on by default (for new stories and in the API schema). Off means the first turn drops the player straight into a scene and reveals the world gradually; on means the first turn opens with a short framing passage establishing the setting and the hero's situation. The flag only changes how the first turn's prompt is built; later turns are unaffected. Stories created before the default flip keep their stored flag.

The option lists live in one place on the backend and are served through the API, so they can be changed without touching the frontend.

## Player choice

Every turn has a choice mode. There are three modes.

`open`: three to four options plus a field for a custom action. The player clicks an option or writes their own.

`locked`: two to four options, no custom input.

`binary`: exactly two options, no custom input. It is visually highlighted as an important moment.

The frontend renders the interface strictly by mode. The backend also checks it: in `locked` and `binary` modes a turn with custom text is rejected.

## Turn contract

The model returns a single JSON object. The backend validates and stores it.

```json
{
  "narration": "turn text, paragraphs separated by \n\n",
  "choice": {
    "mode": "open",
    "options": [ { "id": "a", "text": "..." } ],
    "allow_custom": true,
    "prompt": "What will you do?"
  },
  "state": {
    "scene": "scene name",
    "summary": "1-3 sentences about what happened",
    "facts": ["important fact to remember"]
  },
  "is_ending": false,
  "image_prompt": "1girl, solo, adventurer, brown leather coat, standing on cliff, morning mist, wide shot",
  "image_format": "wide",
  "hero": { "name": "Ayla", "appearance_tags": "1girl, silver hair, blue eyes, braided ponytail, brown leather coat", "portrait_update": false, "portrait_revert": false },
  "characters": [
    {
      "name": "Kaelen",
      "is_new": true,
      "role": "sky pirate captain",
      "relationship": "reluctant ally",
      "description": "Sharp-tongued captain of the airship Halcyon.",
      "appearance_tags": "1boy, brown hair, green eyes, red long coat, tricorn hat, scar"
    },
    { "name": "Kaelen", "is_new": false, "relationship": "ally" }
  ],
  "characters_in_scene": ["__hero__", "Kaelen"]
}
```

Validation rules: `open` requires 3-4 options and `allow_custom` set to `true`. `locked` requires 2-4 options and `allow_custom` set to `false`. `binary` requires exactly 2 options and `allow_custom` set to `false`. Option ids are `a`, `b`, `c`, `d`. If `is_ending` is `true`, `choice` must be `null`. The fields `narration`, `state.scene` and `state.summary` are required and non-empty. `image_prompt` and `image_format` are optional; an invalid `image_format` falls back to `wide`, and an empty or missing `image_prompt` falls back to a generic scene shot (`solo, standing, detailed background, wide shot`) so every turn is still illustrated when image generation is enabled.

`narration` is prose, not a transcript: the rules ask for 3-9 blank-line separated paragraphs with the quoted speech carried inside them (see the PROSE FIRST and DIALOGUE SPACING rules in `narrator_system.txt`). The backend measures the answer (`services/narration_style.py`): when a turn longer than 700 characters comes back as a single block of text, with more than 60% of its words inside quotes/italics/dash dialogue, or with a whole chain of quoted exchanges crammed into one paragraph (more than five), the turn gets ONE more request carrying the format complaint. A style problem is never fatal — the second answer is stored as it is, so a model with a bad day costs one extra call, not a lost turn. Short turns and single-paragraph vignettes are never checked, because the rules explicitly allow a brief exchange.

The same module carries the novelty guard: the new narration is compared against the narrations of the last three turns (the ones the prompt already shows the model). A turn that re-uses a run of 8 words from an earlier turn gets a `REPEATED CONTENT` complaint, and a quoted line or italic thought of two words or more that comes back word for word gets a `REPEATED DIALOGUE` complaint; either one asks for the same single rewrite and, like a format problem, is never fatal. Names, places and short turns alone are not enough to trigger it, so an ordinary continuation is never rewritten.

`characters`, `characters_in_scene` and `hero` are optional; old responses without them still validate. In `characters` the narrator lists every named character appearing or referenced this turn (hero excluded): `is_new: true` only on first introduction, and then `appearance_tags` (same tag convention as `image_prompt`), `role`, `relationship` (to the player character) and `description` are required; later mentions send only `name` (plus `relationship` when it changes). `hero` is sent on the first turn with the hero's name and `appearance_tags`, and again whenever the hero's look changes for good: `portrait_update: true` with the NEW complete `appearance_tags` (and a pose/expression for the new portrait) repaints the hero's portrait and every later scene image, `portrait_revert: true` brings the previous look back instantly. One-scene details (mud, sweat, rain) stay in `image_prompt` and never touch the stored look. The hero's current `appearance_tags` are sent back to the narrator in the `KNOWN CHARACTERS` block, so an update is written against the look actually stored rather than from memory. `characters_in_scene` lists who is visibly present in the turn's illustration (`__hero__` is the player character) so the backend can splice stored appearance tags into the image prompt.

A character report can also carry optional per-portrait `pose` and `expression` tag strings (used for that portrait only, never spliced into scenes), `portrait_update` (the character's look changes persistently from this turn on; accompanied by the NEW complete `appearance_tags`) and `portrait_revert` (the character returns to their immediately previous look). These are used rarely, only when the story itself changes the look, and never update and revert for the same character in one turn. See "Character tracking and portraits".

## Scene illustrations

After a turn is saved and returned, an illustration is generated in the background by a local ComfyUI server; the text and the choice are never blocked by it. Under the narration text the turn view shows an image block with four states: a shimmering placeholder with the final aspect ratio while `queued`/`generating` (polled every 2 seconds), the picture with a fade-in when `done` (click opens it full-size), a compact error with a Retry button when `failed`, and nothing when `none`. The choice panel stays usable while an image loads, and the placeholder reserves its height so the page does not jump.

`image_prompt` describes only the current scene in English as comma-separated danbooru-style tags (subject, appearance, clothing, action, place, lighting, camera) — no sentences, and no quality, rating or style words (style is injected by the backend from the story's `image_style`). Every prompt includes one deliberate camera shot (`close-up` when an emotion is the point, `medium shot`/`cowboy shot` for dialogue, `medium wide shot` as the default for scenes with people, `wide shot` for landscapes and establishing shots only), a clear focal subject and composition, at least one expression tag per visible character (varied turn to turn, matching the text), and 1-2 lighting tags plus a mood tag. All tags stay coherent with the story's setting and genre. `image_format` is always `wide`: scene illustrations render in the wide format and framing is expressed with shot tags; the narrator must also restate the key appearance anchors (hair, eyes, one signature clothing item) of any named character visible in a wide or medium wide shot. NPC `appearance_tags` always start with the gender tag (`1boy`/`1girl`) matching the narration.

Scenes with two or more characters are two-shots, and the backend enforces it rather than trusting the tags: `image_service._group_scene_tags` drops `solo` and a lone `1girl`/`1boy` (they delete everyone else from the frame), writes the real count tags from the stored appearance anchors (`2girls`, `1boy, 1girl`), replaces anything tighter than a `medium wide shot` so nobody is cropped out, and adds `two-shot, facing each other, looking at each other` — at most one character may face the lens, and `looking at viewer` is negated in the negative prompt, because the people in the frame must engage with each other, not with the camera. One character in frame keeps the close framing the camera rules ask for.

The backend prepends a rating token: `general` for every story below 18+ and for 18+ stories with explicit content off; `explicit` only for 18+ stories with explicit sexual content on. The SDXL-era quality prefix (`masterpiece, best quality, amazing quality`) is NOT written any more — on Qwen-Image-2.1 it produced flat, oversaturated colors — and the same words are stripped from the narrator's tags. The narrator's own content tags are not filtered while content filtering is off (DECISIONS 2026-09-25). It ensures `adult` is present when a person tag appears — the adults-only rule for depicted people is absolute at every rating — and sends the job to ComfyUI strictly one at a time.

A scene reference is always a character portrait (hero first, when `IMAGE_REFERENCE_MODE=img2img`), never a previous scene image, and the drawn picture is written by ComfyUI into its own `output/roleplaygen/story_<id>/` folder (`scene_<turn_id>_*.png`, `portrait_<character_id>_*.png`) before the app copies it into `IMAGE_DIR/<story_id>/` — images of different stories never share one folder. Because the sampler starts from the portrait, a place the story has just left can survive into the next picture, so when the narrator's `state.scene` names a different place than the previous turn, the place words of the previous turn that the new scene no longer uses (never whole tags — a tag may carry a character) are added to the negative prompt: the story walks out of the forest into a hut and the picture shows the hut. The narrator is told the same rule (`CURRENT PLACE ONLY` in the system prompt): name the new place early, drop the old one completely.

## Character tracking and portraits

The story screen has two tabs: Story (the turn feed) and Characters. The Characters tab shows a card per character — portrait (placeholder while `queued`/`generating`, a silhouette for `none`/`failed`), name, role, relationship — with the hero pinned first and marked "you". Clicking a card opens a detail view with the full portrait and description; a `failed` portrait offers a Retry button there. The list polls the backend every ~2.5 s only while any portrait is still in progress.

Portraits also appear inline in the turn feed: on the turn where a character is first introduced (`first_seen_turn_id`), their portrait, name and role render under the scene illustration, so a first meeting shows the scene image and every new face together. A look that changes later (`portrait_update`, or a `portrait_revert` back to an earlier version) appears the same way on the turn it happened in, marked "New look" — the character is not re-introduced, only their new picture is shown under the narration that changed it.

Every reported character is stored in the `characters` table (one row per story and name). When a character is first introduced, a portrait job goes into the same single-worker ComfyUI queue as scene illustrations (never two jobs on the GPU at once) and always uses the portrait workflow. The portrait prompt is built from the character's stored `appearance_tags` with the same tag handling as scene prompts (the backend's own quality words deduped, content left untouched), plus this portrait's `pose`/`expression` (narrator-supplied per portrait — including the hero's first portrait via the `hero` report — varied per character in stance, camera side and gaze; `full body`/`upper body` allowed inside the pose) with only a blank-portrait fallback underneath (`standing, looking at viewer`) and a head-to-thighs framing suffix (`cowboy shot` unless the character's own tags name a shot, `simple background`). Portraits are general-rated by default at every rating — the rating token is the backend's decision, never the narrator's — and the narrator's own nudity tags are passed through unfiltered (DECISIONS 2026-09-25). A portrait is rated explicit only when the story is 18+ with explicit content on AND the narrator deliberately tags that look as nude (a plot-driven `portrait_update`). The character detail view also shows a "Past looks" gallery: every portrait-history version with its file, opening in the shared lightbox, with the current look marked. `role`/`relationship`/`description` are UI-only and never reach the image model.

Each character keeps a small portrait history (a JSON list on the row: `{appearance_tags, pose, expression, portrait_path, turn_id}` per version; the latest entry is current). On `portrait_update` a new entry is appended and made current, the character's `appearance_tags` switch to the new tags from that turn on (scene images follow outfit changes too), and exactly one portrait job is enqueued. On `portrait_revert`, if a previous entry exists it becomes current and `portrait_path` points at its already-generated file — instantly, with no GPU job; with no previous entry the revert is ignored and logged. `portrait_status`/`portrait_error` always describe the current version, and the UI needs no structural change — it shows whatever `portrait_url` points to. Old characters without history are initialized from their single-version data and behave exactly as before.

Appearance consistency is enforced by the backend, not the narrator: when assembling a scene prompt, the stored `appearance_tags` of every character listed in `characters_in_scene` (hero first) are prepended to the narrator's `image_prompt`, so a character looks the same across turns even though the text model has no memory between generations. Without `characters_in_scene` the behavior falls back to the hero's tags only. All name matching (reports, scene names, reference portraits) uses the shared fuzzy matcher in `services/character_matching.py`, so a re-described known character never spawns a duplicate row; scenes render tag-only by default (no portrait latent — see `IMAGE_SCENE_REFERENCE`), and a portrait regeneration is driven by the previous portrait so an evolving look keeps the same face.

## Lightbox

Every image in the app — scene illustrations, inline introduction portraits in the feed, and portraits in the Characters tab (detail view) — opens in a shared fullscreen in-app lightbox on click: a fixed overlay with a dimmed backdrop showing the image at up to ~95vw/95vh. Clicking the opened image toggles between fit-to-screen and actual size (pannable); `Esc`, a backdrop click or a ✕ button closes it. While open, body scroll is locked and the overlay has basic dialog semantics (`role="dialog"`, `aria-label`). Images never open the raw file in a new browser tab.

## Persistence

Every story and every turn is saved to SQLite right after the response arrives. Closing the tab must not lose progress. An unfinished story is restored at exactly the turn where it stopped. Deleting a story also recursively deletes its image folder (`IMAGE_DIR/{story_id}/`, scenes and portraits); the deletion is verified to stay inside `IMAGE_DIR`, and filesystem failures are logged but never turn a successful database delete into an error.

## Out of scope

Word-by-word text streaming, voice, multiple users, story export, mobile adaptation beyond the basics.

Non-goals: this is a guided interactive story, not a general chat client — lorebooks, text-to-speech, many more provider types and mini-games are not planned unless they are added to `docs/FEATURES.md` first.
