import { useEffect, useState } from 'react';
import type { Choice, ChoiceOption, TurnCreate } from '../api';
import ChatInputBar from './ui/ChatInputBar';

const NOTE_MAX_LENGTH = 2000;
// The counter appears only near the limit, so it does not distract players
// who write one short line.
const NOTE_COUNTER_FROM = NOTE_MAX_LENGTH - 200;

interface Props {
  choice: Choice;
  disabled: boolean;
  onSubmit: (payload: TurnCreate) => Promise<void>;
  /** Story + turn id, so a draft is restored for THIS turn only and never
   *  leaks into another story. */
  draftKey?: string;
}

/** What the player typed or picked, kept until a turn actually lands. */
interface Draft {
  customText: string;
  noteText: string;
  optionId: ChoiceOption['id'] | null;
  optionText: string | null;
  /** The last submit failed, so the panel says so after a reload too. */
  failed: boolean;
}

const EMPTY: Draft = {
  customText: '',
  noteText: '',
  optionId: null,
  optionText: null,
  failed: false,
};

/** A stored draft is untrusted input: only a real option id is handed back. */
function isOptionId(value: unknown): value is ChoiceOption['id'] {
  return value === 'a' || value === 'b' || value === 'c' || value === 'd';
}

function readDraft(key: string | undefined): Draft {
  if (!key) return EMPTY;
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as Partial<Draft>;
    return {
      customText: typeof parsed.customText === 'string' ? parsed.customText : '',
      noteText: typeof parsed.noteText === 'string' ? parsed.noteText : '',
      optionId: isOptionId(parsed.optionId) ? parsed.optionId : null,
      optionText: typeof parsed.optionText === 'string' ? parsed.optionText : null,
      failed: parsed.failed === true,
    };
  } catch {
    return EMPTY;
  }
}

/** The active choice, docked at the bottom of the story screen like a chat
 * input bar: options above, the custom-action input row and the optional note
 * to the narrator below. */
export default function ChoicePanel({ choice, disabled, onSubmit, draftKey }: Props) {
  const [customText, setCustomText] = useState('');
  const [noteText, setNoteText] = useState('');
  // The option whose submit failed, so it can be offered back in one click
  // instead of making the player find it in the list again.
  const [failedOption, setFailedOption] = useState<{ id: ChoiceOption['id']; text: string } | null>(
    null,
  );
  const [submitFailed, setSubmitFailed] = useState(false);
  // Collapsed by default (player request): a new turn opens as a slim bar with
  // the prompt and a "Show choices" button, so the choice UI never covers the
  // feed until it is actually wanted. The toggle still works for the turn.
  const [collapsed, setCollapsed] = useState(true);

  // Restore this turn's draft ONCE per turn, not on every render. The effect
  // used to depend on the `choice` OBJECT, which the parent recreates on each
  // render, so a submit that cleared the fields was immediately undone by a
  // re-read of the stored draft. This key is the turn's own CONTENT instead: it
  // changes when a new turn arrives (new question, new options) and is stable
  // across re-renders of the same turn.
  const turnKey = `${choice.prompt}|${choice.options.map((option) => option.id).join('')}`;
  useEffect(() => {
    const restored = readDraft(draftKey);
    setCustomText(restored.customText);
    setNoteText(restored.noteText);
    setFailedOption(
      restored.optionId && restored.optionText
        ? { id: restored.optionId, text: restored.optionText }
        : null,
    );
    setSubmitFailed(restored.failed);
    setCollapsed(true);
    if (draftKey) {
      try {
        sessionStorage.removeItem(draftKey);
      } catch {
        // Storage disabled: the fields still work, they just do not survive a
        // reload. A draft failure must never break the panel.
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turnKey]);

  // Mirror the fields into sessionStorage, so a failed request, a crash or an
  // unlucky reload cannot cost the player a paragraph they already wrote.
  useEffect(() => {
    if (!draftKey) return;
    const draft: Draft = {
      customText,
      noteText,
      optionId: failedOption?.id ?? null,
      optionText: failedOption?.text ?? null,
      failed: submitFailed,
    };
    const isEmpty = !draft.customText && !draft.noteText && !draft.optionId && !draft.failed;
    const timer = window.setTimeout(() => {
      try {
        if (isEmpty) sessionStorage.removeItem(draftKey);
        else sessionStorage.setItem(draftKey, JSON.stringify(draft));
      } catch {
        /* storage disabled */
      }
    }, 150);
    return () => window.clearTimeout(timer);
  }, [customText, noteText, failedOption, submitFailed, draftKey]);

  const notePayload = () => {
    const note = noteText.trim();
    return note ? { note_text: note } : {};
  };

  // A submit that comes back with an error keeps EVERYTHING: the typed action,
  // the note, and the option that was pressed. The caller rejects the promise
  // and the turn is unchanged, so the player retries exactly what they wrote
  // instead of retyping it.
  const send = async (
    payload: TurnCreate,
    option?: { id: ChoiceOption['id']; text: string },
  ) => {
    setSubmitFailed(false);
    try {
      await onSubmit(payload);
      // The turn landed: the draft is used up. Clearing the fields is enough —
      // the mirroring effect then sees an empty draft and removes the stored
      // copy itself. Deleting it here as well would race that debounced write.
      setCustomText('');
      setNoteText('');
      setFailedOption(null);
    } catch {
      if (option) setFailedOption(option);
      setSubmitFailed(true);
    }
  };

  const submitCustom = () => {
    const text = customText.trim();
    if (!text || disabled) return;
    void send({ custom_text: text, ...notePayload() });
  };

  const submitOption = (id: ChoiceOption['id'], text: string) => {
    if (disabled) return;
    void send({ option_id: id, ...notePayload() }, { id, text });
  };

  // Collapsed: a slim bar with just the prompt, so it stops covering the feed
  // while reading; one click brings the options back.
  if (collapsed) {
    return (
      <section className={`choice-panel choice-${choice.mode} collapsed`}>
        <div className="choice-panel-inner choice-collapsed-bar">
          <span className="choice-collapsed-prompt">{choice.prompt}</span>
          <button type="button" onClick={() => setCollapsed(false)}>
            Show choices ▴
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className={`choice-panel choice-${choice.mode}`}>
      <div className="choice-panel-inner">
        <div className="choice-panel-header">
          <h2>{choice.prompt}</h2>
          <button
            type="button"
            className="link-button choice-collapse"
            onClick={() => setCollapsed(true)}
          >
            Hide ▾
          </button>
        </div>
        {choice.mode === 'binary' && <p className="important-note">An important decision</p>}
        <div className="choice-options">
          {choice.options.map((option) => (
            <button
              key={option.id}
              type="button"
              disabled={disabled}
              onClick={() => submitOption(option.id, option.text)}
            >
              <span>{option.id.toUpperCase()}</span>
              {option.text}
            </button>
          ))}
        </div>
        {submitFailed && (
          <p className="choice-retry" role="status">
            {failedOption
              ? 'That did not go through — your choice is still here.'
              : 'That did not go through — what you typed is still here, press Send again.'}
            {failedOption && (
              <>
                {' '}
                <button
                  type="button"
                  className="link-button"
                  disabled={disabled}
                  onClick={() => submitOption(failedOption.id, failedOption.text)}
                >
                  Try again
                </button>
              </>
            )}
          </p>
        )}
        {/* The custom-action row is ALWAYS shown. `allow_custom` came from the
            narrator and a "locked"/"binary" turn set it to false, which hid the
            input and left the player able to play only by picking one of the
            narrator's options. The freedom to type your own action is the
            player's, on every turn. */}
        <label className="custom-choice-label" htmlFor="custom-action">
          Or write your own action
        </label>
        <ChatInputBar
          inputId="custom-action"
          value={customText}
          onChange={setCustomText}
          onSubmit={submitCustom}
          disabled={disabled}
          placeholder="What do you do?"
        />
        <div className="note-field">
          <label className="note-label" htmlFor="narrator-note">
            Note to the narrator (optional)
          </label>
          <textarea
            id="narrator-note"
            className="note-textarea"
            rows={2}
            maxLength={NOTE_MAX_LENGTH}
            disabled={disabled}
            placeholder="For example: my character has no lighter"
            value={noteText}
            onChange={(event) => setNoteText(event.target.value)}
          />
          {noteText.length >= NOTE_COUNTER_FROM && (
            <span
              className={`note-counter${noteText.length >= NOTE_MAX_LENGTH ? ' at-limit' : ''}`}
            >
              {noteText.length}/{NOTE_MAX_LENGTH}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
