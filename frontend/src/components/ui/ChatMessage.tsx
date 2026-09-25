import type { ReactNode } from 'react';

interface Props {
  author: string;
  /** Small round avatar on the left; a glyph is shown when there is no image. */
  avatarUrl?: string | null;
  avatarFallback?: string;
  /** Meta line under the message (turn number, scene, time…). */
  meta?: ReactNode;
  variant?: 'narrator' | 'player';
  children: ReactNode;
}

/** One entry of the story chat feed: avatar + author + text + meta line,
 * or a right-aligned bubble for the player's own action. */
export default function ChatMessage({
  author,
  avatarUrl,
  avatarFallback = '✒',
  meta,
  variant = 'narrator',
  children,
}: Props) {
  if (variant === 'player') {
    return (
      <div className="chat-message chat-player">
        <div className="chat-bubble">{children}</div>
        <div className="chat-meta">{author}</div>
      </div>
    );
  }
  return (
    <div className="chat-message">
      <span className="chat-avatar" aria-hidden="true">
        {avatarUrl ? <img src={avatarUrl} alt="" /> : avatarFallback}
      </span>
      <div className="chat-body">
        <div className="chat-author">{author}</div>
        <div className="chat-text">{children}</div>
        {meta && <div className="chat-meta">{meta}</div>}
      </div>
    </div>
  );
}
