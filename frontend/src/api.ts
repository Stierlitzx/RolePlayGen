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
  narration: string;
  choice: Choice | null;
  state: TurnState;
  is_ending: boolean;
  image_status: ImageStatus;
  image_format: ImageFormat | null;
  image_url: string | null;
  image_error: string | null;
  created_at: string;
}

export interface TurnImageInfo {
  status: ImageStatus;
  format: ImageFormat | null;
  url: string | null;
  error: string | null;
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
}

export interface StoryCreate {
  setting: string;
  custom_setting: string | null;
  genres: string[];
  tone: string;
  hero_role: string | null;
  hero_name: string | null;
  hero_appearance: string | null;
  length: Length;
  custom_turns: number | null;
  model: string | null;
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
  portrait_status: ImageStatus;
  portrait_url: string | null;
  portrait_error: string | null;
  created_at: string;
}

export type TurnCreate = { option_id: ChoiceOption['id'] } | { custom_text: string };

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
  turnImage: (turnId: number) => request<TurnImageInfo>(`/turns/${turnId}/image`, undefined, POLL_TIMEOUT_MS),
  retryTurnImage: (turnId: number) =>
    request<TurnImageInfo>(`/turns/${turnId}/image/retry`, { method: 'POST' }),
  characters: (storyId: number) =>
    request<CharacterInfo[]>(`/stories/${storyId}/characters`, undefined, POLL_TIMEOUT_MS),
  character: (characterId: number) =>
    request<CharacterInfo>(`/characters/${characterId}`, undefined, POLL_TIMEOUT_MS),
  retryCharacterPortrait: (characterId: number) =>
    request<CharacterInfo>(`/characters/${characterId}/portrait/retry`, { method: 'POST' }),
  deleteStory: (id: number) => request<void>(`/stories/${id}`, { method: 'DELETE' }),
};
