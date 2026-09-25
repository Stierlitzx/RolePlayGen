import { useEffect, useState } from 'react';
import type { CSSProperties } from 'react';

interface LightboxProps {
  src: string;
  alt: string;
  onClose: () => void;
}

/** Fullscreen overlay: click toggles fit-to-screen / actual size, Esc or the
 * backdrop closes it. Body scroll is locked while open. */
export function Lightbox({ src, alt, onClose }: LightboxProps) {
  const [zoomed, setZoomed] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [onClose]);

  return (
    <div
      className={zoomed ? 'lightbox-backdrop zoomed' : 'lightbox-backdrop'}
      role="dialog"
      aria-label={alt}
      onClick={onClose}
    >
      <button type="button" className="lightbox-close" aria-label="Close" onClick={onClose}>
        ✕
      </button>
      <img
        src={src}
        alt={alt}
        className={zoomed ? 'lightbox-image zoomed' : 'lightbox-image'}
        onClick={(event) => {
          event.stopPropagation();
          setZoomed((current) => !current);
        }}
      />
      <p className="lightbox-hint">
        Click the image to {zoomed ? 'fit it to the screen' : 'zoom in'} · Esc to close
      </p>
    </div>
  );
}

interface ZoomableImageProps {
  src: string;
  alt: string;
  className?: string;
  style?: CSSProperties;
}

/** An image that opens the fullscreen lightbox on click. */
export default function ZoomableImage({ src, alt, className, style }: ZoomableImageProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="image-zoom-trigger"
        onClick={() => setOpen(true)}
        aria-label={`Open ${alt} fullscreen`}
      >
        <img src={src} alt={alt} className={className} style={style} />
      </button>
      {open && <Lightbox src={src} alt={alt} onClose={() => setOpen(false)} />}
    </>
  );
}
