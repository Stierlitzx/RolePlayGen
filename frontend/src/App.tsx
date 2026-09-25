import { useCallback, useEffect, useState } from 'react';
import { api, type CharacterInfo, type Story, type StorySummary } from './api';
import ErrorBanner from './components/ErrorBanner';
import AppShell from './components/ui/AppShell';
import HomePage from './pages/HomePage';
import SetupPage from './pages/SetupPage';
import StoryPage, { type StoryTab } from './pages/StoryPage';

type Route =
  | { page: 'home' }
  | { page: 'setup' }
  | { page: 'edit'; story: Story }
  | { page: 'story'; storyId: number };

const STORAGE_KEY = 'roleplaygen.currentStoryId';

export default function App() {
  const [route, setRoute] = useState<Route>(() => {
    const saved = Number(localStorage.getItem(STORAGE_KEY));
    return Number.isInteger(saved) && saved > 0 ? { page: 'story', storyId: saved } : { page: 'home' };
  });
  // The sidebar needs the story list on every screen, so it lives here.
  const [stories, setStories] = useState<StorySummary[]>([]);
  const [storiesError, setStoriesError] = useState<string | null>(null);
  // Reported up by StoryPage so the sidebar can show the open story's cast.
  const [sidebarCharacters, setSidebarCharacters] = useState<CharacterInfo[]>([]);
  const [storyTab, setStoryTab] = useState<StoryTab>('story');

  const refreshStories = useCallback(async () => {
    try {
      setStories(await api.stories());
      setStoriesError(null);
    } catch (err) {
      setStoriesError(err instanceof Error ? err.message : 'Could not load stories.');
    }
  }, []);

  useEffect(() => {
    void refreshStories();
  }, [refreshStories, route]);

  useEffect(() => {
    if (route.page === 'story') {
      localStorage.setItem(STORAGE_KEY, String(route.storyId));
    } else if (route.page !== 'edit') {
      localStorage.removeItem(STORAGE_KEY);
    }
    if (route.page !== 'story') {
      setSidebarCharacters([]);
      setStoryTab('story');
    }
  }, [route]);

  const deleteStory = async (story: StorySummary) => {
    if (!window.confirm(`Delete “${story.title}” and all its turns?`)) return;
    setStoriesError(null);
    try {
      await api.deleteStory(story.id);
      localStorage.removeItem(STORAGE_KEY);
      if (route.page === 'story' && route.storyId === story.id) {
        setRoute({ page: 'home' });
      }
      await refreshStories();
    } catch (err) {
      setStoriesError(err instanceof Error ? err.message : 'Could not delete the story.');
    }
  };

  const openStory = (id: number) => {
    setStoryTab('story');
    setRoute({ page: 'story', storyId: id });
  };

  let page: React.ReactNode;
  if (route.page === 'setup' || route.page === 'edit') {
    const editing = route.page === 'edit' ? route.story : null;
    page = (
      <SetupPage
        editingStory={editing}
        onBack={() =>
          setRoute(editing ? { page: 'story', storyId: editing.id } : { page: 'home' })
        }
        onStarted={(story: Story) => setRoute({ page: 'story', storyId: story.id })}
      />
    );
  } else if (route.page === 'story') {
    page = (
      <StoryPage
        storyId={route.storyId}
        tab={storyTab}
        onTabChange={setStoryTab}
        onHome={() => setRoute({ page: 'home' })}
        onNewStory={() => setRoute({ page: 'setup' })}
        onEditStory={(story: Story) => setRoute({ page: 'edit', story })}
        onCharactersChange={setSidebarCharacters}
      />
    );
  } else {
    page = <HomePage onNewStory={() => setRoute({ page: 'setup' })} />;
  }

  return (
    <AppShell
      stories={stories}
      activeStoryId={route.page === 'story' ? route.storyId : undefined}
      characters={route.page === 'story' ? sidebarCharacters : undefined}
      onOpenStory={openStory}
      onNewStory={() => setRoute({ page: 'setup' })}
      onDeleteStory={(story) => void deleteStory(story)}
      onHome={() => setRoute({ page: 'home' })}
      onCharacterClick={() => setStoryTab('characters')}
    >
      <ErrorBanner message={storiesError} onClose={() => setStoriesError(null)} />
      {page}
    </AppShell>
  );
}
