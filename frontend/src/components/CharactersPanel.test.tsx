import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CharacterInfo } from '../api';
import CharactersPanel from './CharactersPanel';

function makeCharacter(overrides: Partial<CharacterInfo>): CharacterInfo {
  return {
    id: 1,
    story_id: 1,
    name: 'Kaelen',
    is_hero: false,
    role: 'sky pirate captain',
    relationship: 'reluctant ally',
    description: 'Sharp-tongued captain of the airship Halcyon.',
    first_seen_turn_id: null,
    portrait_status: 'none',
    portrait_url: null,
    portrait_error: null,
    created_at: '2026-09-21T00:00:00Z',
    ...overrides,
  };
}

function okResponse(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload };
}

function stubListFetch(list: CharacterInfo[]) {
  const fetchMock = vi.fn().mockResolvedValue(okResponse(list));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('CharactersPanel', () => {
  it('shows an empty-state note when the story has no characters yet', async () => {
    stubListFetch([]);
    render(<CharactersPanel storyId={1} />);
    expect(await screen.findByText(/No characters met yet/)).toBeInTheDocument();
  });

  it('shows a loading placeholder while a portrait is queued', async () => {
    stubListFetch([makeCharacter({ portrait_status: 'queued' })]);
    render(<CharactersPanel storyId={1} />);
    expect(await screen.findByText('Drawing…')).toBeInTheDocument();
  });

  it('shows the portrait and hero badge when the portrait is done', async () => {
    stubListFetch([
      makeCharacter({
        is_hero: true,
        name: 'Ayla',
        portrait_status: 'done',
        portrait_url: '/media/portraits/1.png',
      }),
    ]);
    render(<CharactersPanel storyId={1} />);
    const img = await screen.findByAltText('Portrait of Ayla');
    expect(img).toHaveAttribute('src', '/media/portraits/1.png');
    expect(screen.getByText('you')).toBeInTheDocument();
  });

  it('retries a failed portrait from the detail view', async () => {
    const failed = makeCharacter({
      id: 5,
      portrait_status: 'failed',
      portrait_error: 'Image generator is not running',
    });
    const retried = { ...failed, portrait_status: 'queued', portrait_error: null };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(okResponse([failed])) // initial list
      .mockResolvedValueOnce(okResponse(retried)); // retry POST
    vi.stubGlobal('fetch', fetchMock);

    render(<CharactersPanel storyId={1} />);
    fireEvent.click(await screen.findByRole('button', { name: /Kaelen/ }));
    expect(await screen.findByText(/Image generator is not running/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/characters/5/portrait/retry',
        expect.objectContaining({ method: 'POST' }),
      ),
    );
  });

  it('does not offer a retry button for a finished portrait', async () => {
    stubListFetch([
      makeCharacter({ portrait_status: 'done', portrait_url: '/media/portraits/1.png' }),
    ]);
    render(<CharactersPanel storyId={1} />);
    fireEvent.click(await screen.findByRole('button', { name: /Kaelen/ }));
    await screen.findByRole('dialog');
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });
});
