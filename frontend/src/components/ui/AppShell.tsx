import type { ReactNode } from 'react';
import type { CharacterInfo, StorySummary } from '../../api';

interface Props {
  stories: StorySummary[];
  activeStoryId?: number;
  /** Characters of the open story (reported up by StoryPage); omitted elsewhere. */
  characters?: CharacterInfo[];
  onOpenStory: (id: number) => void;
  onNewStory: () => void;
  onDeleteStory: (story: StorySummary) => void;
  /** The brand acts as a "home" link. */
  onHome: () => void;
  /** Clicking a character in the sidebar (StoryPage switches to its tab). */
  onCharacterClick?: () => void;
  children: ReactNode;
}

function genresOf(story: StorySummary): string {
  const genres = story.settings.genres;
  return Array.isArray(genres) ? genres.join(', ') : '';
}

/** The workspace frame: permanent left sidebar (stories, and the open story's
 * characters) plus the main column each page fills with its own content. */
export default function AppShell({
  stories,
  activeStoryId,
  characters,
  onOpenStory,
  onNewStory,
  onDeleteStory,
  onHome,
  onCharacterClick,
  children,
}: Props) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button type="button" className="sidebar-brand" onClick={onHome} title="Home">
          ✦ RolePlayGen
        </button>
        <section className="sidebar-section">
          <header className="sidebar-section-header">
            <span>Stories</span>
            <button
              type="button"
              className="sidebar-add"
              onClick={onNewStory}
              aria-label="New story"
              title="New story"
            >
              +
            </button>
          </header>
          {stories.length === 0 ? (
            <p className="sidebar-empty">No stories yet — press + to start one.</p>
          ) : (
            <ul className="sidebar-list">
              {stories.map((story) => (
                <li key={story.id}>
                  <div className={story.id === activeStoryId ? 'sidebar-item active' : 'sidebar-item'}>
                    <button
                      type="button"
                      className="sidebar-item-main"
                      onClick={() => onOpenStory(story.id)}
                    >
                      <span className="sidebar-item-title">{story.title}</span>
                      <span className="sidebar-item-meta">
                        {story.status === 'finished' ? '✓ finished · ' : ''}
                        {story.turn_count} turns · {new Date(story.updated_at).toLocaleDateString()}
                      </span>
                      {genresOf(story) && (
                        <span className="sidebar-item-meta">{genresOf(story)}</span>
                      )}
                    </button>
                    <button
                      type="button"
                      className="sidebar-item-delete"
                      aria-label={`Delete ${story.title}`}
                      title="Delete story"
                      onClick={() => onDeleteStory(story)}
                    >
                      ✕
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
        {characters && characters.length > 0 && (
          <section className="sidebar-section">
            <header className="sidebar-section-header">
              <span>Characters</span>
            </header>
            <ul className="sidebar-list">
              {characters.map((character) => (
                <li key={character.id}>
                  <button
                    type="button"
                    className="sidebar-item sidebar-item-main sidebar-character"
                    onClick={onCharacterClick}
                  >
                    <span className="sidebar-avatar" aria-hidden="true">
                      {character.portrait_url ? (
                        <img src={character.portrait_url} alt="" />
                      ) : (
                        '👤'
                      )}
                    </span>
                    <span className="sidebar-item-text">
                      <span className="sidebar-item-title">
                        {character.name}
                        {character.is_hero && <span className="hero-badge">you</span>}
                      </span>
                      {character.role && (
                        <span className="sidebar-item-meta">{character.role}</span>
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </aside>
      <div className="main-column">{children}</div>
    </div>
  );
}
