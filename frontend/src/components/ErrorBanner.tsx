interface Props {
  message: string | null;
  onClose?: () => void;
}

export default function ErrorBanner({ message, onClose }: Props) {
  if (!message) return null;
  return (
    <div className="error-banner" role="alert">
      <span>{message}</span>
      {onClose && (
        <button type="button" onClick={onClose} aria-label="Close error">
          ×
        </button>
      )}
    </div>
  );
}
