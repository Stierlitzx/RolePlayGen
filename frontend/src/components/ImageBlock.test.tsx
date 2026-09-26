import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, type ImageStatus, type Turn } from '../api';
import ImageBlock from './ImageBlock';

function makeTurn(overrides: Partial<Turn>): Turn {
  return {
    id: 1,
    story_id: 1,
    index: 0,
    player_input_type: 'start',
    player_input_text: null,
    note_text: null,
    note_type: null,
    narration: 'Some narration.',
    choice: null,
    state: { scene: 'Scene', summary: 'Summary', facts: [] },
    is_ending: false,
    image_status: 'none',
    image_format: 'wide',
    image_url: null,
    image_error: null,
    image_build_log: null,
    image_progress: null,
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

  it('lets the player re-aim a picture with their own prompt', async () => {
    // Another seed cannot fix the wrong person in the frame or a crop that cuts
    // the point off, and the narrator is not there to ask — so the scene sentence
    // itself is editable, and the picture is regenerated from it.
    const update = vi.fn().mockResolvedValue({ status: 'queued' });
    vi.spyOn(api, 'updateTurnImagePrompt').mockImplementation(update);
    render(
      <ImageBlock
        turn={makeTurn({
          image_status: 'done',
          image_url: '/media/1/1.png',
          image_prompt: 'A woman standing in a field at dusk, medium shot',
        })}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Change the picture/ }));
    const box = screen.getByLabelText('What should be in this picture');
    // The editor opens on the text that produced the current picture.
    expect(box).toHaveValue('A woman standing in a field at dusk, medium shot');
    fireEvent.change(box, { target: { value: 'The same woman kneeling in the barley' } });
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate with this' }));
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(1, 'The same woman kneeling in the barley'),
    );
  });

  it('offers the narrator wording back when an override is set', () => {
    // The way out when an edit made the picture worse.
    const update = vi.fn().mockResolvedValue({ status: 'queued' });
    vi.spyOn(api, 'updateTurnImagePrompt').mockImplementation(update);
    render(
      <ImageBlock
        turn={makeTurn({
          image_status: 'done',
          image_url: '/media/1/1.png',
          image_prompt: 'A woman standing in a field',
          image_prompt_override: 'Something else',
        })}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Change the picture/ }));
    // Opening the editor shows the override, not the narrator's text.
    expect(screen.getByLabelText('What should be in this picture')).toHaveValue('Something else');
    fireEvent.click(screen.getByRole('button', { name: /narrator's own words/ }));
    // An empty prompt clears the override.
    expect(update).toHaveBeenCalledWith(1, '');
  });

  it('has no prompt editor when the turn has no scene text', () => {
    render(
      <ImageBlock
        turn={makeTurn({ image_status: 'done', image_url: '/media/1/1.png' })}
      />,
    );
    expect(screen.queryByRole('button', { name: /Change the picture/ })).not.toBeInTheDocument();
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

  it('opens the image in the fullscreen lightbox when done', () => {
    render(
      <ImageBlock
        turn={makeTurn({ image_status: 'done', image_url: '/media/1/1.png', image_format: 'wide' })}
      />,
    );
    const img = screen.getByAltText('Scene illustration');
    expect(img).toHaveAttribute('src', '/media/1/1.png');
    expect(img.closest('a')).toBeNull(); // no more raw-file new tab

    fireEvent.click(img);
    const dialog = screen.getByRole('dialog', { name: 'Scene illustration' });
    expect(within(dialog).getByAltText('Scene illustration')).toHaveAttribute('src', '/media/1/1.png');

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
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
