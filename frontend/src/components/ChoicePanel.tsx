import { useEffect, useState } from 'react';
import type { Choice, TurnCreate } from '../api';
import ChatInputBar from './ui/ChatInputBar';

const NOTE_MAX_LENGTH = 2000;
// The counter appears only near the limit, so it does not distract players
// who write one short line.
const NOTE_COUNTER_FROM = NOTE_MAX_LENGTH - 200;

interface Props {
  choice: Choice;
  disabled: boolean;
  onSubmit: (payload: TurnCreate) => Promise<void>;
}

/** The active choice, docked at the bottom of the story screen like a chat
 * input bar: options above, the custom-action input row and the optional note
 * to the narrator below. */
export default function ChoicePanel({ choice, disabled, onSubmit }: Props) {
  const [customText, setCustomText] = useState('');
  const [noteText, setNoteText] = useState('');
  // Collapsed by default (player request): a new turn opens as a slim bar with
  // the prompt and a "Show choices" button, so the choice UI never covers the
  // feed until it is actually wanted. The toggle still works for the turn.
  const [collapsed, setCollapsed] = useState(true);

  // A new choice means the previous turn was submitted successfully: clear the
  // note (and the custom action). On a submit error the choice is unchanged,
  // so the note stays in the field and nothing is lost.
  useEffect(() => {
    setCustomText('');
    setNoteText('');
    setCollapsed(true);
  }, [choice]);

  const notePayload = () => {
    const note = noteText.trim();
    return note ? { note_text: note } : {};
  };

  const submitCustom = () => {
    const text = customText.trim();
    if (!text || disabled) return;
    void onSubmit({ custom_text: text, ...notePayload() });
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
              onClick={() => void onSubmit({ option_id: option.id, ...notePayload() })}
            >
              <span>{option.id.toUpperCase()}</span>
              {option.text}
            </button>
          ))}
        </div>
        {choice.allow_custom && (
          <>
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
          </>
        )}
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
