import { api, type CharacterInfo } from '../api';

interface Props {
  /** Characters whose first_seen_turn_id matches this turn. */
  characters: CharacterInfo[];
  /** Called with the updated character after a portrait retry is accepted. */
  onUpdated?: (character: CharacterInfo) => void;
}

const PORTRAIT_ASPECT = '4 / 5';

/**
 * Portraits of characters introduced on a given turn, shown inline in the
 * turn feed next to the scene illustration — so a first meeting shows the
 * scene image AND every new face, not just the scene.
 */
export default function IntroducedCharacters({ characters, onUpdated }: Props) {
  if (characters.length === 0) return null;

  const retry = (character: CharacterInfo) => {
    api
      .retryCharacterPortrait(character.id)
      .then((updated) => onUpdated?.(updated))
      .catch(() => {
        /* a rejected retry leaves the failed state as is */
      });
  };

  return (
    <div className="introduced-row">
      {characters.map((character) => (
        <figure key={character.id} className="introduced-card">
          {character.portrait_status === 'done' && character.portrait_url ? (
            <a href={character.portrait_url} target="_blank" rel="noreferrer">
              <img src={character.portrait_url} alt={`Portrait of ${character.name}`} />
            </a>
          ) : character.portrait_status === 'queued' || character.portrait_status === 'generating' ? (
            <div className="portrait-placeholder image-loading" style={{ aspectRatio: PORTRAIT_ASPECT }}>
              <span className="spinner" aria-hidden="true" />
              <span>Drawing…</span>
            </div>
          ) : character.portrait_status === 'failed' ? (
            <div className="portrait-placeholder portrait-empty" style={{ aspectRatio: PORTRAIT_ASPECT }}>
              <span aria-hidden="true">👤</span>
              <button type="button" className="link-button" onClick={() => retry(character)}>
                Retry portrait
              </button>
            </div>
          ) : (
            <div className="portrait-placeholder portrait-empty" style={{ aspectRatio: PORTRAIT_ASPECT }}>
              <span aria-hidden="true">👤</span>
            </div>
          )}
          <figcaption>
            <strong>{character.name}</strong>
            {character.is_hero && <span className="hero-badge">you</span>}
            {character.role && <span className="character-role"> — {character.role}</span>}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
