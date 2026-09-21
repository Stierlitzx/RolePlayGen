import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import ZoomableImage from './Lightbox';

afterEach(cleanup);

describe('ZoomableImage / Lightbox', () => {
  it('opens the overlay on click and closes on Esc', () => {
    render(<ZoomableImage src="/media/1/1.png" alt="Scene illustration" />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    fireEvent.click(screen.getByAltText('Scene illustration'));
    expect(screen.getByRole('dialog', { name: 'Scene illustration' })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('toggles between fit-to-screen and actual size when the opened image is clicked', () => {
    render(<ZoomableImage src="/media/1/1.png" alt="Scene illustration" />);
    fireEvent.click(screen.getByAltText('Scene illustration'));

    const dialog = screen.getByRole('dialog');
    const fullImage = dialog.querySelector('.lightbox-image')!;
    expect(fullImage).not.toHaveClass('zoomed');

    fireEvent.click(fullImage);
    expect(dialog.querySelector('.lightbox-image')).toHaveClass('zoomed');

    fireEvent.click(dialog.querySelector('.lightbox-image')!);
    expect(dialog.querySelector('.lightbox-image')).not.toHaveClass('zoomed');
  });

  it('closes via the backdrop and the close button', () => {
    render(<ZoomableImage src="/media/1/1.png" alt="Scene illustration" />);

    fireEvent.click(screen.getByAltText('Scene illustration'));
    fireEvent.click(screen.getByRole('dialog')); // backdrop
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    fireEvent.click(screen.getByAltText('Scene illustration'));
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
