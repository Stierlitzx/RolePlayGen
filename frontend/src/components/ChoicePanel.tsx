import { FormEvent, useEffect, useState } from 'react';
import type { Choice, TurnCreate } from '../api';

interface Props {
  choice: Choice;
  disabled: boolean;
  onSubmit: (payload: TurnCreate) => Promise<void>;
}

export default function ChoicePanel({ choice, disabled, onSubmit }: Props) {
  const [customText, setCustomText] = useState('');

  useEffect(() => {
    setCustomText('');
  }, [choice]);

  const submitCustom = (event: FormEvent) => {
    event.preventDefault();
    const text = customText.trim();
    if (!text || disabled) return;
    void onSubmit({ custom_text: text });
  };

  return (
    <section className={`choice-panel choice-${choice.mode}`}>
      <h2>{choice.prompt}</h2>
      {choice.mode === 'binary' && <p className="important-note">An important decision</p>}
      <div className="choice-options">
        {choice.options.map((option) => (
          <button
            key={option.id}
            type="button"
            disabled={disabled}
            onClick={() => void onSubmit({ option_id: option.id })}
          >
            <span>{option.id.toUpperCase()}</span>
            {option.text}
          </button>
        ))}
      </div>
      {choice.allow_custom && (
        <form className="custom-choice" onSubmit={submitCustom}>
          <label htmlFor="custom-action">Or write your own action</label>
          <div>
            <input
              id="custom-action"
              value={customText}
              maxLength={500}
              disabled={disabled}
              onChange={(event) => setCustomText(event.target.value)}
              placeholder="What do you do?"
            />
            <button type="submit" disabled={disabled || !customText.trim()}>
              Send
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
