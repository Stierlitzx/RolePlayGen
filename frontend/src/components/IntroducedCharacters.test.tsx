import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CharacterInfo } from '../api';
import IntroducedCharacters from './IntroducedCharacters';

function makeCharacter(overrides: Partial<CharacterInfo>): CharacterInfo {
  return {
    id: 1,
    story_id: 1,
    name: 'Kaelen',
    is_hero: false,
    role: 'sky pirate captain',
    relationship: 'reluctant ally',
    description: 'Sharp-tongued captain.',
    first_seen_turn_id: 3,
    portrait_status: 'none',
    portrait_url: null,
    portrait_error: null,
    created_at: '2026-09-21T00:00:00Z',
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('IntroducedCharacters', () => {
  it('renders nothing when no characters were introduced on the turn', () => {
    const { container } = render(<IntroducedCharacters characters={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the portrait, name and role when the portrait is done', () => {
    render(
      <IntroducedCharacters
        characters={[makeCharacter({ portrait_status: 'done', portrait_url: '/media/1/char_1.png' })]}
      />,
    );
    const img = screen.getByAltText('Portrait of Kaelen');
    expect(img).toHaveAttribute('src', '/media/1/char_1.png');
    expect(img.closest('a')).toBeNull(); // opens in the lightbox, not a new tab
    fireEvent.click(img);
    expect(screen.getByRole('dialog', { name: 'Portrait of Kaelen' })).toBeInTheDocument();
    expect(screen.getByText('Kaelen')).toBeInTheDocument();
    expect(screen.getByText(/sky pirate captain/)).toBeInTheDocument();
  });

  it('shows a loading placeholder while the portrait is queued or generating', () => {
    render(<IntroducedCharacters characters={[makeCharacter({ portrait_status: 'generating' })]} />);
    expect(screen.getByText('Drawing…')).toBeInTheDocument();
  });

  it('offers a retry for a failed portrait and reports the update', async () => {
    const failed = makeCharacter({ id: 7, portrait_status: 'failed' });
    const retried = { ...failed, portrait_status: 'queued' as const };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => retried,
    });
    vi.stubGlobal('fetch', fetchMock);
    const onUpdated = vi.fn();

    render(<IntroducedCharacters characters={[failed]} onUpdated={onUpdated} />);
    fireEvent.click(screen.getByRole('button', { name: 'Retry portrait' }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/characters/7/portrait/retry',
        expect.objectContaining({ method: 'POST' }),
      ),
    );
    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(retried));
  });

  it('marks the hero with a you badge', () => {
    render(<IntroducedCharacters characters={[makeCharacter({ is_hero: true, name: 'Ayla' })]} />);
    expect(screen.getByText('you')).toBeInTheDocument();
  });
});
