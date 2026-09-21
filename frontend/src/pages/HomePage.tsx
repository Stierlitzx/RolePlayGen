import { useEffect, useState } from 'react';
import { api, type StorySummary } from '../api';
import ErrorBanner from '../components/ErrorBanner';
import LoadingIndicator from '../components/LoadingIndicator';

interface Props {
  onNewStory: () => void;
  onOpenStory: (id: number) => void;
}

function genresOf(story: StorySummary): string {
  const genres = story.settings.genres;
  return Array.isArray(genres) ? genres.join(', ') : 'Unknown genre';
}

export default function HomePage({ onNewStory, onOpenStory }: Props) {
  const [stories, setStories] = useState<StorySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadStories = async () => {
    setLoading(true);
    setError(null);
    try {
      setStories(await api.stories());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load stories.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadStories();
  }, []);

  const deleteStory = async (story: StorySummary) => {
    if (!window.confirm(`Delete “${story.title}” and all its turns?`)) return;
    setError(null);
    try {
      await api.deleteStory(story.id);
      localStorage.removeItem('roleplaygen.currentStoryId');
      await loadStories();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete the story.');
    }
  };

  return (
    <main className="page narrow-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Interactive fiction</p>
          <h1>Your stories</h1>
        </div>
        <button className="primary" type="button" onClick={onNewStory}>
          New story
        </button>
      </div>
      <ErrorBanner message={error} onClose={() => setError(null)} />
      {loading ? (
        <LoadingIndicator text="Loading stories…" />
      ) : stories.length === 0 ? (
        <section className="empty-state">
          <h2>No saved stories yet</h2>
          <p>Configure a world and let the narrator begin.</p>
          <button className="primary" type="button" onClick={onNewStory}>
            Start your first story
          </button>
        </section>
      ) : (
        <div className="story-list">
          {stories.map((story) => (
            <article className="story-card" key={story.id}>
              <div>
                <h2>{story.title}</h2>
                <p>{genresOf(story)}</p>
                <p>
                  {story.turn_count} turns · {new Date(story.updated_at).toLocaleDateString()} ·{' '}
                  {story.status}
                </p>
              </div>
              <div className="card-actions">
                <button type="button" onClick={() => onOpenStory(story.id)}>
                  {story.status === 'finished' ? 'Read' : 'Resume'}
                </button>
                <button className="danger" type="button" onClick={() => void deleteStory(story)}>
                  Delete
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </main>
  );
}
