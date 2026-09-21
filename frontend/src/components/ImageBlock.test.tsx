import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ImageStatus, Turn } from '../api';
import ImageBlock from './ImageBlock';

function makeTurn(overrides: Partial<Turn>): Turn {
  return {
    id: 1,
    story_id: 1,
    index: 0,
    player_input_type: 'start',
    player_input_text: null,
    narration: 'Some narration.',
    choice: null,
    state: { scene: 'Scene', summary: 'Summary', facts: [] },
    is_ending: false,
    image_status: 'none',
    image_format: 'wide',
    image_url: null,
    image_error: null,
    created_at: '2026-09-21T00:00:00Z',
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('ImageBlock', () => {
  it('renders nothing when the turn has no image', () => {
    const { container } = render(<ImageBlock turn={makeTurn({ image_status: 'none' })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each<ImageStatus>(['queued', 'generating'])(
    'shows a loading placeholder while %s',
    (status) => {
      render(<ImageBlock turn={makeTurn({ image_status: status })} />);
      expect(screen.getByText(/Drawing the scene/)).toBeInTheDocument();
    },
  );

  it('reserves a portrait aspect ratio placeholder for portrait images', () => {
    const { container } = render(
      <ImageBlock turn={makeTurn({ image_status: 'queued', image_format: 'portrait' })} />,
    );
    const placeholder = container.querySelector('.image-loading');
    expect(placeholder).toHaveStyle({ aspectRatio: '4 / 5' });
  });

  it('shows the image with a full-size link when done', () => {
    render(
      <ImageBlock
        turn={makeTurn({ image_status: 'done', image_url: '/media/1/1.png', image_format: 'wide' })}
      />,
    );
    const img = screen.getByAltText('Scene illustration');
    expect(img).toHaveAttribute('src', '/media/1/1.png');
    expect(img.closest('a')).toHaveAttribute('href', '/media/1/1.png');
    expect(img.closest('a')).toHaveAttribute('target', '_blank');
  });

  it('shows the failure reason and a Retry button when failed', () => {
    render(
      <ImageBlock
        turn={makeTurn({ image_status: 'failed', image_error: 'Image generator is not running' })}
      />,
    );
    expect(screen.getByText(/Image generator is not running/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('calls the retry endpoint and returns to the loading state', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'queued', format: 'wide', url: null, error: null }),
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<ImageBlock turn={makeTurn({ image_status: 'failed', image_error: 'boom' })} />);

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/turns/1/image/retry',
        expect.objectContaining({ method: 'POST' }),
      ),
    );
    expect(await screen.findByText(/Drawing the scene/)).toBeInTheDocument();
  });
});
