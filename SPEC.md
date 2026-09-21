# Specification

## Concept

The player configures a story, the AI narrates it turn by turn, and the player makes decisions. Stories are saved and can be resumed later.

## Screens

Home. A list of saved stories (title, genre, number of turns, date) and a "New story" button. A story can be resumed or deleted with a confirmation.

Setup. A form with the parameters described below and a "Start" button. If the AI key is not configured, show a clear message with instructions instead of crashing.

Story. The main screen. A title and an exit button to the home screen at the top. In the middle, a feed of turns: the narrator text and, under it, the choice the player made. At the bottom, the active choice for the current turn. While waiting for the AI, show a loading indicator and block input.

Ending. When `is_ending` is `true`, show the story summary and the buttons "New story" and "Home".

## Setup parameters

Setting: a list of presets (medieval kingdom, space station, modern city, post-apocalypse, wizard school, Wild West, underwater world, cyberpunk metropolis, high fantasy epic, noir detective city, horror mansion, historical drama, superhero city, fairy tale kingdom, pirate seas, dystopia, steampunk, wuxia, survival island, cosmic horror, slice-of-life school) and a "Custom" option with a text field. A "Random" option is available and picks uniformly among all presets except Custom.

Genre: fantasy, science fiction, detective, horror, adventure, romance, thriller, comedy, drama, action, mystery, slice of life, historical, psychological, mythology, cyberpunk, dark fantasy, survival, political intrigue, tragedy. The player can combine up to three. A "Random" option is available.

Tone: dark, serious, light, ironic, epic, cozy. One option or "Random".

Hero role: optional text field. Empty means the AI invents the role.

Hero name: optional text field.

Length: short (50 turns), medium (100), long (no limit), or a custom count (50-500).

Custom details: optional multi-line field for anything the preset does not cover — plot premise, tone details, characters the player wants present, relationships, factions, a starting conflict. Concatenated into the world-building part of the narrator prompt, clearly separated from the preset description.

Content restrictions: optional text field, for example "no violent scenes". Unlike Custom details, this field is exclusionary.

Story language: Russian, English, Kazakh. Russian by default. Controls only the language the narration and UI text are written in.

Setting culture: a separate dropdown (Match story language, Slavic/Russian, Western European, East Asian, Norse/Scandinavian, Middle Eastern, South Asian, Latin American, African, Generic/international fantasy, Custom). Controls naming conventions for people and places, social customs and cultural details — independently of the story language. "Match story language" is the neutral default and reproduces the old behavior, so stories created before this field existed are unaffected.

Character naming culture: optional override that pins character names to a specific culture when it should differ from the general setting culture. Empty falls back to the setting culture.

Intro exposition: a checkbox, off by default. Off means the first turn drops the player straight into a scene and reveals the world gradually; on means the first turn opens with a short framing passage establishing the setting and the hero's situation. The flag only changes how the first turn's prompt is built; later turns are unaffected.

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
  "hero": { "name": "Ayla", "appearance_tags": "1girl, silver hair, blue eyes, braided ponytail, brown leather coat" },
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

Validation rules: `open` requires 3-4 options and `allow_custom` set to `true`. `locked` requires 2-4 options and `allow_custom` set to `false`. `binary` requires exactly 2 options and `allow_custom` set to `false`. Option ids are `a`, `b`, `c`, `d`. If `is_ending` is `true`, `choice` must be `null`. The fields `narration`, `state.scene` and `state.summary` are required and non-empty. `image_prompt` and `image_format` are optional; an empty or missing `image_prompt` skips illustration for the turn, and an invalid `image_format` falls back to `wide`.

`characters`, `characters_in_scene` and `hero` are optional; old responses without them still validate. In `characters` the narrator lists every named character appearing or referenced this turn (hero excluded): `is_new: true` only on first introduction, and then `appearance_tags` (same tag convention as `image_prompt`), `role`, `relationship` (to the player character) and `description` are required; later mentions send only `name` (plus `relationship` when it changes). `hero` is sent on the first turn only, with the hero's name and `appearance_tags`. `characters_in_scene` lists who is visibly present in the turn's illustration (`__hero__` is the player character) so the backend can splice stored appearance tags into the image prompt.

## Scene illustrations

After a turn is saved and returned, an illustration is generated in the background by a local ComfyUI server; the text and the choice are never blocked by it. Under the narration text the turn view shows an image block with four states: a shimmering placeholder with the final aspect ratio while `queued`/`generating` (polled every 2 seconds), the picture with a fade-in when `done` (click opens it full-size), a compact error with a Retry button when `failed`, and nothing when `none`. The choice panel stays usable while an image loads, and the placeholder reserves its height so the page does not jump.

`image_prompt` describes only the current scene in English as comma-separated danbooru-style tags (subject, appearance, clothing, action, place, lighting, camera) — no sentences, no quality or rating words. `image_format` is `portrait` for character/dialogue/close moments and `wide` for landscapes, action, group or establishing shots. The backend prepends `masterpiece, best quality, amazing quality, general, `, strips any rating/quality tokens from the narrator tags, ensures `adult` is present when a person tag appears, and sends the job to ComfyUI strictly one at a time. All images are rated `general` and show adults only.

## Character tracking and portraits

The story screen has two tabs: Story (the turn feed) and Characters. The Characters tab shows a card per character — portrait (placeholder while `queued`/`generating`, a silhouette for `none`/`failed`), name, role, relationship — with the hero pinned first and marked "you". Clicking a card opens a detail view with the full portrait and description; a `failed` portrait offers a Retry button there. The list polls the backend every ~2.5 s only while any portrait is still in progress.

Portraits also appear inline in the turn feed: on the turn where a character is first introduced (`first_seen_turn_id`), their portrait, name and role render under the scene illustration, so a first meeting shows the scene image and every new face together.

Every reported character is stored in the `characters` table (one row per story and name). When a character is first introduced, a portrait job goes into the same single-worker ComfyUI queue as scene illustrations (never two jobs on the GPU at once) and always uses the portrait workflow. The portrait prompt is built from the character's stored `appearance_tags` with the same sanitization rules as scene prompts plus a portrait framing suffix; `role`/`relationship`/`description` are UI-only and never reach the image model.

Appearance consistency is enforced by the backend, not the narrator: when assembling a scene prompt, the stored `appearance_tags` of every character listed in `characters_in_scene` (hero first) are prepended to the narrator's `image_prompt`, so a character looks the same across turns even though the text model has no memory between generations. Without `characters_in_scene` the behavior falls back to the hero's tags only.

## Persistence

Every story and every turn is saved to SQLite right after the response arrives. Closing the tab must not lose progress. An unfinished story is restored at exactly the turn where it stopped.

## Out of scope for the first version

Word-by-word text streaming, voice, multiple users, story export, mobile adaptation beyond the basics. (Scene illustrations were added later and are described above.)
