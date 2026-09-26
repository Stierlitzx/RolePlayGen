import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
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
  // The panel debounces its sessionStorage write, so a key left by one test can
  // be rewritten by the previous component's timer after cleanup and confuse the
  // next one. Each draft test also asserts on its own key.
  sessionStorage.clear();
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

  it('keeps the custom-action field even when the turn says allow_custom is off', () => {
    // A locked/binary turn used to hide this input, leaving the player able to
    // play only by picking one of the narrator's options. Whatever the flag says,
    // writing your own action is the player's.
    const onSubmit = vi.fn();
    render(
      <ChoicePanel
        choice={{ ...CHOICE, mode: 'binary', allow_custom: false }}
        disabled={false}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Show choices ▴' }));

    const input = screen.getByPlaceholderText('What do you do?');
    fireEvent.change(input, { target: { value: 'Say something else entirely' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(onSubmit).toHaveBeenCalledWith({ custom_text: 'Say something else entirely' });
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

  it('keeps the typed action and the note when the submit fails', async () => {
    // The turn is unchanged after a failure, so the paragraph the player already
    // wrote must still be there — they retry, they do not retype.
    const onSubmit = vi.fn().mockRejectedValue(new Error('model unreachable'));
    render(<ChoicePanel choice={CHOICE} disabled={false} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole('button', { name: 'Show choices ▴' }));
    fireEvent.change(screen.getByPlaceholderText('What do you do?'), {
      target: { value: 'Climb the watchtower' },
    });
    fireEvent.change(screen.getByLabelText('Note to the narrator (optional)'), {
      target: { value: 'the rope is frayed' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByRole('status');

    expect(screen.getByPlaceholderText('What do you do?')).toHaveValue('Climb the watchtower');
    expect(screen.getByLabelText('Note to the narrator (optional)')).toHaveValue(
      'the rope is frayed',
    );
  });

  it('offers the failed option back in one click', async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error('model unreachable'));
    render(<ChoicePanel choice={CHOICE} disabled={false} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole('button', { name: 'Show choices ▴' }));
    fireEvent.click(screen.getByRole('button', { name: /Sneak around/ }));
    const retry = await screen.findByRole('button', { name: 'Try again' });
    expect(onSubmit).toHaveBeenCalledTimes(1);

    fireEvent.click(retry);
    // The same choice is sent again, not a different one.
    expect(onSubmit).toHaveBeenLastCalledWith({ option_id: 'b' });
  });

  it('restores the draft of a turn after a reload', () => {
    // sessionStorage, not component state: a reload (or a crash) must not cost
    // the player what they wrote before the failure.
    sessionStorage.setItem(
      'draft.7.13',
      JSON.stringify({
        customText: 'Ride out past the gate',
        noteText: 'horse is lame',
        optionId: 'a',
        optionText: 'Charge in',
        failed: true,
      }),
    );
    render(
      <ChoicePanel choice={CHOICE} disabled={false} onSubmit={vi.fn()} draftKey="draft.7.13" />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Show choices ▴' }));
    expect(screen.getByPlaceholderText('What do you do?')).toHaveValue('Ride out past the gate');
    expect(screen.getByLabelText('Note to the narrator (optional)')).toHaveValue('horse is lame');
    // The failed option comes back too, so it can be retried.
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('clears the draft once a turn actually lands', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <ChoicePanel
        choice={CHOICE}
        disabled={false}
        onSubmit={onSubmit}
        draftKey="draft.done"
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Show choices ▴' }));
    fireEvent.change(screen.getByPlaceholderText('What do you do?'), {
      target: { value: 'Walk away' },
    });
    // `send` is async (it awaits the caller), so the clearing of the fields
    // happens after the click handler returns; act() lets React flush it.
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    });
    // The draft is consumed once the turn lands, and the stored copy goes with
    // it (the mirroring write is debounced, so this waits for it).
    await vi.waitFor(() => expect(sessionStorage.getItem('draft.done')).toBeNull());
    expect(screen.getByPlaceholderText('What do you do?')).toHaveValue('');
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
