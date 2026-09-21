import { useEffect, useState } from 'react';
import type { Story } from './api';
import HomePage from './pages/HomePage';
import SetupPage from './pages/SetupPage';
import StoryPage from './pages/StoryPage';

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

  useEffect(() => {
    if (route.page === 'story') {
      localStorage.setItem(STORAGE_KEY, String(route.storyId));
    } else if (route.page !== 'edit') {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [route]);

  if (route.page === 'setup' || route.page === 'edit') {
    const editing = route.page === 'edit' ? route.story : null;
    return (
      <SetupPage
        editingStory={editing}
        onBack={() =>
          setRoute(editing ? { page: 'story', storyId: editing.id } : { page: 'home' })
        }
        onStarted={(story: Story) => setRoute({ page: 'story', storyId: story.id })}
      />
    );
  }

  if (route.page === 'story') {
    return (
      <StoryPage
        storyId={route.storyId}
        onHome={() => setRoute({ page: 'home' })}
        onNewStory={() => setRoute({ page: 'setup' })}
        onEditStory={(story: Story) => setRoute({ page: 'edit', story })}
      />
    );
  }

  return (
    <HomePage
      onNewStory={() => setRoute({ page: 'setup' })}
      onOpenStory={(id: number) => setRoute({ page: 'story', storyId: id })}
    />
  );
}
