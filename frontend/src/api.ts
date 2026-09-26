export type ChoiceMode = 'open' | 'locked' | 'binary';
export type StoryStatus = 'active' | 'finished';
export type Length = 'short' | 'medium' | 'long' | 'custom';
export type Language = 'Russian' | 'English' | 'Kazakh';

export interface ChoiceOption {
  id: 'a' | 'b' | 'c' | 'd';
  text: string;
}

export interface Choice {
  mode: ChoiceMode;
  options: ChoiceOption[];
  allow_custom: boolean;
  prompt: string;
}

export interface TurnState {
  scene: string;
  summary: string;
  facts: string[];
}

export type ImageStatus = 'none' | 'queued' | 'generating' | 'done' | 'failed';
export type ImageFormat = 'portrait' | 'wide';

export interface Turn {
  id: number;
  story_id: number;
  index: number;
  player_input_type: 'option' | 'custom' | 'start';
  player_input_text: string | null;
  note_text: string | null;
  note_type: 'fact' | 'event' | null;
  narration: string;
  choice: Choice | null;
  state: TurnState;
  is_ending: boolean;
  image_status: ImageStatus;
  image_format: ImageFormat | null;
  /** The narrator's own scene text for this picture. */
  image_prompt?: string | null;
  /** The player's own wording, when set; the picture uses this instead. */
  image_prompt_override?: string | null;
  image_url: string | null;
  image_error: string | null;
  /** What was sent to the picture model for this turn (mode, steps, prompt). */
  image_build_log: string | null;
  /** Sampler progress of the running picture, 0-100. */
  image_progress: number | null;
  created_at: string;
}

export interface TurnImageInfo {
  status: ImageStatus;
  format: ImageFormat | null;
  url: string | null;
  error: string | null;
  /** Sampler progress of the running job, 0-100 (null when not known). */
  progress: number | null;
}

export interface Story {
  id: number;
  title: string;
  settings: Record<string, unknown>;
  status: StoryStatus;
  max_turns: number | null;
  created_at: string;
  updated_at: string;
  turns: Turn[];
  pinned_facts: string[];
}

export interface StorySummary extends Omit<Story, 'turns'> {
  turn_count: number;
}

export interface SetupOptions {
  settings: string[];
  genres: string[];
  tones: string[];
  lengths: Array<{ value: Length; label: string }>;
  languages: Language[];
  cultures: string[];
  max_genres: number;
  age_ratings: string[];
  adult_genres: string[];
  image_styles: string[];
  narrator_styles: string[];
  default_age_rating: string;
  default_image_style: string;
  default_narrator_style: string;
  models: string[];
  default_model: string;
  ai_configured: boolean;
  mock_llm: boolean;
  default_provider: 'gemini' | 'local' | 'groq' | 'openrouter' | 'mistral';
  gemini_models: string[];
  default_gemini_model: string;
  gemini_configured: boolean;
  local_model: string | null;
  local_configured: boolean;
  groq_model: string | null;
  groq_configured: boolean;
  openrouter_model: string | null;
  openrouter_configured: boolean;
  mistral_model: string | null;
  mistral_configured: boolean;
  hero_genders: string[];
  default_hero_gender: string;
}

export interface StoryCreate {
  setting: string;
  custom_setting: string | null;
  genres: string[];
  tone: string;
  hero_role: string | null;
  hero_name: string | null;
  hero_appearance: string | null;
  hero_gender: string | null;
  length: Length;
  custom_turns: number | null;
  model: string | null;
  llm_provider: 'gemini' | 'local' | 'groq' | 'openrouter' | 'mistral' | null;
  content_restrictions: string | null;
  language: Language;
  custom_details: string | null;
  setting_culture: string | null;
  naming_culture: string | null;
  intro_exposition: boolean;
  age_rating: string | null;
  explicit_sexual: boolean;
  graphic_violence: boolean;
  image_style: string | null;
  narrator_style: string | null;
  /** Optional player photo of the hero, as a data URL. */
  hero_image?: string | null;
}

export interface PortraitVersion {
  turn_id: number | null;
  portrait_url: string | null;
  current: boolean;
}

export interface CharacterInfo {
  id: number;
  story_id: number;
  name: string;
  is_hero: boolean;
  role: string | null;
  relationship: string | null;
  description: string | null;
  first_seen_turn_id: number | null;
  /** The character's look, editable in the Characters tab. */
  appearance_tags?: string | null;
  portrait_status: ImageStatus;
  portrait_url: string | null;
  portrait_error: string | null;
  /** The picture the player uploaded for this character, if any. */
  photo_url: string | null;
  /** What was sent to the picture model for the last portrait. */
  portrait_build_log: string | null;
  /** Sampler progress of the running portrait job, 0-100. */
  portrait_progress: number | null;
  portrait_history: PortraitVersion[];
  created_at: string;
}

// The optional note goes with either an option pick or a custom action; it is
// omitted entirely when the field is empty (an empty note changes nothing).
export type TurnCreate =
  | { option_id: ChoiceOption['id']; note_text?: string }
  | { custom_text: string; note_text?: string };

const DEFAULT_TIMEOUT_MS = 60_000;
const POLL_TIMEOUT_MS = 12_000;
const LLM_TIMEOUT_MS = 300_000; // story/turn generation waits on the model synchronously

async function request<T>(path: string, init?: RequestInit, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      headers: { 'Content-Type': 'application/json', ...init?.headers },
      ...init,
      signal: init?.signal ?? AbortSignal.timeout(timeoutMs),
    });
  } catch (err) {
    if (err instanceof DOMException && (err.name === 'TimeoutError' || err.name === 'AbortError')) {
      throw new Error('The server is not responding. Check that the backend is running.');
    }
    if (err instanceof TypeError) {
      throw new Error('Cannot reach the server. Check that the backend is running.');
    }
    throw err;
  }
  if (!response.ok) {
    let message = 'Something went wrong. Please try again.';
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Keep the plain-language fallback.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string }>('/health'),
  setupOptions: () => request<SetupOptions>('/setup-options'),
  stories: () => request<StorySummary[]>('/stories'),
  story: (id: number) => request<Story>(`/stories/${id}`),
  createStory: (payload: StoryCreate) =>
    request<Story>('/stories', { method: 'POST', body: JSON.stringify(payload) }, LLM_TIMEOUT_MS),
  createTurn: (storyId: number, payload: TurnCreate) =>
    request<Turn>(`/stories/${storyId}/turns`, { method: 'POST', body: JSON.stringify(payload) }, LLM_TIMEOUT_MS),
  updateStory: (id: number, payload: StoryCreate) =>
    request<Story>(`/stories/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }, LLM_TIMEOUT_MS),
  regenerateStart: (id: number) =>
    request<Story>(`/stories/${id}/regenerate-start`, { method: 'POST' }, LLM_TIMEOUT_MS),
  regenerateLast: (id: number) =>
    request<Story>(`/stories/${id}/regenerate-last`, { method: 'POST' }, LLM_TIMEOUT_MS),
  turnImage: (turnId: number) =>
    request<TurnImageInfo>(`/turns/${turnId}/image`, undefined, POLL_TIMEOUT_MS),
  /** Repaint a finished picture with the current prompt/style (new seed, new log). */
  redoTurnImage: (turnId: number) =>
    request<TurnImageInfo>(`/turns/${turnId}/image/redo`, { method: 'POST' }),
  retryTurnImage: (turnId: number) =>
    request<TurnImageInfo>(`/turns/${turnId}/image/retry`, { method: 'POST' }),
  /** Re-aim a picture with the player's own scene wording and repaint it. An
   *  empty prompt clears the override and goes back to the narrator's own. */
  updateTurnImagePrompt: (turnId: number, prompt: string) =>
    request<TurnImageInfo>(`/turns/${turnId}/image/prompt`, {
      method: 'PATCH',
      body: JSON.stringify({ prompt }),
    }, LLM_TIMEOUT_MS),
  characters: (storyId: number) =>
    request<CharacterInfo[]>(`/stories/${storyId}/characters`, undefined, POLL_TIMEOUT_MS),
  character: (characterId: number) =>
    request<CharacterInfo>(`/characters/${characterId}`, undefined, POLL_TIMEOUT_MS),
  /** Repaint a finished portrait with the current prompt/style. */
  redoCharacterPortrait: (characterId: number) =>
    request<CharacterInfo>(`/characters/${characterId}/portrait/redo`, { method: 'POST' }),
  /** Hand the generator the player's own picture of a character (Characters tab). */
  uploadCharacterPhoto: (characterId: number, image: string, useAsPortrait = true) =>
    request<CharacterInfo>(`/characters/${characterId}/portrait`, {
      method: 'POST',
      body: JSON.stringify({ image, use_as_portrait: useAsPortrait }),
    }),
  retryCharacterPortrait: (characterId: number) =>
    request<CharacterInfo>(`/characters/${characterId}/portrait/retry`, { method: 'POST' }),
  /** Rewrite a character's look by hand and repaint the card. */
  updateCharacterLook: (
    characterId: number,
    appearanceTags: string,
    options: { keepHistory?: boolean; repaint?: boolean } = {},
  ) =>
    request<CharacterInfo>(`/characters/${characterId}/look`, {
      method: 'PATCH',
      body: JSON.stringify({
        appearance_tags: appearanceTags,
        keep_history: options.keepHistory ?? true,
        repaint: options.repaint ?? true,
      }),
    }, LLM_TIMEOUT_MS),
  deletePinnedFact: (storyId: number, index: number) =>
    request<{ pinned_facts: string[] }>(`/stories/${storyId}/pinned-facts/${index}`, { method: 'DELETE' }),
  deleteStory: (id: number) => request<void>(`/stories/${id}`, { method: 'DELETE' }),
};
