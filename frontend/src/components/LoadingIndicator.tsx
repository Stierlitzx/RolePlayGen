interface Props {
  text?: string;
}

export default function LoadingIndicator({ text = 'The narrator is thinking…' }: Props) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{text}</span>
    </div>
  );
}
