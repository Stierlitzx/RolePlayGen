import TopBar from '../components/ui/TopBar';

interface Props {
  onNewStory: () => void;
}

/** The home content area. The story list itself lives in the app shell's
 * sidebar (present on every screen); this is just the welcome panel. */
export default function HomePage({ onNewStory }: Props) {
  return (
    <div className="page-column">
      <TopBar
        title="Your stories"
        subtitle="Interactive fiction"
        actions={
          <button className="primary" type="button" onClick={onNewStory}>
            New story
          </button>
        }
      />
      <div className="content-scroll">
        <section className="empty-state">
          <h2>Welcome back</h2>
          <p>Pick a story in the sidebar, or configure a new world and let the narrator begin.</p>
          <button className="primary" type="button" onClick={onNewStory}>
            Start a new story
          </button>
        </section>
      </div>
    </div>
  );
}
