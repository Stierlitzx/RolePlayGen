import { useEffect, useState } from 'react';
import { api, type CharacterInfo } from '../api';
import ZoomableImage from './Lightbox';

/** Read a picked file as a data URL, so the backend gets it in one JSON body. */
function readImageAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error('Could not read the picture.'));
    reader.readAsDataURL(file);
  });
}

interface Props {
  storyId: number;
  /** Bumped by the parent when a new turn arrives, so freshly introduced characters load. */
  refreshKey?: number;
  /** Reports a character the player just re-pictured, so the story feed and the
   *  sidebar show the new picture without waiting for a reload. */
  onCharacterUpdated?: (character: CharacterInfo) => void;
}

const PORTRAIT_ASPECT = '4 / 5';

function PortraitThumb({ character, zoomable = false }: { character: CharacterInfo; zoomable?: boolean }) {
  if (character.portrait_status === 'done' && character.portrait_url) {
    if (zoomable) {
      return <ZoomableImage src={character.portrait_url} alt={`Portrait of ${character.name}`} />;
    }
    return <img src={character.portrait_url} alt={`Portrait of ${character.name}`} />;
  }
  if (character.portrait_status === 'queued' || character.portrait_status === 'generating') {
    return (
      <div className="portrait-placeholder image-loading" style={{ aspectRatio: PORTRAIT_ASPECT }}>
        <span className="spinner" aria-hidden="true" />
        <span>Drawing…</span>
      </div>
    );
  }
  return (
    <div className="portrait-placeholder portrait-empty" style={{ aspectRatio: PORTRAIT_ASPECT }}>
      <span aria-hidden="true">👤</span>
    </div>
  );
}

export default function CharactersPanel({ storyId, refreshKey = 0, onCharacterUpdated }: Props) {
  const [characters, setCharacters] = useState<CharacterInfo[] | null>(null);
  const [selected, setSelected] = useState<CharacterInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  // True while the player's own picture is being uploaded.
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const load = () => {
      api
        .characters(storyId)
        .then((list) => {
          if (cancelled) return;
          setError(null);
          setCharacters(list);
          setSelected((current) =>
            current ? (list.find((item) => item.id === current.id) ?? current) : current,
          );
          // Poll only while a portrait is still being drawn.
          if (list.some((c) => c.portrait_status === 'queued' || c.portrait_status === 'generating')) {
            timer = window.setTimeout(load, 2500);
          }
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setError(err instanceof Error ? err.message : 'Could not load characters.');
          // Keep retrying slowly: a backend restart must not freeze the panel.
          timer = window.setTimeout(load, 5000);
        });
    };
    load();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [storyId, refreshKey]);

  // A failed request must NOT blank the panel: a hung backend used to look
  // exactly like "the characters are gone", which is worse than a warning above
  // a list that is still there. The list is kept, and the reload is retried.
  if (characters === null) {
    return <p className="progress-note">{error ?? 'Loading characters…'}</p>;
  }
  if (characters.length === 0) {
    return (
      <p className="progress-note">
        {error ?? 'No characters met yet — they will appear here as the story introduces them.'}
      </p>
    );
  }

  const retry = (character: CharacterInfo) => {
    api
      .retryCharacterPortrait(character.id)
      .then(applyUpdate)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Could not retry the portrait.'),
      );
  };

  const applyUpdate = (updated: CharacterInfo) => {
    setCharacters((list) => list?.map((c) => (c.id === updated.id ? updated : c)) ?? null);
    setSelected(updated);
    onCharacterUpdated?.(updated);
  };

  // The player's own picture of a character: it becomes the reference every
  // generated picture is built from, and the card shows it right away.
  const uploadPhoto = (character: CharacterInfo, file: File) => {
    setUploading(true);
    setError(null);
    void readImageAsDataUrl(file)
      .then((image) => api.uploadCharacterPhoto(character.id, image))
      .then(applyUpdate)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Could not upload the picture.'),
      )
      .finally(() => setUploading(false));
  };

  return (
    <div className="characters-panel">
      {error && (
        <p className="progress-note characters-panel-warning">
          {error} — showing the last known list.
        </p>
      )}
      <div className="character-list">
        {characters.map((character) => (
          <button
            key={character.id}
            type="button"
            className={selected?.id === character.id ? 'character-card active' : 'character-card'}
            onClick={() => setSelected(character)}
          >
            <PortraitThumb character={character} />
            <span className="character-card-text">
              <strong>
                {character.name}
                {character.is_hero && <span className="hero-badge">you</span>}
              </strong>
              {character.role && <span className="character-role">{character.role}</span>}
              <span className="character-relationship">{character.relationship ?? '—'}</span>
            </span>
          </button>
        ))}
      </div>
      {selected && (
        <div className="character-detail" role="dialog" aria-label={`About ${selected.name}`}>
          <div className="character-detail-body">
            <div className="character-detail-portrait">
              <PortraitThumb character={selected} zoomable />
            </div>
            <div>
              <h2>
                {selected.name}
                {selected.is_hero && <span className="hero-badge">you</span>}
              </h2>
              <p className="character-role">{selected.role ?? '—'}</p>
              {!selected.is_hero && (
                <p>
                  <strong>Relationship to you:</strong> {selected.relationship ?? '—'}
                </p>
              )}
              {selected.description && <p>{selected.description}</p>}
              {selected.portrait_history.filter((v) => v.portrait_url).length > 1 && (
                <div className="portrait-history">
                  <h3>Past looks</h3>
                  <div className="portrait-history-grid">
                    {selected.portrait_history.map((version, index) =>
                      version.portrait_url ? (
                        <figure
                          key={`${version.turn_id ?? 'x'}-${index}`}
                          className={version.current ? 'portrait-history-item current' : 'portrait-history-item'}
                        >
                          <ZoomableImage
                            src={version.portrait_url}
                            alt={`${selected.name} — look ${index + 1}`}
                          />
                          <figcaption>
                            Look {index + 1}
                            {version.turn_id != null && ` · turn ${version.turn_id}`}
                            {version.current && ' · current'}
                          </figcaption>
                        </figure>
                      ) : null,
                    )}
                  </div>
                </div>
              )}
              {selected.portrait_status === 'failed' && (
                <div className="image-block image-failed">
                  <span>
                    Portrait could not be generated{selected.portrait_error ? `: ${selected.portrait_error}` : '.'}
                  </span>
                  <button type="button" onClick={() => retry(selected)}>Retry</button>
                </div>
              )}
              {selected.portrait_build_log && (
                <details className="character-image-log">
                  <summary>Image log — what the picture model was told</summary>
                  <pre>{selected.portrait_build_log}</pre>
                </details>
              )}
              <div className="character-photo-actions">
                <button
                  type="button"
                  className="link-button"
                  disabled={uploading}
                  onClick={() => {
                    setUploading(true);
                    api
                      .redoCharacterPortrait(selected.id)
                      .then(applyUpdate)
                      .catch((err: unknown) =>
                        setError(
                          err instanceof Error ? err.message : 'Could not repaint the portrait.',
                        ),
                      )
                      .finally(() => setUploading(false));
                  }}
                >
                  Repaint this portrait
                </button>
              </div>
              <label className="character-photo-upload">
                {selected.photo_url ? 'Replace their picture' : 'Use your own picture'}
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  disabled={uploading}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) uploadPhoto(selected, file);
                    event.target.value = '';
                  }}
                />
                <span className="character-photo-hint">
                  {uploading
                    ? 'Uploading…'
                    : 'The picture generator works from this face, in the story feed and in every scene.'}
                </span>
              </label>
            </div>
          </div>
          <button type="button" className="link-button" onClick={() => setSelected(null)}>Close</button>
        </div>
      )}
    </div>
  );
}
