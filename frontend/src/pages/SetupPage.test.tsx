import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SetupOptions, Story } from '../api';
import SetupPage from './SetupPage';

const OPTIONS: SetupOptions = {
  settings: ['Medieval kingdom', 'Cyberpunk city', 'Custom'],
  genres: ['Fantasy', 'Sci-fi', 'Random'],
  tones: ['Dark', 'Light'],
  lengths: [
    { value: 'short', label: 'Short (20 turns)' },
    { value: 'medium', label: 'Medium (50 turns)' },
    { value: 'long', label: 'Long (100 turns)' },
    { value: 'custom', label: 'Custom' },
  ],
  languages: ['Russian', 'English', 'Kazakh'],
  cultures: ['Match story language', 'Western European'],
  max_genres: 2,
  age_ratings: ['0+', '12+', '16+', '18+'],
  adult_genres: ['Hentai'],
  image_styles: ['Painterly', 'Anime'],
  narrator_styles: ['Classic narrator', 'Snarky narrator'],
  default_age_rating: '16+',
  default_image_style: 'Painterly',
  default_narrator_style: 'Classic narrator',
  models: ['gemini-2.0-flash'],
  default_model: 'gemini-2.0-flash',
  ai_configured: true,
  mock_llm: true,
  default_provider: 'gemini',
  gemini_models: ['gemini-2.0-flash'],
  default_gemini_model: 'gemini-2.0-flash',
  gemini_configured: true,
  local_model: null,
  local_configured: false,
  groq_model: null,
  groq_configured: false,
  openrouter_model: null,
  openrouter_configured: false,
  mistral_model: null,
  mistral_configured: false,
  hero_genders: ['Male', 'Female'],
  default_hero_gender: 'Male',
};

function makeStory(overrides: Partial<Story> = {}): Story {
  return {
    id: 7,
    title: 'Ash over the marshes',
    settings: {},
    status: 'active',
    max_turns: 20,
    created_at: '2026-09-21T00:00:00Z',
    updated_at: '2026-09-21T00:00:00Z',
    turns: [],
    pinned_facts: [],
    ...overrides,
  };
}

function okResponse(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload };
}

/** Fetch stub that serves setup options first and then the given responses. */
function stubFetch(...responses: unknown[]) {
  const fetchMock = vi.fn().mockResolvedValueOnce(okResponse(OPTIONS));
  for (const payload of responses) {
    fetchMock.mockResolvedValueOnce(okResponse(payload));
  }
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function lastRequestBody(fetchMock: ReturnType<typeof vi.fn>) {
  const [, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
  return JSON.parse(String(init.body)) as Record<string, unknown>;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('SetupPage', () => {
  it('renders the sectioned form once the options are loaded', async () => {
    stubFetch();
    render(<SetupPage onBack={() => {}} onStarted={() => {}} />);

    expect(await screen.findByText('Choose the world')).toBeInTheDocument();
    for (const section of ['World', 'Hero', 'Language & culture', 'Narration & model', 'Content rating']) {
      expect(screen.getByText(section)).toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: 'Start' })).toBeEnabled();
  });

  it('creates a story with the filled-in payload on Start', async () => {
    const story = makeStory();
    const fetchMock = stubFetch(story);
    const onStarted = vi.fn();
    const { container } = render(<SetupPage onBack={() => {}} onStarted={onStarted} />);

    await screen.findByRole('button', { name: 'Start' });
    fireEvent.change(screen.getByLabelText(/Hero name/), { target: { value: 'Ayla' } });
    fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(onStarted).toHaveBeenCalledWith(story));
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/stories',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(lastRequestBody(fetchMock)).toMatchObject({
      setting: 'Medieval kingdom',
      genres: ['Fantasy'],
      tone: 'Dark',
      hero_name: 'Ayla',
      llm_provider: 'gemini',
      model: 'gemini-2.0-flash',
      age_rating: '16+',
      narrator_style: 'Classic narrator',
    });
  });

  it('keeps at most max_genres genre pills selected', async () => {
    stubFetch();
    const { container } = render(<SetupPage onBack={() => {}} onStarted={() => {}} />);
    await screen.findByRole('button', { name: 'Start' });

    fireEvent.click(screen.getByRole('button', { name: 'Sci-fi' }));
    fireEvent.click(screen.getByRole('button', { name: 'Random' }));
    // Fantasy (the default) + Sci-fi + Random exceeds the cap of 2,
    // so the oldest selection is dropped.

    expect(container.querySelectorAll('.pill.selected')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Fantasy' })).not.toHaveClass('selected');
    expect(screen.getByRole('button', { name: 'Sci-fi' })).toHaveClass('selected');
  });

  it('saves an existing story with PATCH in edit mode', async () => {
    const editing = makeStory({
      settings: {
        setting: 'Cyberpunk city',
        genres: ['Sci-fi'],
        tone: 'Light',
        length: 'short',
        language: 'English',
        narrator_style: 'Snarky narrator',
      },
    });
    const fetchMock = stubFetch(editing);
    const { container } = render(
      <SetupPage onBack={() => {}} onStarted={() => {}} editingStory={editing} />,
    );

    expect(await screen.findByText('Edit the beginning')).toBeInTheDocument();
    fireEvent.submit(container.querySelector('form')!);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        '/api/stories/7',
        expect.objectContaining({ method: 'PATCH' }),
      ),
    );
    expect(lastRequestBody(fetchMock)).toMatchObject({
      setting: 'Cyberpunk city',
      genres: ['Sci-fi'],
      tone: 'Light',
    });
  });
});
