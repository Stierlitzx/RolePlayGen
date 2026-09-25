import type { FormEvent } from 'react';

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  placeholder?: string;
  inputId?: string;
  maxLength?: number;
}

/** The input row docked at the bottom of the story screen. */
export default function ChatInputBar({
  value,
  onChange,
  onSubmit,
  disabled = false,
  placeholder = 'Continue the story…',
  inputId,
  maxLength = 1500,
}: Props) {
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };
  return (
    <form className="chat-input-bar" onSubmit={submit}>
      <input
        id={inputId}
        value={value}
        maxLength={maxLength}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      <button type="submit" className="primary" disabled={disabled || !value.trim()}>
        Send
      </button>
    </form>
  );
}
