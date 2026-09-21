import { useEffect, useState } from 'react';
import { api, type ImageFormat, type ImageStatus, type Turn } from '../api';

interface Props {
  turn: Turn;
}

const ASPECT: Record<ImageFormat, string> = {
  wide: '16 / 9',
  portrait: '4 / 5',
};

export default function ImageBlock({ turn }: Props) {
  const [status, setStatus] = useState<ImageStatus>(turn.image_status);
  const [url, setUrl] = useState<string | null>(turn.image_url);
  const [error, setError] = useState<string | null>(turn.image_error);
  const [format, setFormat] = useState<ImageFormat>(turn.image_format ?? 'wide');
  const [pollFailures, setPollFailures] = useState(0);

  useEffect(() => {
    setStatus(turn.image_status);
    setUrl(turn.image_url);
    setError(turn.image_error);
    setFormat(turn.image_format ?? 'wide');
    setPollFailures(0);
  }, [turn.id, turn.image_status, turn.image_url, turn.image_error, turn.image_format]);

  useEffect(() => {
    if (status !== 'queued' && status !== 'generating') return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      api
        .turnImage(turn.id)
        .then((info) => {
          if (cancelled) return;
          setPollFailures(0);
          setStatus(info.status);
          setUrl(info.url);
          setError(info.error);
          if (info.format) setFormat(info.format);
        })
        .catch(() => {
          // Keep polling: a wedged or restarting server must not kill the image.
          // After several failures in a row the UI says so instead of spinning silently.
          if (!cancelled) setPollFailures((count) => count + 1);
        });
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [status, turn.id]);

  if (status === 'none') return null;

  const unreachable = pollFailures >= 5;

  const retry = () => {
    setStatus('queued');
    setError(null);
    api.retryTurnImage(turn.id).catch((err: unknown) => {
      setStatus('failed');
      setError(err instanceof Error ? err.message : 'Retry failed.');
    });
  };

  if (status === 'failed') {
    return (
      <div className="image-block image-failed">
        <span>Image could not be generated{error ? `: ${error}` : '.'}</span>
        <button type="button" onClick={retry}>Retry</button>
      </div>
    );
  }

  if (status === 'done' && url) {
    return (
      <div className={`image-block image-done image-${format}`}>
        <a href={url} target="_blank" rel="noreferrer">
          <img src={url} alt="Scene illustration" style={{ aspectRatio: ASPECT[format] }} />
        </a>
      </div>
    );
  }

  if (unreachable) {
    return (
      <div className={`image-block image-loading image-${format}`} style={{ aspectRatio: ASPECT[format] }}>
        <span className="spinner" aria-hidden="true" />
        <span>
          The server is not responding — the image may still be generating.
          It will appear here once the backend is back.
        </span>
      </div>
    );
  }

  return (
    <div className={`image-block image-loading image-${format}`} style={{ aspectRatio: ASPECT[format] }}>
      <span className="spinner" aria-hidden="true" />
      <span>Drawing the scene…</span>
    </div>
  );
}
