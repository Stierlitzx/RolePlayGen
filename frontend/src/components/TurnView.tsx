import type { CharacterInfo, Turn } from '../api';
import ImageBlock from './ImageBlock';
import IntroducedCharacters from './IntroducedCharacters';

interface Props {
  turn: Turn;
  /** Characters first introduced on this turn (matched by first_seen_turn_id). */
  introduced?: CharacterInfo[];
  onPortraitUpdated?: (character: CharacterInfo) => void;
}

export default function TurnView({ turn, introduced, onPortraitUpdated }: Props) {
  return (
    <article className={`turn ${turn.is_ending ? 'turn-ending' : ''}`}>
      <div className="turn-meta">
        <span>Turn {turn.index + 1}</span>
        <span>{turn.state.scene}</span>
      </div>
      {turn.narration.split(/\n\n+/).map((paragraph) => (
        <p key={paragraph}>{paragraph}</p>
      ))}
      <ImageBlock turn={turn} />
      {introduced && introduced.length > 0 && (
        <IntroducedCharacters characters={introduced} onUpdated={onPortraitUpdated} />
      )}
      {turn.player_input_type !== 'start' && (
        <div className="player-choice">
          <strong>Your choice:</strong> {turn.player_input_text}
        </div>
      )}
    </article>
  );
}
