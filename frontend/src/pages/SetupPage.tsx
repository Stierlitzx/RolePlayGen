import { FormEvent, useEffect, useState } from 'react';
import { api, type Language, type Length, type SetupOptions, type Story } from '../api';
import ErrorBanner from '../components/ErrorBanner';
import LoadingIndicator from '../components/LoadingIndicator';

interface Props {
  onBack: () => void;
  onStarted: (story: Story) => void;
  editingStory?: Story | null;
}

export default function SetupPage({ onBack, onStarted, editingStory }: Props) {
  const isEditing = Boolean(editingStory);
  const initial = editingStory?.settings as Record<string, unknown> | undefined;
  const [options, setOptions] = useState<SetupOptions | null>(null);
  const [setting, setSetting] = useState(String(initial?.setting ?? 'Medieval kingdom'));
  const [customSetting, setCustomSetting] = useState(String(initial?.custom_setting ?? ''));
  const [genres, setGenres] = useState<string[]>(
    Array.isArray(initial?.genres) ? (initial.genres as string[]) : ['Fantasy'],
  );
  const [tone, setTone] = useState(String(initial?.tone ?? 'Dark'));
  const [heroRole, setHeroRole] = useState(String(initial?.hero_role ?? ''));
  const [heroName, setHeroName] = useState(String(initial?.hero_name ?? ''));
  const [heroAppearance, setHeroAppearance] = useState(String(initial?.hero_appearance ?? ''));
  const [length, setLength] = useState<Length>((initial?.length as Length) ?? 'short');
  const [customTurns, setCustomTurns] = useState(Number(initial?.custom_turns ?? 50));
  const [model, setModel] = useState(String(initial?.model ?? ''));
  const [restrictions, setRestrictions] = useState(String(initial?.content_restrictions ?? ''));
  const [language, setLanguage] = useState<Language>((initial?.language as Language) ?? 'Russian');
  const [customDetails, setCustomDetails] = useState(String(initial?.custom_details ?? ''));
  const [settingCulture, setSettingCulture] = useState(String(initial?.setting_culture ?? ''));
  const [namingCulture, setNamingCulture] = useState(String(initial?.naming_culture ?? ''));
  const [introExposition, setIntroExposition] = useState(Boolean(initial?.intro_exposition ?? true));
  const [ageRating, setAgeRating] = useState(String(initial?.age_rating ?? ''));
  const [explicitSexual, setExplicitSexual] = useState(Boolean(initial?.explicit_sexual ?? false));
  const [graphicViolence, setGraphicViolence] = useState(Boolean(initial?.graphic_violence ?? false));
  const [imageStyle, setImageStyle] = useState(String(initial?.image_style ?? ''));
  const [narratorStyle, setNarratorStyle] = useState(String(initial?.narrator_style ?? ''));
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .setupOptions()
      .then((value) => {
        setOptions(value);
        // Defaults apply both to new stories and to old stories being edited
        // that predate these fields.
        setAgeRating((current) => current || value.default_age_rating);
        setImageStyle((current) => current || value.default_image_style);
        setNarratorStyle((current) => current || value.default_narrator_style);
        if (!isEditing) {
          setSetting(value.settings[0]);
          setGenres([value.genres[0]]);
          setTone(value.tones[0]);
          setLanguage(value.languages[0]);
          setSettingCulture(value.cultures[0]);
          setModel(value.default_model);
        } else if (!model) {
          setModel(value.default_model);
        }
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Could not load setup options.'),
      )
      .finally(() => setLoading(false));
  }, []);

  const toggleGenre = (genre: string) => {
    const maxGenres = options?.max_genres ?? 3;
    setGenres((current) => {
      if (current.includes(genre)) return current.filter((item) => item !== genre);
      return [...current, genre].slice(-maxGenres);
    });
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (genres.length === 0 || starting) return;
    setStarting(true);
    setError(null);
    const payload = {
      setting,
      custom_setting: setting === 'Custom' ? customSetting.trim() : null,
      genres,
      tone,
      hero_role: heroRole.trim() || null,
      hero_name: heroName.trim() || null,
      hero_appearance: heroAppearance.trim() || null,
      length,
      custom_turns: length === 'custom' ? customTurns : null,
      model: model || null,
      content_restrictions: restrictions.trim() || null,
      language,
      custom_details: customDetails.trim() || null,
      setting_culture: settingCulture || null,
      naming_culture: namingCulture.trim() || null,
      intro_exposition: introExposition,
      age_rating: ageRating || null,
      explicit_sexual: ageRating === '18+' && explicitSexual,
      graphic_violence: ageRating === '18+' && graphicViolence,
      image_style: imageStyle || null,
      narrator_style: narratorStyle || null,
    };
    try {
      const story = isEditing && editingStory
        ? await api.updateStory(editingStory.id, payload)
        : await api.createStory(payload);
      onStarted(story);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the story.');
    } finally {
      setStarting(false);
    }
  };

  if (loading) return <LoadingIndicator text="Loading story options…" />;
  if (!options) {
    return (
      <main className="page narrow-page">
        <ErrorBanner message={error} />
        <button type="button" onClick={onBack}>Home</button>
      </main>
    );
  }

  return (
    <main className="page setup-page">
      <button type="button" className="link-button" onClick={onBack}>← Home</button>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Story setup</p>
          <h1>Choose the world</h1>
        </div>
      </div>
      {!options.ai_configured && !options.mock_llm && (
        <div className="warning-banner">
          Gemini is not configured. Add GEMINI_API_KEY to <code>.env</code> (free key at{' '}
          aistudio.google.com/api-keys), or set <code>MOCK_LLM=true</code> for local development.
        </div>
      )}
      <ErrorBanner message={error} onClose={() => setError(null)} />
      <form className="setup-form" onSubmit={(event) => void submit(event)}>
        <label>
          Setting
          <select value={setting} onChange={(event) => setSetting(event.target.value)}>
            {options.settings.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
        {setting === 'Custom' && (
          <label>
            Custom setting
            <textarea
              value={customSetting}
              maxLength={1000}
              required
              onChange={(event) => setCustomSetting(event.target.value)}
            />
          </label>
        )}
        <label>
          Custom details (optional)
          <textarea
            value={customDetails}
            maxLength={5000}
            placeholder="Plot premise, tone details, characters you want present, relationships, factions, a conflict to start from…"
            onChange={(event) => setCustomDetails(event.target.value)}
          />
        </label>
        <fieldset>
          <legend>Genre (choose up to {options.max_genres})</legend>
          <div className="pill-grid">
            {(ageRating === '18+'
              ? [...options.genres.filter((g) => g !== 'Random'), ...options.adult_genres, 'Random']
              : options.genres
            ).map((genre) => (
              <button
                key={genre}
                type="button"
                className={genres.includes(genre) ? 'pill selected' : 'pill'}
                onClick={() => toggleGenre(genre)}
              >
                {genre}
              </button>
            ))}
          </div>
        </fieldset>
        <div className="form-grid">
          <label>
            Tone
            <select value={tone} onChange={(event) => setTone(event.target.value)}>
              {options.tones.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Length
            <select value={length} onChange={(event) => setLength(event.target.value as Length)}>
              {options.lengths.map((item) => (
                <option key={item.value} value={item.value}>{item.label}</option>
              ))}
            </select>
          </label>
          {length === 'custom' && (
            <label>
              Number of turns (50-500)
              <input
                type="number"
                min={50}
                max={500}
                value={customTurns}
                onChange={(event) => setCustomTurns(Number(event.target.value))}
              />
            </label>
          )}
          <label>
            AI model
            <select value={model} onChange={(event) => setModel(event.target.value)}>
              {options.models.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Hero role (optional)
            <textarea value={heroRole} maxLength={1000} onChange={(event) => setHeroRole(event.target.value)} />
          </label>
          <label>
            Hero name (optional)
            <input value={heroName} maxLength={200} onChange={(event) => setHeroName(event.target.value)} />
          </label>
          <label>
            Hero appearance (optional — the narrator bases the hero's look and portrait on it)
            <textarea value={heroAppearance} maxLength={1000} onChange={(event) => setHeroAppearance(event.target.value)} />
          </label>
          <label>
            Story language
            <select value={language} onChange={(event) => setLanguage(event.target.value as Language)}>
              {options.languages.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Setting culture
            <select value={settingCulture} onChange={(event) => setSettingCulture(event.target.value)}>
              {options.cultures.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Character naming culture (optional)
            <select value={namingCulture} onChange={(event) => setNamingCulture(event.target.value)}>
              <option value="">Same as setting culture</option>
              {options.cultures
                .filter((item) => item !== 'Match story language')
                .map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Age rating
            <select
              value={ageRating}
              onChange={(event) => {
                const value = event.target.value;
                setAgeRating(value);
                if (value !== '18+') {
                  // adult genres and flags are 18+-only
                  setExplicitSexual(false);
                  setGraphicViolence(false);
                  setGenres((current) =>
                    current.filter((genre) => !options.adult_genres.includes(genre)),
                  );
                }
              }}
            >
              {options.age_ratings.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Narrator style
            <select value={narratorStyle} onChange={(event) => setNarratorStyle(event.target.value)}>
              {options.narrator_styles.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Image style
            <select value={imageStyle} onChange={(event) => setImageStyle(event.target.value)}>
              {options.image_styles.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
        </div>
        {ageRating === '18+' && (
          <div className="adult-options">
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={explicitSexual}
                onChange={(event) => setExplicitSexual(event.target.checked)}
              />
              Explicit sexual content (porn-parody / hentai level)
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={graphicViolence}
                onChange={(event) => setGraphicViolence(event.target.checked)}
              />
              Graphic violence and gore
            </label>
          </div>
        )}
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={introExposition}
            onChange={(event) => setIntroExposition(event.target.checked)}
          />
          Explain the world and the hero before the story begins
        </label>
        <label>
          Content restrictions (optional)
          <textarea
            value={restrictions}
            maxLength={2000}
            onChange={(event) => setRestrictions(event.target.value)}
          />
        </label>
        <button className="primary start-button" type="submit" disabled={starting || genres.length === 0}>
          {starting ? (isEditing ? 'Saving…' : 'Starting…') : isEditing ? 'Save changes' : 'Start'}
        </button>
      </form>
      {starting && <LoadingIndicator text="Creating the first turn…" />}
    </main>
  );
}
