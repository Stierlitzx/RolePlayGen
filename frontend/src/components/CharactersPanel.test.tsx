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
    portrait_build_log: null,
    portrait_progress: null,
    photo_url: null,
    portrait_history: [],
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

  it('keeps the last known list when a reload fails', async () => {
    // A hung backend used to blank the panel, which looked exactly like "my
    // characters are gone". The list must survive the error.
    const characters = [makeCharacter({ name: 'Tom' })];
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(okResponse(characters))
      .mockRejectedValue(new Error('The server is not responding.'));
    vi.stubGlobal('fetch', fetchMock);

    const { rerender } = render(<CharactersPanel storyId={1} refreshKey={0} />);
    expect(await screen.findByText('Tom')).toBeInTheDocument();

    // The parent bumps refreshKey -> a reload that fails.
    rerender(<CharactersPanel storyId={1} refreshKey={1} />);
    expect(await screen.findByText(/showing the last known list/i)).toBeInTheDocument();
    expect(screen.getByText('Tom')).toBeInTheDocument();
  });

  it('uploads the player’s own picture for a character', async () => {
    const character = makeCharacter({});
    const uploaded = makeCharacter({
      photo_url: '/media/1/photo_1.png',
      portrait_url: '/media/1/photo_1.png',
      portrait_status: 'done',
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(okResponse([character]))
      .mockResolvedValueOnce(okResponse(uploaded));
    vi.stubGlobal('fetch', fetchMock);
    // jsdom has no FileReader data for real files; stand in for the read step.
    const readAsDataURL = vi
      .spyOn(FileReader.prototype, 'readAsDataURL')
      .mockImplementation(function (this: FileReader) {
        this.onload?.({ target: this } as ProgressEvent<FileReader>);
      });
    Object.defineProperty(FileReader.prototype, 'result', {
      configurable: true,
      get: () => 'data:image/png;base64,aGVsbG8=',
    });

    render(<CharactersPanel storyId={1} />);
    fireEvent.click(await screen.findByRole('button', { name: /Kaelen/ }));
    const input = await screen.findByLabelText(/Use your own picture/);
    const file = new File(['x'], 'kaelen.png', { type: 'image/png' });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() =>
      expect(
        screen.getAllByAltText('Portrait of Kaelen').some(
          (node) => node.getAttribute('src') === '/media/1/photo_1.png',
        ),
      ).toBe(true),
    );
    const uploadCall = fetchMock.mock.calls.find(([, options]) =>
      String((options as RequestInit).method ?? '') === 'POST',
    );
    expect(uploadCall).toBeTruthy();
    expect(String((uploadCall?.[1] as RequestInit).body)).toContain('data:image/png;base64');
    readAsDataURL.mockRestore();
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

  it('shows the portrait history gallery in the detail view', async () => {
    stubListFetch([
      makeCharacter({
        portrait_status: 'done',
        portrait_url: '/media/1/char_1.png',
        portrait_history: [
          { turn_id: 1, portrait_url: '/media/1/char_1.png', current: false },
          { turn_id: 7, portrait_url: '/media/1/char_1_v2.png', current: true },
        ],
      }),
    ]);
    render(<CharactersPanel storyId={1} />);
    fireEvent.click(await screen.findByRole('button', { name: /Kaelen/ }));

    expect(await screen.findByText('Past looks')).toBeInTheDocument();
    expect(screen.getByAltText('Kaelen — look 1')).toHaveAttribute('src', '/media/1/char_1.png');
    expect(screen.getByAltText('Kaelen — look 2')).toHaveAttribute('src', '/media/1/char_1_v2.png');
    expect(screen.getByText(/turn 7 · current/)).toBeInTheDocument();
  });

  it('hides the gallery when there is only one look', async () => {
    stubListFetch([
      makeCharacter({
        portrait_status: 'done',
        portrait_url: '/media/1/char_1.png',
        portrait_history: [{ turn_id: 1, portrait_url: '/media/1/char_1.png', current: true }],
      }),
    ]);
    render(<CharactersPanel storyId={1} />);
    fireEvent.click(await screen.findByRole('button', { name: /Kaelen/ }));
    await screen.findByRole('dialog');
    expect(screen.queryByText('Past looks')).not.toBeInTheDocument();
  });
});
