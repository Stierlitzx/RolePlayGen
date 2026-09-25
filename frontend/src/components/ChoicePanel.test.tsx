import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Choice } from '../api';
import ChoicePanel from './ChoicePanel';

const CHOICE: Choice = {
  mode: 'open',
  options: [
    { id: 'a', text: 'Charge in' },
    { id: 'b', text: 'Sneak around' },
  ],
  allow_custom: true,
  prompt: 'What will you do?',
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('ChoicePanel', () => {
  /** The panel starts collapsed (player request), so every test that needs the
   *  options first opens it with the "Show choices" button. */
  function renderExpanded(onSubmit = vi.fn()) {
    render(<ChoicePanel choice={CHOICE} disabled={false} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole('button', { name: 'Show choices ▴' }));
    return onSubmit;
  }

  it('starts collapsed so it does not cover the feed', () => {
    render(<ChoicePanel choice={CHOICE} disabled={false} onSubmit={vi.fn()} />);
    // Only the slim bar with the prompt and the expander.
    expect(screen.queryByRole('button', { name: /Charge in/ })).not.toBeInTheDocument();
    expect(screen.getByText('What will you do?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show choices ▴' })).toBeInTheDocument();
  });

  it('submits the clicked option', () => {
    const onSubmit = renderExpanded();
    fireEvent.click(screen.getByRole('button', { name: /Charge in/ }));
    expect(onSubmit).toHaveBeenCalledWith({ option_id: 'a' });
  });

  it('collapses to a slim bar and expands back', () => {
    render(<ChoicePanel choice={CHOICE} disabled={false} onSubmit={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Show choices ▴' }));

    fireEvent.click(screen.getByRole('button', { name: 'Hide ▾' }));
    expect(screen.queryByRole('button', { name: /Charge in/ })).not.toBeInTheDocument();
    expect(screen.getByText('What will you do?')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Show choices ▴' }));
    expect(screen.getByRole('button', { name: /Charge in/ })).toBeInTheDocument();
  });

  it('collapses again when the next turn arrives', () => {
    const { rerender } = render(
      <ChoicePanel choice={CHOICE} disabled={false} onSubmit={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Show choices ▴' }));
    expect(screen.getByRole('button', { name: /Charge in/ })).toBeInTheDocument();

    rerender(
      <ChoicePanel
        choice={{ ...CHOICE, prompt: 'What next?' }}
        disabled={false}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.queryByRole('button', { name: /Charge in/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show choices ▴' })).toBeInTheDocument();
  });

  it('submits a custom action from the input bar', () => {
    const onSubmit = renderExpanded();
    fireEvent.change(screen.getByPlaceholderText('What do you do?'), {
      target: { value: 'Wave at the guards' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(onSubmit).toHaveBeenCalledWith({ custom_text: 'Wave at the guards' });
  });

  it('sends the narrator note together with an option pick', () => {
    const onSubmit = renderExpanded();
    fireEvent.change(screen.getByLabelText('Note to the narrator (optional)'), {
      target: { value: '  my character has no lighter  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Charge in/ }));
    expect(onSubmit).toHaveBeenCalledWith({
      option_id: 'a',
      note_text: 'my character has no lighter',
    });
  });

  it('sends the narrator note together with a custom action', () => {
    const onSubmit = renderExpanded();
    fireEvent.change(screen.getByPlaceholderText('What do you do?'), {
      target: { value: 'Wave at the guards' },
    });
    fireEvent.change(screen.getByLabelText('Note to the narrator (optional)'), {
      target: { value: 'bandits ambush me ahead' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(onSubmit).toHaveBeenCalledWith({
      custom_text: 'Wave at the guards',
      note_text: 'bandits ambush me ahead',
    });
  });

  it('omits an empty note entirely', () => {
    const onSubmit = renderExpanded();
    fireEvent.click(screen.getByRole('button', { name: /Charge in/ }));
    expect(onSubmit).toHaveBeenCalledWith({ option_id: 'a' });
  });

  it('shows the character counter only near the limit', () => {
    renderExpanded();
    const note = screen.getByLabelText('Note to the narrator (optional)');
    fireEvent.change(note, { target: { value: 'short note' } });
    expect(screen.queryByText(/\/2000/)).not.toBeInTheDocument();
    fireEvent.change(note, { target: { value: 'x'.repeat(1801) } });
    expect(screen.getByText('1801/2000')).toBeInTheDocument();
  });

  it('limits the note to 2000 characters', () => {
    renderExpanded();
    const note = screen.getByLabelText('Note to the narrator (optional)');
    expect(note).toHaveAttribute('maxLength', '2000');
  });

  it('clears the note when a new choice arrives (after a successful submit)', () => {
    const { rerender } = render(
      <ChoicePanel choice={CHOICE} disabled={false} onSubmit={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Show choices ▴' }));
    const note = screen.getByLabelText('Note to the narrator (optional)');
    fireEvent.change(note, { target: { value: 'a note' } });
    rerender(
      <ChoicePanel
        choice={{ ...CHOICE, prompt: 'What next?' }}
        disabled={false}
        onSubmit={vi.fn()}
      />,
    );
    // The new turn is collapsed again, so the note field is re-mounted empty.
    expect(screen.getByRole('button', { name: 'Show choices ▴' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show choices ▴' }));
    expect(screen.getByLabelText('Note to the narrator (optional)')).toHaveValue('');
  });
});
