import { useEffect, useState } from 'react';
import { api, type ImageFormat, type ImageStatus, type Turn } from '../api';
import ZoomableImage from './Lightbox';

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
  // Sampler progress (0-100) while the picture is being drawn.
  const [progress, setProgress] = useState<number | null>(null);

  useEffect(() => {
    setStatus(turn.image_status);
    setUrl(turn.image_url);
    setError(turn.image_error);
    setFormat(turn.image_format ?? 'wide');
    setProgress(turn.image_progress ?? null);
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
          setProgress(info.progress ?? null);
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

  // The prompt that produced this picture, right where the picture is: the header
  // "Image log" panel lists the whole story, but a player who dislikes THIS
  // picture must not have to go looking for its prompt.
  const [showLog, setShowLog] = useState(false);

  /** Repaint with the CURRENT prompt/style: a finished picture was made by an
   *  older prompt, and only a new job shows what the model draws now. */
  const [repainting, setRepainting] = useState(false);
  const repaint = () => {
    setRepainting(true);
    setStatus('queued');
    setUrl(null);
    setError(null);
    api
      .redoTurnImage(turn.id)
      .then((info) => {
        setStatus(info.status);
        if (info.status === 'failed') setError(info.error ?? 'Repaint failed.');
      })
      .catch((err: unknown) => {
        setStatus('failed');
        setError(err instanceof Error ? err.message : 'Repaint failed.');
      })
      .finally(() => setRepainting(false));
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
        <ZoomableImage src={url} alt="Scene illustration" style={{ aspectRatio: ASPECT[format] }} />
        <div className="image-block-actions">
          <button
            type="button"
            className="link-button image-repaint"
            onClick={repaint}
            disabled={repainting}
          >
            {repainting ? 'Repainting…' : 'Repaint this picture'}
          </button>
          {turn.image_build_log && (
            <button
              type="button"
              className="link-button"
              onClick={() => setShowLog((value) => !value)}
            >
              {showLog ? 'Hide the prompt ▾' : 'Why does it look like this? ▴'}
            </button>
          )}
        </div>
        {showLog && turn.image_build_log && (
          <pre className="image-inline-log">{turn.image_build_log}</pre>
        )}
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
      {progress !== null ? (
        <div
          className="image-progress"
          role="progressbar"
          aria-valuenow={progress}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="image-progress-bar"
            style={{ width: `${Math.min(100, Math.max(2, progress))}%` }}
          />
          <span className="image-progress-label">Drawing the scene… {progress}%</span>
        </div>
      ) : (
        <>
          <span className="spinner" aria-hidden="true" />
          <span>Drawing the scene…</span>
        </>
      )}
    </div>
  );
}
