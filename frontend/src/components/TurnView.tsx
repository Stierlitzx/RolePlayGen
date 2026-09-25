import type { CharacterInfo, Turn } from '../api';
import ChatMessage from './ui/ChatMessage';
import ImageBlock from './ImageBlock';
import IntroducedCharacters from './IntroducedCharacters';

interface Props {
  turn: Turn;
  /** Characters first introduced on this turn (matched by first_seen_turn_id). */
  introduced?: CharacterInfo[];
  /** Characters whose look changed on this turn (portrait_update/revert). */
  updated?: CharacterInfo[];
  onPortraitUpdated?: (character: CharacterInfo) => void;
}

/** One turn as chat entries: the player's action as a right-aligned bubble,
 * then the narrator's message (avatar, name, text, meta line). Same data as
 * before — only the presentation changed. */
export default function TurnView({ turn, introduced, updated, onPortraitUpdated }: Props) {
  const time = new Date(turn.created_at).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });
  return (
    <div className={`turn ${turn.is_ending ? 'turn-ending' : ''}`}>
      {turn.player_input_type !== 'start' && turn.player_input_text && (
        <ChatMessage author="You" variant="player">
          {turn.player_input_text}
          {turn.note_text && (
            <span className="turn-note" title="Note to the narrator">
              ✎ {turn.note_text}
            </span>
          )}
        </ChatMessage>
      )}
      <ChatMessage
        author="Narrator"
        avatarUrl={turn.image_status === 'done' ? turn.image_url : null}
        meta={
          <>
            Turn {turn.index + 1} · {turn.state.scene} · {time}
          </>
        }
      >
        {turn.narration.split(/\n\n+/).map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
        <ImageBlock turn={turn} />
        {introduced && introduced.length > 0 && (
          <IntroducedCharacters characters={introduced} onUpdated={onPortraitUpdated} />
        )}
        {updated && updated.length > 0 && (
          <IntroducedCharacters characters={updated} onUpdated={onPortraitUpdated} lookChanged />
        )}
      </ChatMessage>
    </div>
  );
}
