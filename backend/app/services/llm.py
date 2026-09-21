import json
from typing import Any

import httpx

from ..config import Settings

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Ordered fallback list: if the chosen model is overloaded (503) or out of
# quota (429), the request is retried on the next model automatically.
MODEL_FALLBACK_ORDER = [
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
]


class LLMConfigurationError(RuntimeError):
    pass


class LLMResponseError(RuntimeError):
    pass


def _mock_contract(turn_number: int, max_turns: int | None, language: str, setting: str) -> dict[str, Any]:
    lang = language if language in ("Russian", "Kazakh") else "English"
    is_start = turn_number == 1
    should_end = max_turns is not None and turn_number >= max_turns
    decisive = max_turns is not None and not should_end and turn_number == max(2, max_turns // 2)
    mode = "binary" if decisive else ("open" if turn_number % 2 == 1 else "locked")
    state = _state(lang, turn_number, setting)
    narration = _narration(lang, turn_number, setting)
    if is_start:
        narration = _intro(lang, setting) + "\n\n" + narration

    if should_end:
        return {
            "narration": narration + "\n\n" + _ending_text(lang),
            "choice": None,
            "state": state,
            "is_ending": True,
            "image_prompt": f"solo, adult, traveler, {setting}, sunset, dramatic lighting, wide shot",
            "image_format": "wide",
        }

    options, prompt = _options(lang, mode, setting)
    image_format = "portrait" if turn_number % 2 == 0 else "wide"
    image_prompt = (
        f"1girl, solo, adult, traveler, cloak, standing, {setting}, detailed background, "
        + ("cowboy shot, looking at viewer" if image_format == "portrait" else "wide shot, scenery")
    )
    result: dict[str, Any] = {
        "narration": narration,
        "choice": {"mode": mode, "options": options, "allow_custom": mode == "open", "prompt": prompt},
        "state": state,
        "is_ending": False,
        "image_prompt": image_prompt,
        "image_format": image_format,
        "characters_in_scene": ["__hero__"],
    }
    if is_start:
        result["hero"] = {
            "name": None,
            "appearance_tags": "1girl, solo, adult, traveler, cloak, determined expression",
        }
        result["characters"] = [_mock_companion(lang)]
    return result


def _mock_companion(lang: str) -> dict[str, Any]:
    companions = {
        "English": ("Warden Hale", "local guide", "wary ally", "A scarred guide who knows every road and owes the hero a debt."),
        "Russian": ("Стражник Галка", "местный проводник", "настороженный союзник", "Проводник со шрамом, знающий все дороги и должный герою услугу."),
        "Kazakh": ("Күзетші Галка", "жергілікті жолсерік", "сақ одақтас", "Барлық жолды білетін, кейіпкерге қарыз тірі жолсерік."),
    }
    name, role, relationship, description = companions[lang]
    return {
        "name": name,
        "is_new": True,
        "role": role,
        "relationship": relationship,
        "description": description,
        "appearance_tags": "1boy, adult, short hair, weathered face, leather vest, scar",
    }


def _intro(lang: str, setting: str) -> str:
    intros = {
        "English": (
            f"Long before your story began, {setting} had its own legends — old roads, older debts, "
            "and rumors that travel faster than any ship.\n\n"
            "You arrive as a stranger, but your name already means something here. The role you carry "
            "shapes how doors open and which ones stay barred."
        ),
        "Russian": (
            f"Задолго до начала этой истории {setting} хранил свои легенды — старые дороги, "
            "ещё более старые долги и слухи, что бегут быстрее любых кораблей.\n\n"
            "Вы приезжаете чужаком, но ваше имя уже кое-что значит здесь. Ваша роль решает, "
            "какие двери открываются, а какие остаются запертыми."
        ),
        "Kazakh": (
            f"Бұл әңгіме басталмай тұрып, {setting} өз аңыздарын сақтап қалған — ескі жолдар, "
            "одан да ескі қарыздар және кез келген кемеден тез жүретін сыбыстар.\n\n"
            "Сіз бөтен адам ретінде келесіз, бірақ атыңыз бұл жерде әлдеқашан мағынаға ие. "
            "Рөліңіз қай есіктердің ашылатынын шешеді."
        ),
    }
    return intros[lang]


def _narration(lang: str, turn_number: int, setting: str) -> str:
    texts = {
        "English": (
            f"Turn {turn_number}. The air in {setting} tastes of rain and old smoke. Lantern light "
            "slides across wet stone as a figure detaches from the shadows — a watcher who has been "
            "waiting for someone exactly like you.\n\n"
            '"You walk loudly for someone with secrets," the stranger says, voice low and amused. '
            '"That can be fixed. What matters is whether you listen before you answer."\n\n'
            "Behind them, a narrow stair descends into lamplight and voices — a gathering that "
            "should not exist, planning something that should not be possible."
        ),
        "Russian": (
            f"Ход {turn_number}. Воздух в {setting} пахнет дождём и старым дымом. Свет фонарей "
            "скользит по мокрому камню, и из тени отделяется фигура — наблюдатель, который ждал "
            "именно вас.\n\n"
            "— Вы шумно ходите для человека с тайнами, — говорит незнакомец тихо и с усмешкой. "
            "— Это поправимо. Важно лишь, слушаете ли вы, прежде чем ответить.\n\n"
            "За его спиной узкая лестница уходит вниз, к свету и голосам — к собранию, которого "
            "не должно существовать, замышляющему невозможное."
        ),
        "Kazakh": (
            f"{turn_number}-жүріс. {setting} ауасында жаңбыр мен ескі түтіннің иісі бар. Шам жарығы "
            "жаңбырлы тасқа сырғанайды, ал көлеңкеден бір бейне бөлініп шығады — дәл сіз сияқты "
            "біреуді күткен бақылаушы.\n\n"
            "— Құпиясы бар адам үшін қатты жүресіз, — дейді бейтаныс төмен ғана күлкілі дауыспен. "
            "— Мұны түзетуге болады. Маңыздысы — жауап бермес бұрын тыңдайсыз ба.\n\n"
            "Оның артындағы тар баспалдақ жарық пен дауыстарға төмен түседі — болмауға тиіс жиналыс "
            "мүмкін емес нәрсені жоспарлап отыр."
        ),
    }
    return texts[lang]


def _ending_text(lang: str) -> str:
    endings = {
        "English": (
            "When the last echo fades, you understand the shape of what you chose. Some doors "
            "close forever; others you now hold the keys to.\n\n"
            "The story is over, but the road remembers you."
        ),
        "Russian": (
            "Когда стихает последнее эхо, вы понимаете, каким был ваш выбор. Одни двери "
            "закрываются навсегда; к другим у вас теперь есть ключи.\n\n"
            "История окончена, но дорога вас запомнит."
        ),
        "Kazakh": (
            "Соңғы жаңғырық басылғанда, таңдауыңыздың қалай болғанын түсінесіз. Кейбір есіктер "
            "мәңгі жабылады; басқаларының кілті енді сізде.\n\n"
            "Әңгіме бітті, бірақ жол сізді есте сақтайды."
        ),
    }
    return endings[lang]

    return endings[lang]


def _options(lang: str, mode: str, setting: str) -> tuple[list[dict[str, str]], str]:
    option_texts: dict[str, dict[str, list[str]]] = {
        "English": {
            "open": ["Approach the stranger openly", "Watch from the shadows first", "Ask about the gathering below", "Demand to know how they knew you"],
            "locked": ["Follow the stranger down the stair", "Refuse and walk away", "Search the stranger's belongings"],
            "binary": ["Trust the stranger completely", "Turn your back forever"],
        },
        "Russian": {
            "open": ["Подойти к незнакомцу открыто", "Сначала понаблюдать из тени", "Спросить о собрании внизу", "Потребовать объяснить, откуда вас знают"],
            "locked": ["Пойти за незнакомцем по лестнице", "Отказаться и уйти", "Обыскать вещи незнакомца"],
            "binary": ["Довериться незнакомцу полностью", "Навсегда повернуться спиной"],
        },
        "Kazakh": {
            "open": ["Бейтанысқа ашық жақындау", "Алдымен көлеңкеден бақылау", "Төмендегі жиналыс туралы сұрау", "Сізді қайдан білетінін түсіндіруін талап ету"],
            "locked": ["Бейтанысқа еріп баспалдақпен түсу", "Бас тартып кету", "Бейтаныстың заттарын тексеру"],
            "binary": ["Бейтанысқа толық сену", "Мәңгілікке артқа бұрылу"],
        },
    }
    prompts = {
        "English": {"open": "What will you do?", "locked": "Choose your path.", "binary": "This is a decisive moment."},
        "Russian": {"open": "Что будете делать?", "locked": "Выберите путь.", "binary": "Это решающий момент."},
        "Kazakh": {"open": "Не істейсіз?", "locked": "Жолыңызды таңдаңыз.", "binary": "Бұл шешуші сәт."},
    }
    texts = option_texts[lang][mode]
    letters = ["a", "b", "c", "d"]
    return [{"id": letters[i], "text": text} for i, text in enumerate(texts)], prompts[lang][mode]


def _state(lang: str, turn_number: int, setting: str) -> dict[str, Any]:
    scenes = {"English": f"{setting} — turn {turn_number}", "Russian": f"{setting} — ход {turn_number}", "Kazakh": f"{setting} — {turn_number}-жүріс"}
    summaries = {
        "English": f"Turn {turn_number}: the hero navigated {setting} and met a key figure.",
        "Russian": f"Ход {turn_number}: герой прошёл через {setting} и встретил важную фигуру.",
        "Kazakh": f"{turn_number}-жүріс: кейіпкер {setting} арқылы өтіп, маңызды тұлғамен кездесті.",
    }
    facts = {
        "English": [f"A stranger in {setting} knew the hero's name."],
        "Russian": [f"Незнакомец в {setting} знал имя героя."],
        "Kazakh": [f"{setting} ішіндегі бейтаныс кейіпкердің атын білді."],
    }
    return {"scene": scenes[lang], "summary": summaries[lang], "facts": facts[lang]}


def call_model(
    system_prompt: str,
    user_prompt: str,
    settings: Settings,
    mock_index: int = 0,
    mock_language: str = "English",
    mock_setting: str = "a mysterious world",
    mock_max_turns: int | None = None,
    model_name: str | None = None,
) -> str:
    if settings.mock_llm:
        turn_number = mock_index + 1
        return json.dumps(
            _mock_contract(turn_number, mock_max_turns, mock_language, mock_setting),
            ensure_ascii=False,
        )

    if not settings.gemini_api_key:
        raise LLMConfigurationError(
            "Gemini API key is not configured. Add GEMINI_API_KEY to .env or enable MOCK_LLM=true."
        )

    chosen_model = model_name or settings.model_name
    candidates = [chosen_model] + [m for m in MODEL_FALLBACK_ORDER if m != chosen_model]
    last_error: LLMResponseError | None = None
    for candidate in candidates:
        try:
            return _call_gemini(candidate, system_prompt, user_prompt, settings)
        except LLMResponseError as exc:
            if "503" in str(exc) or "429" in str(exc):
                last_error = exc
                continue
            raise
    raise last_error or LLMResponseError("The AI service returned an error.")


def _call_gemini(model: str, system_prompt: str, user_prompt: str, settings: Settings) -> str:
    url = f"{GEMINI_API_BASE}/{model}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "maxOutputTokens": settings.max_tokens,
            "temperature": 0.9,
            "responseMimeType": "application/json",
        },
    }
    try:
        response = httpx.post(
            url,
            headers={"Content-Type": "application/json", "X-goog-api-key": settings.gemini_api_key},
            json=payload,
            timeout=120.0,
        )
    except httpx.HTTPError as exc:
        raise LLMResponseError(f"The AI service could not be reached: {exc}") from exc

    if response.status_code != 200:
        detail = ""
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = response.text[:300]
        raise LLMResponseError(f"The AI service returned an error ({response.status_code}): {detail}")

    data = response.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMResponseError("The AI service returned an unexpected response shape.") from exc
    if not text.strip():
        raise LLMResponseError("The AI service returned no text.")
    return text
