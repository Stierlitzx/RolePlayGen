import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type CharacterInfo, type Story, type StoryCreate, type TurnCreate } from '../api';
import CharactersPanel from '../components/CharactersPanel';
import ChoicePanel from '../components/ChoicePanel';
import ErrorBanner from '../components/ErrorBanner';
import LoadingIndicator from '../components/LoadingIndicator';
import TurnView from '../components/TurnView';

interface Props {
  storyId: number;
  onHome: () => void;
  onNewStory: () => void;
  onEditStory: (story: Story) => void;
}

export default function StoryPage({ storyId, onHome, onNewStory, onEditStory }: Props) {
  const [story, setStory] = useState<Story | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'story' | 'characters'>('story');
  const [characters, setCharacters] = useState<CharacterInfo[]>([]);
  const [narratorStyles, setNarratorStyles] = useState<string[]>([]);
  const [styleSaving, setStyleSaving] = useState(false);
  const feedEndRef = useRef<HTMLDivElement | null>(null);
  const lastTurnTextRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .story(storyId)
      .then(setStory)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Could not load the story.'),
      )
      .finally(() => setLoading(false));
  }, [storyId]);

  // Characters load alongside the story and refresh whenever a new turn
  // arrives, so portraits of newly introduced characters show up in the feed.
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      api
        .characters(storyId)
        .then((list) => {
          if (cancelled) return;
          setCharacters(list);
          if (list.some((c) => c.portrait_status === 'queued' || c.portrait_status === 'generating')) {
            window.setTimeout(() => {
              if (!cancelled) load();
            }, 2500);
          }
        })
        .catch(() => {
          /* portraits are optional — a failure here must not break the story */
        });
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [storyId, story?.turns.length]);

  const updateCharacter = useCallback((updated: CharacterInfo) => {
    setCharacters((list) => list.map((c) => (c.id === updated.id ? updated : c)));
  }, []);

  useEffect(() => {
    api
      .setupOptions()
      .then((value) => setNarratorStyles(value.narrator_styles))
      .catch(() => {
        /* the style picker simply stays hidden without the options */
      });
  }, []);

  // The narrator voice may change at any point; every other setup field is
  // frozen once the second turn exists (the backend enforces this too).
  const changeNarratorStyle = useCallback(
    async (value: string) => {
      if (!story || styleSaving) return;
      setStyleSaving(true);
      setError(null);
      try {
        const payload = { ...story.settings, narrator_style: value } as unknown as StoryCreate;
        setStory(await api.updateStory(story.id, payload));
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not change the narrator style.');
      } finally {
        setStyleSaving(false);
      }
    },
    [story, styleSaving],
  );

  useEffect(() => {
    // Scroll to the new turn's text; image placeholders reserve their height
    // so the page does not jump when the picture arrives.
    lastTurnTextRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [story?.turns.length]);

  const submitChoice = useCallback(
    async (payload: TurnCreate) => {
      if (submitting) return;
      setSubmitting(true);
      setError(null);
      try {
        const turn = await api.createTurn(storyId, payload);
        setStory((current) => {
          if (!current) return current;
          const finished = turn.is_ending;
          return {
            ...current,
            status: finished ? 'finished' : current.status,
            turns: [...current.turns, turn],
          };
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not submit your choice.');
      } finally {
        setSubmitting(false);
      }
    },
    [storyId, submitting],
  );

  const regenerateStart = useCallback(async () => {
    if (regenerating || !window.confirm('Regenerate the opening turn? The current beginning will be replaced.')) return;
    setRegenerating(true);
    setError(null);
    try {
      setStory(await api.regenerateStart(storyId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not regenerate the beginning.');
    } finally {
      setRegenerating(false);
    }
  }, [storyId, regenerating]);

  if (loading) return <LoadingIndicator text="Loading story…" />;
  if (!story) {
    return (
      <main className="page narrow-page">
        <ErrorBanner message={error} />
        <button type="button" onClick={onHome}>Home</button>
      </main>
    );
  }

  const lastTurn = story.turns[story.turns.length - 1];
  const ended = story.status === 'finished' || (lastTurn?.is_ending ?? false);
  const canChangeStart = story.turns.length <= 1 && !ended;

  return (
    <main className="page story-page">
      <header className="story-header">
        <div>
          <p className="eyebrow">{String(story.settings.tone ?? '')}</p>
          <h1>{story.title}</h1>
          <p className="progress-note">
            Turn {story.turns.length}{story.max_turns ? ` of ${story.max_turns}` : ''}
          </p>
        </div>
        {narratorStyles.length > 0 && (
          <label className="narrator-style-picker">
            Narrator
            <select
              value={String(story.settings.narrator_style ?? 'Classic narrator')}
              disabled={styleSaving}
              onChange={(event) => void changeNarratorStyle(event.target.value)}
            >
              {narratorStyles.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
        )}
        <div className="card-actions">
          {canChangeStart && (
            <>
              <button type="button" onClick={() => onEditStory(story)}>Change beginning</button>
              <button type="button" disabled={regenerating} onClick={() => void regenerateStart()}>
                {regenerating ? 'Regenerating…' : 'Regenerate opening'}
              </button>
            </>
          )}
          <button type="button" onClick={onHome}>Exit</button>
        </div>
      </header>
      <ErrorBanner message={error} onClose={() => setError(null)} />
      <nav className="story-tabs" aria-label="Story sections">
        <button
          type="button"
          className={tab === 'story' ? 'tab-button active' : 'tab-button'}
          onClick={() => setTab('story')}
        >
          Story
        </button>
        <button
          type="button"
          className={tab === 'characters' ? 'tab-button active' : 'tab-button'}
          onClick={() => setTab('characters')}
        >
          Characters
        </button>
      </nav>
      {tab === 'characters' ? (
        <CharactersPanel storyId={storyId} refreshKey={story.turns.length} />
      ) : (
        <>
      <div className="turn-feed">
        {story.turns.map((turn, i) => (
          <div
            key={turn.id}
            ref={i === story.turns.length - 1 ? (el) => { lastTurnTextRef.current = el; } : undefined}
          >
            <TurnView
              turn={turn}
              introduced={characters.filter((c) => c.first_seen_turn_id === turn.id)}
              onPortraitUpdated={updateCharacter}
            />
          </div>
        ))}
        <div ref={feedEndRef} />
      </div>
      {ended ? (
        <section className="ending-panel">
          <h2>The End</h2>
          <p>{lastTurn?.state.summary}</p>
          <div className="card-actions">
            <button className="primary" type="button" onClick={onNewStory}>New story</button>
            <button type="button" onClick={onHome}>Home</button>
          </div>
        </section>
      ) : submitting ? (
        <LoadingIndicator />
      ) : (
        lastTurn?.choice && (
          <ChoicePanel choice={lastTurn.choice} disabled={submitting} onSubmit={submitChoice} />
        )
      )}
        </>
      )}
    </main>
  );
}
