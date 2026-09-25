import { api, type CharacterInfo } from '../api';
import ZoomableImage from './Lightbox';

interface Props {
  /** Characters whose first_seen_turn_id matches this turn. */
  characters: CharacterInfo[];
  /** Called with the updated character after a portrait retry is accepted. */
  onUpdated?: (character: CharacterInfo) => void;
  /** True when these portraits are a NEW LOOK of characters met earlier rather
   * than a first appearance; the row is then labelled "New look". */
  lookChanged?: boolean;
}

const PORTRAIT_ASPECT = '4 / 5';

/**
 * Characters whose CURRENT look was created on this turn — a narrator
 * `portrait_update` (disguise, new outfit, injury) or a `portrait_revert` back
 * to an earlier version. Either rewrites the last `portrait_history` entry with
 * the turn it happened in, so that turn can show the new picture under its
 * narration, exactly like a first meeting does.
 */
export function charactersWithNewLook(
  characters: CharacterInfo[],
  turnId: number,
): CharacterInfo[] {
  return characters.filter((character) => {
    if (character.first_seen_turn_id === turnId) return false; // shown as an introduction
    const latest = character.portrait_history[character.portrait_history.length - 1];
    return latest !== undefined && latest.turn_id === turnId;
  });
}

/**
 * Portraits of characters introduced on a given turn (or of characters whose
 * look changed on it), shown inline in the turn feed next to the scene
 * illustration — so a first meeting shows the scene image AND every new face,
 * and a look change shows the new portrait where it happened.
 */
export default function IntroducedCharacters({ characters, onUpdated, lookChanged }: Props) {
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
      {lookChanged && <span className="introduced-label">New look</span>}
      {characters.map((character) => (
        <figure key={character.id} className="introduced-card">
          {character.portrait_status === 'done' && character.portrait_url ? (
            <ZoomableImage src={character.portrait_url} alt={`Portrait of ${character.name}`} />
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
