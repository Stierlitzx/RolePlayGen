import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type CharacterInfo, type Story, type StoryCreate, type TurnCreate } from '../api';
import CharactersPanel from '../components/CharactersPanel';
import ChoicePanel from '../components/ChoicePanel';
import ErrorBanner from '../components/ErrorBanner';
import LoadingIndicator from '../components/LoadingIndicator';
import { charactersWithNewLook } from '../components/IntroducedCharacters';
import TurnView from '../components/TurnView';
import TopBar from '../components/ui/TopBar';

export type StoryTab = 'story' | 'characters';

interface Props {
  storyId: number;
  /** The tab state lives in App so the sidebar can switch to Characters. */
  tab: StoryTab;
  onTabChange: (tab: StoryTab) => void;
  onHome: () => void;
  onNewStory: () => void;
  onEditStory: (story: Story) => void;
  /** Reports the loaded cast up so the app shell sidebar can list it. */
  onCharactersChange: (characters: CharacterInfo[]) => void;
}

/** The play screen: story turns as a chat feed with the choice bar docked at
 * the bottom. Same data and handlers as before — only the layout changed. */
export default function StoryPage({
  storyId,
  tab,
  onTabChange,
  onHome,
  onNewStory,
  onEditStory,
  onCharactersChange,
}: Props) {
  const [story, setStory] = useState<Story | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [characters, setCharacters] = useState<CharacterInfo[]>([]);
  const [narratorStyles, setNarratorStyles] = useState<string[]>([]);
  const [styleSaving, setStyleSaving] = useState(false);
  const [showFacts, setShowFacts] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [factDeleting, setFactDeleting] = useState<number | null>(null);
  const lastTurnTextRef = useRef<HTMLDivElement | null>(null);
  const feedRef = useRef<HTMLDivElement | null>(null);
  const seenTurnsRef = useRef<number | null>(null);
  const scrollKey = `roleplaygen.storyScroll.${storyId}`;

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

  // A character the player just re-pictured (Characters tab) must appear in the
  // story feed immediately: the panel hands the updated row up, and the same
  // patch refreshes the app-shell sidebar. Without this the feed kept showing
  // the old picture until a page reload.
  const applyCharacterUpdate = useCallback((updated: CharacterInfo) => {
    setCharacters((list) =>
      list.map((item) => (item.id === updated.id ? updated : item)),
    );
  }, []);

  // Keep the app shell sidebar in sync with the open story's cast.
  useEffect(() => {
    onCharactersChange(characters);
  }, [characters, onCharactersChange]);

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

  // Scroll memory. The feed unmounts when the Characters tab (or Home, via
  // the sidebar) opens, and without this the reader loses their place in a
  // long story. The position is kept in sessionStorage per story and restored
  // on return; only a genuinely new turn jumps to its opening line — the
  // narrator's latest text is what the player reads next. Image placeholders
  // reserve their height so the restored position does not jump when the
  // picture arrives.
  useEffect(() => {
    seenTurnsRef.current = null;
  }, [storyId]);

  useEffect(() => {
    if (tab !== 'story' || !story) return;
    const frame = requestAnimationFrame(() => {
      const feed = feedRef.current;
      if (!feed) return;
      const turnsNow = story.turns.length;
      const isNewTurn = seenTurnsRef.current !== null && turnsNow !== seenTurnsRef.current;
      seenTurnsRef.current = turnsNow;
      const saved = sessionStorage.getItem(scrollKey);
      if (isNewTurn || saved === null) {
        lastTurnTextRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
      } else {
        feed.scrollTop = Number(saved);
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [tab, story, storyId, scrollKey]);

  const saveFeedScroll = () => {
    if (feedRef.current) {
      sessionStorage.setItem(scrollKey, String(feedRef.current.scrollTop));
    }
  };

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
        // Rethrow so the choice panel learns the turn did NOT land and keeps
        // what the player wrote. Swallowing it here left the panel clearing
        // itself after a failure, which is how a typed paragraph got lost.
        throw err;
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

  // Shown whenever the opening-regenerate buttons are not: deletes the last
  // turn and replays the stored player input (works on finished stories too).
  const regenerateLast = useCallback(async () => {
    if (regenerating || !window.confirm('Redo the last turn? It will be regenerated from the same choice.')) return;
    setRegenerating(true);
    setError(null);
    try {
      setStory(await api.regenerateLast(storyId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not redo the last turn.');
    } finally {
      setRegenerating(false);
    }
  }, [storyId, regenerating]);

  const updateCharacter = useCallback((updated: CharacterInfo) => {
    setCharacters((list) => list.map((c) => (c.id === updated.id ? updated : c)));
  }, []);

  // The player removes a mistaken "fact" note here instead of writing the
  // opposite note; the fact stops reaching the narrator from the next turn on.
  const deletePinnedFact = async (index: number) => {
    setFactDeleting(index);
    try {
      const result = await api.deletePinnedFact(storyId, index);
      setStory((s) => (s ? { ...s, pinned_facts: result.pinned_facts } : s));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete the pinned fact.');
    } finally {
      setFactDeleting(null);
    }
  };

  if (loading) return <LoadingIndicator text="Loading story…" />;
  if (!story) {
    return (
      <div className="page-column">
        <div className="content-scroll">
          <ErrorBanner message={error} />
          <button type="button" onClick={onHome}>Home</button>
        </div>
      </div>
    );
  }

  const lastTurn = story.turns[story.turns.length - 1];
  const ended = story.status === 'finished' || (lastTurn?.is_ending ?? false);
  const canChangeStart = story.turns.length <= 1 && !ended;
  const loggedTurns = story.turns.filter((turn) => turn.image_build_log).length;

  return (
    <div className="page-column">
      <TopBar
        title={story.title}
        subtitle={
          <>
            {String(story.settings.tone ?? '')}
            {' · '}
            Turn {story.turns.length}{story.max_turns ? ` of ${story.max_turns}` : ''}
          </>
        }
        status={{ ok: !ended, label: ended ? 'finished' : 'active' }}
        actions={
          <>
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
            {canChangeStart ? (
              <>
                <button type="button" onClick={() => onEditStory(story)}>Change beginning</button>
                <button type="button" disabled={regenerating} onClick={() => void regenerateStart()}>
                  {regenerating ? 'Regenerating…' : 'Regenerate opening'}
                </button>
              </>
            ) : (
              <button type="button" disabled={regenerating} onClick={() => void regenerateLast()}>
                {regenerating ? 'Regenerating…' : 'Redo last turn'}
              </button>
            )}
            <button
              type="button"
              className={showLog ? 'facts-toggle active' : 'facts-toggle'}
              onClick={() => setShowLog((v) => !v)}
            >
              🖼 Image log{loggedTurns > 0 ? ` (${loggedTurns})` : ''}
            </button>
            <button
              type="button"
              className={showFacts ? 'facts-toggle active' : 'facts-toggle'}
              onClick={() => setShowFacts((v) => !v)}
            >
              📌 Pinned facts{story.pinned_facts.length > 0 ? ` (${story.pinned_facts.length})` : ''}
            </button>
            <button type="button" onClick={onHome}>Exit</button>
          </>
        }
      />
      <ErrorBanner message={error} onClose={() => setError(null)} />
      {showLog && (
        <section className="pinned-facts-panel">
          <h2>Image log — what the picture model was told</h2>
          <p className="pinned-facts-hint">
            One entry per turn that was drawn. A turn generated from text only says
            &quot;mode: text to image&quot;; a turn built from your photo says
            &quot;mode: edit&quot; and lists the pictures it used.
          </p>
          {loggedTurns === 0 ? (
            <p className="pinned-facts-empty">
              No picture generated with logging yet. The log is written when a picture is
              drawn, so pictures made before this button existed have none — press
              &quot;Repaint this picture&quot; on any picture to get one.
            </p>
          ) : (
            <div className="image-log-list">
              {story.turns
                .filter((turn) => turn.image_build_log)
                .map((turn) => (
                  <details key={turn.id} className="image-log-entry">
                    <summary>Turn {turn.index + 1} — {turn.state.scene}</summary>
                    <pre>{turn.image_build_log}</pre>
                  </details>
                ))}
            </div>
          )}
        </section>
      )}
      {showFacts && (
        <section className="pinned-facts-panel">
          <h2>Pinned facts</h2>
          <p className="pinned-facts-hint">
            Facts the narrator always remembers about your story. Delete a mistaken one and
            the narrator will forget it from the next turn on.
          </p>
          {story.pinned_facts.length === 0 ? (
            <p className="pinned-facts-empty">
              No pinned facts yet. Add one with the "Note to the narrator" field below the choices.
            </p>
          ) : (
            <ul className="pinned-facts-list">
              {story.pinned_facts.map((fact, index) => (
                <li key={`${index}-${fact}`} className="pinned-fact-row">
                  <span className="pinned-fact-text">{fact}</span>
                  <button
                    type="button"
                    className="link-button pinned-fact-delete"
                    disabled={factDeleting !== null}
                    onClick={() => void deletePinnedFact(index)}
                  >
                    {factDeleting === index ? 'Deleting…' : 'Delete'}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      <nav className="story-tabs" aria-label="Story sections">
        <button
          type="button"
          className={tab === 'story' ? 'tab-button active' : 'tab-button'}
          onClick={() => onTabChange('story')}
        >
          Story
        </button>
        <button
          type="button"
          className={tab === 'characters' ? 'tab-button active' : 'tab-button'}
          onClick={() => onTabChange('characters')}
        >
          Characters
        </button>
      </nav>
      {tab === 'characters' ? (
        <CharactersPanel
          storyId={storyId}
          refreshKey={story.turns.length}
          onCharacterUpdated={applyCharacterUpdate}
        />
      ) : (
        <>
          <div className="chat-feed" ref={feedRef} onScroll={saveFeedScroll}>
            <div className="chat-feed-inner">
              {story.turns.map((turn, i) => (
                <div
                  key={turn.id}
                  ref={i === story.turns.length - 1 ? (el) => { lastTurnTextRef.current = el; } : undefined}
                >
                  <TurnView
                    turn={turn}
                    introduced={characters.filter((c) => c.first_seen_turn_id === turn.id)}
                    updated={charactersWithNewLook(characters, turn.id)}
                    onPortraitUpdated={updateCharacter}
                  />
                </div>
              ))}
            </div>
            {ended && (
              <section className="ending-panel">
                <h2>The End</h2>
                <p>{lastTurn?.state.summary}</p>
                <div className="card-actions">
                  <button className="primary" type="button" onClick={onNewStory}>New story</button>
                  <button type="button" onClick={onHome}>Home</button>
                </div>
              </section>
            )}
          </div>
          {!ended &&
            (submitting ? (
              <LoadingIndicator />
            ) : (
              lastTurn?.choice && (
                <ChoicePanel
                  choice={lastTurn.choice}
                  disabled={submitting}
                  onSubmit={submitChoice}
                  draftKey={`roleplaygen.choiceDraft.${storyId}.${lastTurn.id}`}
                />
              )
            ))}
        </>
      )}
    </div>
  );
}

