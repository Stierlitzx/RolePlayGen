import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { CharacterInfo, Turn } from '../api';
import TurnView from './TurnView';

function makeTurn(overrides: Partial<Turn>): Turn {
  return {
    id: 1,
    story_id: 1,
    index: 2,
    player_input_type: 'option',
    player_input_text: 'Charge in',
    note_text: null,
    note_type: null,
    narration: 'The guards raise their halberds.',
    choice: null,
    state: { scene: 'Courtyard', summary: 'A fight begins.', facts: [] },
    is_ending: false,
    image_status: 'none',
    image_format: 'wide',
    image_url: null,
    image_error: null,
    image_build_log: null,
    created_at: '2026-09-24T00:00:00Z',
    ...overrides,
  };
}

function makeCharacter(overrides: Partial<CharacterInfo>): CharacterInfo {
  return {
    id: 1,
    story_id: 1,
    name: 'Kaelen',
    is_hero: false,
    role: 'sky pirate captain',
    relationship: 'reluctant ally',
    description: 'Sharp-tongued captain.',
    first_seen_turn_id: 1,
    portrait_status: 'none',
    portrait_url: null,
    portrait_error: null,
    portrait_build_log: null,
    photo_url: null,
    portrait_history: [],
    created_at: '2026-09-24T00:00:00Z',
    ...overrides,
  };
}

afterEach(cleanup);

describe('TurnView', () => {
  it('shows the narrator note next to the player action', () => {
    render(<TurnView turn={makeTurn({ note_text: 'my character has no lighter', note_type: 'fact' })} />);
    expect(screen.getByText(/my character has no lighter/)).toBeInTheDocument();
  });

  it('renders no note element when the turn has none', () => {
    const { container } = render(<TurnView turn={makeTurn({})} />);
    expect(container.querySelector('.turn-note')).toBeNull();
  });

  it('renders no note on the start turn even if one were stored', () => {
    const { container } = render(
      <TurnView turn={makeTurn({ player_input_type: 'start', player_input_text: null, note_text: 'x' })} />,
    );
    expect(container.querySelector('.turn-note')).toBeNull();
  });

  it('shows a new-look portrait under the turn it happened in', () => {
    render(
      <TurnView
        turn={makeTurn({})}
        updated={[
          makeCharacter({
            portrait_status: 'done',
            portrait_url: '/media/1/char_1_v2.png',
            portrait_history: [
              { turn_id: 1, portrait_url: '/media/1/char_1.png', current: false },
              { turn_id: 2, portrait_url: '/media/1/char_1_v2.png', current: true },
            ],
          }),
        ]}
      />,
    );
    expect(screen.getByText('New look')).toBeInTheDocument();
    expect(screen.getByAltText('Portrait of Kaelen')).toHaveAttribute('src', '/media/1/char_1_v2.png');
    expect(screen.getByText(/sky pirate captain/)).toBeInTheDocument();
  });

  it('shows no portrait row when nothing changed on the turn', () => {
    const { container } = render(<TurnView turn={makeTurn({})} updated={[]} />);
    expect(container.querySelector('.introduced-row')).toBeNull();
  });
});
