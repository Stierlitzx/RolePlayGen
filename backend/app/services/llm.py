import json
import logging
from typing import Any

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Ordered fallback list: if the chosen model is overloaded (503) or out of
# quota (429), the request is retried on the next model automatically.
MODEL_FALLBACK_ORDER = [
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
]


# Fiction often brushes against Gemini's default safety filters (dark themes,
# violence, romance). BLOCK_ONLY_HIGH keeps the true hard limits while not
# tripping on ordinary dramatic narration. The app's own rating system sits on
# top of this and governs what the narrator is allowed to write.
SAFETY_SETTINGS = [
    {"category": category, "threshold": "BLOCK_ONLY_HIGH"}
    for category in (
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
    )
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

    provider = (settings.llm_provider or "gemini").lower()
    if provider == "openai":
        if not settings.openai_base_url:
            raise LLMConfigurationError(
                "OPENAI_BASE_URL is not configured. Point it at your local server "
                "(e.g. http://localhost:11434/v1 for Ollama)."
            )
        return _call_openai(model_name or settings.openai_model, system_prompt, user_prompt, settings)
    if provider != "gemini":
        raise LLMConfigurationError(
            f"Unknown LLM_PROVIDER '{settings.llm_provider}' (expected 'gemini' or 'openai')."
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
        "safetySettings": SAFETY_SETTINGS,
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
    prompt_block = (data.get("promptFeedback") or {}).get("blockReason")
    if prompt_block:
        raise LLMResponseError(
            f"The model refused the prompt (reason: {prompt_block}). Soften the setup wording "
            "(custom details, hero description) or lower the story's age rating."
        )
    candidates = data.get("candidates") or []
    finish_reason = candidates[0].get("finishReason") if candidates else None
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMResponseError(_finish_reason_message(finish_reason, candidates)) from exc
    if not text.strip():
        raise LLMResponseError(_finish_reason_message(finish_reason, candidates))
    return text


def _call_openai(model: str, system_prompt: str, user_prompt: str, settings: Settings) -> str:
    """Any OpenAI-compatible chat endpoint (Ollama, LM Studio, llama.cpp).

    Local servers are slower than the cloud, so the timeout is generous; there
    is no safety layer here — content is governed solely by our narrator prompt.
    """
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.9,
        "max_tokens": settings.max_tokens,
        "response_format": {"type": "json_object"},
        # Reasoning models (Nemotron, Qwen-thinking, …) otherwise burn the
        # token budget on chain-of-thought — or leak it into the content and
        # break the JSON contract. Non-reasoning servers ignore this field.
        "reasoning": {"enabled": False},
    }
    headers = {"Content-Type": "application/json"}
    if settings.openai_api_key:
        headers["Authorization"] = f"Bearer {settings.openai_api_key}"
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=300.0)
    except httpx.HTTPError as exc:
        raise LLMResponseError(
            f"The model server could not be reached at {settings.openai_base_url}: {exc}. "
            "Start Ollama/LM Studio, check the cloud endpoint, or switch LLM_PROVIDER back to gemini."
        ) from exc

    if response.status_code != 200:
        detail = ""
        try:
            err = response.json().get("error", {})
            if isinstance(err, dict):
                detail = str(err.get("message", ""))
                metadata = err.get("metadata") or {}
                raw = metadata.get("raw") if isinstance(metadata, dict) else None
                if raw:
                    detail += f" | upstream: {str(raw)[:200]}"
            else:
                detail = str(err)
        except ValueError:
            detail = response.text[:300]
        hint = ""
        if response.status_code == 429:
            hint = " Rate limit hit — free models are shared; wait a bit and retry."
        raise LLMResponseError(f"The model server returned an error ({response.status_code}): {detail}{hint}")

    data = response.json()
    # OpenRouter can return HTTP 200 with an error body when the upstream
    # provider fails mid-generation.
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        message_text = err.get("message", "") if isinstance(err, dict) else str(err)
        raise LLMResponseError(f"The model server returned an error: {message_text}")
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning(
            "openai-compatible response had unexpected shape: %.500s",
            json.dumps(data, ensure_ascii=False, default=str),
        )
        raise LLMResponseError("The model server returned an unexpected response shape.") from exc
    if not text or not str(text).strip():
        raise LLMResponseError("The model server returned no text.")
    return str(text)


def _finish_reason_message(finish_reason: str | None, candidates: list[Any]) -> str:
    """Human-readable error for responses without usable text.

    A safety block used to surface as "unexpected response shape"; name the real
    cause so the player knows what to change.
    """
    if finish_reason == "SAFETY":
        ratings = (candidates[0].get("safetyRatings") or []) if candidates else []
        flagged = [
            str(rating["category"]).replace("HARM_CATEGORY_", "").replace("_", " ").lower()
            for rating in ratings
            if rating.get("probability") in ("MEDIUM", "HIGH") and rating.get("category")
        ]
        detail = f" ({', '.join(flagged)})" if flagged else ""
        return (
            f"The model blocked this turn as unsafe{detail}. Gemini's own limits apply on top of "
            "the story's age rating — soften the scene or the setup wording and try again."
        )
    if finish_reason == "MAX_TOKENS":
        return "The model's answer did not fit the token limit. Try again or raise MAX_TOKENS in .env."
    if finish_reason == "RECITATION":
        return "The model stopped its answer to avoid reproducing existing text. Try again."
    if finish_reason:
        return f"The model stopped without producing text (reason: {finish_reason}). Try again."
    return "The AI service returned an unexpected response shape."
