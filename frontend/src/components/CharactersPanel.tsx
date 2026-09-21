import { useEffect, useState } from 'react';
import { api, type CharacterInfo } from '../api';
import ZoomableImage from './Lightbox';

interface Props {
  storyId: number;
  /** Bumped by the parent when a new turn arrives, so freshly introduced characters load. */
  refreshKey?: number;
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

export default function CharactersPanel({ storyId, refreshKey = 0 }: Props) {
  const [characters, setCharacters] = useState<CharacterInfo[] | null>(null);
  const [selected, setSelected] = useState<CharacterInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const load = () => {
      api
        .characters(storyId)
        .then((list) => {
          if (cancelled) return;
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
          if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load characters.');
        });
    };
    load();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [storyId, refreshKey]);

  if (error) return <p className="progress-note">{error}</p>;
  if (characters === null) return <p className="progress-note">Loading characters…</p>;
  if (characters.length === 0) {
    return <p className="progress-note">No characters met yet — they will appear here as the story introduces them.</p>;
  }

  const retry = (character: CharacterInfo) => {
    api
      .retryCharacterPortrait(character.id)
      .then((updated) => {
        setCharacters((list) => list?.map((c) => (c.id === updated.id ? updated : c)) ?? null);
        setSelected(updated);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Could not retry the portrait.'),
      );
  };

  return (
    <div className="characters-panel">
      <div className="character-grid">
        {characters.map((character) => (
          <button
            key={character.id}
            type="button"
            className="character-card"
            onClick={() => setSelected(character)}
          >
            <PortraitThumb character={character} />
            <strong>
              {character.name}
              {character.is_hero && <span className="hero-badge">you</span>}
            </strong>
            {character.role && <span className="character-role">{character.role}</span>}
            <span className="character-relationship">{character.relationship ?? '—'}</span>
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
              {selected.portrait_status === 'failed' && (
                <div className="image-block image-failed">
                  <span>
                    Portrait could not be generated{selected.portrait_error ? `: ${selected.portrait_error}` : '.'}
                  </span>
                  <button type="button" onClick={() => retry(selected)}>Retry</button>
                </div>
              )}
            </div>
          </div>
          <button type="button" className="link-button" onClick={() => setSelected(null)}>Close</button>
        </div>
      )}
    </div>
  );
}
