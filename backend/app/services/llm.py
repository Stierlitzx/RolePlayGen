import json
import logging
import re
from typing import Any

import httpx

from ..config import Settings
from ..setup_options import GENDER_TAGS
from .image_tags import clean_tag_string, has_cyrillic

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# Named cloud providers on the OpenAI-compatible protocol (see config.py).
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MISTRAL_BASE_URL = "https://api.mistral.ai/v1"

# Groq's free tier enforces ~1000 output tokens/minute per organization and
# rejects requests whose expected output exceeds the remaining budget
# (429 "Request too large"). Cap Groq turns under the limit — a 350-700 word
# turn still fits, it just lands at the shorter end; other providers get the
# full MAX_TOKENS.
GROQ_MAX_OUTPUT_TOKENS = 950

# Free OpenRouter models are a shared, often congested pool: on 429/404/503
# the request is retried on the next free model automatically. The catalog
# changes often; checked against the live API 2026-09-24.
OPENROUTER_FALLBACK_ORDER = [
    "qwen/qwen3.8-27b:free",
    "z-ai/glm-5.2:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
]

# Mistral's Experiment tier rate-limits per model class, and the popular ones
# (medium, small) are chronically congested (429) while ministral-* answers —
# verified live 2026-09-24. Same fallback-chain treatment as OpenRouter.
MISTRAL_FALLBACK_ORDER = [
    "mistral-medium-latest",
    "mistral-small-latest",
    "ministral-14b-latest",
    "ministral-8b-latest",
]

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


def _mock_hero_tags(appearance: str, gender: str) -> str:
    """The mock hero's appearance tags: gender tag + adult + the player's own
    description. Freeform prose becomes comma-separated tags, so a described
    hero actually shows up in portraits and scenes instead of the generic
    traveler look. "fully clothed" is appended last as an overridable DEFAULT:
    with no outfit tags at all (e.g. a non-English description the image model
    can't read) it tends to render the hero nude. A plot-driven nude look still
    works — portrait_update replaces the tags wholesale, and the scene assembly
    strips the guard when the narrator tags an explicit scene as nude."""
    gender_tag = GENDER_TAGS.get(gender or "", "1girl")
    tags = [gender_tag, "solo", "adult"]
    if appearance.strip():
        details = [
            part.strip()[:60]
            for part in re.split(r"[.,\n;]+", appearance)
            if part.strip()
        ]
        if details:
            tags.extend(details[:14])
        else:
            tags.extend(["traveler", "cloak", "determined expression"])
    else:
        tags.extend(["traveler", "cloak", "determined expression"])
    tags.append("fully clothed")
    return ", ".join(tags)


# The mock narrator classifies a player note with the same wording heuristic a
# real narrator is instructed to use: words about the world's future action
# make an event, everything else is treated as a lasting state (a fact).
_MOCK_EVENT_WORDS = (
    "attack", "ambush", "appear", "arrive", "suddenly", "happen", "start",
    "begin", "rain", "storm", "explode", "come ", "comes ",
    "напад", "атак", "появ", "внезапн", "начн", "придёт", "приход", "дождь", "пусть",
    "келеді", "келсін", "пайда",
)


def _mock_extract_note(user_prompt: str) -> str | None:
    """Pull the PLAYER NOTE block out of the turn message; None = no note."""
    match = re.search(r'PLAYER NOTE FOR THIS TURN[^\n]*\n(.*?)\n\s*\n', user_prompt, re.DOTALL)
    if not match:
        return None
    note = match.group(1).strip()
    return None if note in ("", "None") else note


def _mock_note_classification(note: str) -> tuple[str, str]:
    lowered = note.lower()
    if any(word in lowered for word in _MOCK_EVENT_WORDS):
        return "event", note
    return "fact", note


def _mock_contract(turn_number: int, max_turns: int | None, language: str, setting: str,
                   hero_appearance: str = "", hero_gender: str = "", seed: int = 0) -> dict[str, Any]:
    lang = language if language in ("Russian", "Kazakh") else "English"
    is_start = turn_number == 1
    should_end = max_turns is not None and turn_number >= max_turns
    decisive = max_turns is not None and not should_end and turn_number == max(2, max_turns // 2)
    mode = "binary" if decisive else ("open" if turn_number % 2 == 1 else "locked")
    # The seed (the story id) rotates openings, scenes, companions and options,
    # so two mock stories no longer play out as the same scripted episode.
    scene_index = (seed + turn_number - 1) % 3
    state = _state(lang, turn_number, setting, scene_index)
    narration = _narration(lang, scene_index, turn_number)
    if is_start:
        narration = _intro(lang, setting, seed) + "\n\n" + narration

    if should_end:
        return {
            "narration": narration + "\n\n" + _ending_text(lang),
            "choice": None,
            "state": state,
            "is_ending": True,
            "image_prompt": "solo, traveler, sunset, dramatic lighting, wide shot",
            "image_format": "wide",
        }

    options, prompt = _options(lang, mode, scene_index)
    image_format = "portrait" if turn_number % 2 == 0 else "wide"
    # The hero's stored appearance tags are spliced into every scene by the
    # backend — the mock scene prompt only adds camera, place and mood.
    image_prompt = (
        f"standing, {setting}, detailed background, "
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
        pose, expression = _MOCK_HERO_POSES[seed % len(_MOCK_HERO_POSES)]
        result["hero"] = {
            "name": None,
            "appearance_tags": _mock_hero_tags(hero_appearance, hero_gender),
            "pose": pose,
            "expression": expression,
        }
        # Roughly every fourth mock story opens with the hero alone — no guide,
        # no stranger, just the player and the world.
        if seed % 4 != 3:
            result["characters"] = [_mock_companion(lang, seed)]
    return result


# The hero's first portrait is posed like every other portrait — this rotation
# exercises the narrator-supplied pose path and keeps two mock stories from
# opening on the same standing-at-the-camera card.
_MOCK_HERO_POSES: list[tuple[str, str]] = [
    ("hand on the weapon hilt, glancing over the shoulder, three-quarter view", "wary determination"),
    ("one hand on hip, leaning against a wall, looking at viewer", "confident smirk"),
    ("arms crossed, from the side, looking away", "guarded"),
    ("mid-stride, looking at viewer", "curious half-smile"),
]


# Pool of possible first companions, rotated by the story seed. Deliberately
# varied in age, build and manner — the old single "scarred guide" made every
# mock story open with the same face. Appearance tags stay English (danbooru
# style) in every language.
_MOCK_COMPANIONS: dict[str, list[tuple[str, str, str, str, str]]] = {
    "English": [
        ("Warden Hale", "local guide", "wary ally",
         "A scarred guide who knows every road and owes the hero a debt.",
         "1boy, adult, short hair, weathered face, leather vest, scar"),
        ("Sister Maren", "itinerant healer", "curious stranger",
         "A sharp-eyed healer who asks too many questions and bandages wounds without being asked.",
         "1girl, adult, long braided hair, freckles, healer robe, satchel"),
        ("Barto Quill", "tavern keeper", "friendly opportunist",
         "A broad, laughing tavern keeper who trades in rumors as much as in ale.",
         "1boy, adult, overweight, bald, bushy beard, apron, rolled sleeves"),
    ],
    "Russian": [
        ("Стражник Галка", "местный проводник", "настороженный союзник",
         "Проводник со шрамом, знающий все дороги и должный герою услугу.",
         "1boy, adult, short hair, weathered face, leather vest, scar"),
        ("Сестра Марена", "странствующая лекарка", "любопытная незнакомка",
         "Лекарка с острым взглядом: задаёт слишком много вопросов и перевязывает раны, не спрашивая разрешения.",
         "1girl, adult, long braided hair, freckles, healer robe, satchel"),
        ("Трактирщик Барто", "трактирщик", "дружелюбный делец",
         "Широкий смешливый трактирщик, торгующий слухами не меньше, чем элем.",
         "1boy, adult, overweight, bald, bushy beard, apron, rolled sleeves"),
    ],
    "Kazakh": [
        ("Күзетші Галка", "жергілікті жолсерік", "сақ одақтас",
         "Барлық жолды білетін, кейіпкерге қарыз тірі жолсерік.",
         "1boy, adult, short hair, weathered face, leather vest, scar"),
        ("Емші Мариям", "көшпелі емші", "қызыққан бейтаныс",
         "Тым көп сұрақ қойып, рұқсат сұрамай жараны таңып жіберетін кіржияң емші.",
         "1girl, adult, long braided hair, freckles, healer robe, satchel"),
        ("Барто", "мейманхана иесі", "достық саудагер",
         "Сырамен қатар сыбыс та сататын денеүйір, көп күлкілі мейманхана иесі.",
         "1boy, adult, overweight, bald, bushy beard, apron, rolled sleeves"),
    ],
}


def _mock_companion(lang: str, seed: int = 0) -> dict[str, Any]:
    pool = _MOCK_COMPANIONS[lang]
    name, role, relationship, description, appearance_tags = pool[seed % len(pool)]
    return {
        "name": name,
        "is_new": True,
        "role": role,
        "relationship": relationship,
        "description": description,
        "appearance_tags": appearance_tags,
    }


# Localized display names for the setting presets, used by the mock narrator's
# opening: the raw preset key ("Wizard school") must never leak into Russian or
# Kazakh prose. Custom freeform settings pass through unchanged.
_SETTING_DISPLAY: dict[str, dict[str, str]] = {
    "Medieval kingdom": {"Russian": "средневековое королевство", "Kazakh": "ортағасырлық патшалық"},
    "Space station": {"Russian": "космическая станция", "Kazakh": "ғарыш станциясы"},
    "Modern city": {"Russian": "современный город", "Kazakh": "қазіргі үлкен қала"},
    "Post-apocalypse": {"Russian": "мир после катастрофы", "Kazakh": "апокалипсис кейінгі әлем"},
    "Wizard school": {"Russian": "школа магии", "Kazakh": "сиқыр мектебі"},
    "Wild West": {"Russian": "Дикий Запад", "Kazakh": "Жабайы Батыс"},
    "Underwater world": {"Russian": "подводный мир", "Kazakh": "суасты әлемі"},
    "Cyberpunk metropolis": {"Russian": "киберпанк-мегаполис", "Kazakh": "киберпанк мегаполисі"},
    "High fantasy epic": {"Russian": "эпический фэнтези-мир", "Kazakh": "эпикалық фэнтези әлемі"},
    "Noir detective city": {"Russian": "нуарный город детективов", "Kazakh": "нуар-детективті қала"},
    "Horror mansion": {"Russian": "особняк с тёмным прошлым", "Kazakh": "құбыжық сарай"},
    "Historical drama": {"Russian": "историческая эпоха", "Kazakh": "тарихи дәуір"},
    "Superhero city": {"Russian": "город супергероев", "Kazakh": "супербатырлар қаласы"},
    "Fairy tale kingdom": {"Russian": "сказочное королевство", "Kazakh": "ертегі патшалығы"},
    "Pirate seas": {"Russian": "пиратские моря", "Kazakh": "қарақшылар теңіздері"},
    "Dystopia": {"Russian": "тоталитарная дистопия", "Kazakh": "тоталитарлық дистопия"},
    "Steampunk": {"Russian": "стимпанк-мир", "Kazakh": "стимпанк әлемі"},
    "Wuxia / martial arts": {"Russian": "мир уся", "Kazakh": "уся әлемі"},
    "Survival island": {"Russian": "необитаемый остров", "Kazakh": "тірі қалу аралы"},
    "Cosmic horror": {"Russian": "мир космического ужаса", "Kazakh": "ғарыштық қорқыныш әлемі"},
    "Slice-of-life school": {"Russian": "школьная повседневность", "Kazakh": "күнделікті мектеп өмірі"},
}


def _setting_display(lang: str, setting: str) -> str:
    """The setting name in the story's language; custom freeform settings and
    unknown presets pass through unchanged."""
    return _SETTING_DISPLAY.get(setting, {}).get(lang, setting)


def _intro(lang: str, setting: str, seed: int = 0) -> str:
    name = _setting_display(lang, setting)
    # Three rotating openings: the classic road-into-the-world one, a concrete
    # world-lore prologue and a hero-focused one. The story seed picks which.
    intros: dict[str, list[str]] = {
        "English": [
            (
            f"The world of this story is a place of old roads, older debts, and rumors that travel "
            f"faster than any ship — {name}. Long before your arrival it gathered its legends quietly: "
            "names carved where no one looks, promises never repaid, doors that open only for the "
            "right knock. Not all of its stories are told out loud.\n\n"
            "You arrive as a stranger, yet your name already means something here. Some will see an "
            "opportunity in you, others a threat; the role you carry decides which doors open and "
            "which stay barred. For now you know only what you managed to glimpse on the way in — "
            "the rest this world will reveal in its own time.\n\n"
            "Where it all leads is unwritten. This is where your story begins."
            ),
            (
                f"This land — the {name} — has a long memory. It still remembers the war that ended before your "
                "parents were born: the ruined border keeps were never rebuilt, and the victors still argue over "
                "who actually won. The guilds keep debt ledgers a century old, and those debts are still being paid.\n\n"
                "Your name has been spoken here already — not always kindly. Someone awaits you as a debtor, "
                "someone as a weapon, someone as a last hope. Which of them is right, you do not yet know.\n\n"
                "Either way, the road has run out. From here on, there are only choices."
            ),
            (
                "This story begins not with a world, but with the person who rode into it.\n\n"
                f"Little is known about you in the {name}, and half of it is true: rumors outrun any rider, and "
                "this land knows how to listen. Who you were before is yours to decide. Who you become here is "
                "yours too.\n\n"
                "One thing is certain already: the locals are arguing about what to do with you."
            ),
        ],
        "Russian": [
            (
            f"Мир этой истории — {name}. Здесь, задолго до вашего появления, тихо копились легенды: "
            "старые дороги, ещё более старые долги и слухи, что бегут быстрее любых кораблей. У каждой "
            "двери есть своя история, и далеко не все они рассказаны вслух.\n\n"
            "Вы приезжаете чужаком, но ваше имя уже кое-что значит в этих местах. Одни увидят в вас "
            "возможность, другие — угрозу; роль, которую вы несёте, решает, какие двери откроются, "
            "а какие останутся запертыми. Пока вам известно лишь то, что удалось разглядеть по пути — "
            "обо всём остальном этот мир расскажет сам, в своё время.\n\n"
            "К чему всё это приведёт — ещё не написано. Здесь начинается ваша история."
            ),
            (
                f"У этой земли — у {name} — долгая память. Здесь помнят войну, что закончилась до рождения ваших "
                "родителей: разорённые пограничные крепости так и не отстроили, а победители до сих пор спорят, "
                "кому досталась победа. Гильдии хранят долговые книги столетней давности, и по ним до сих пор "
                "платят.\n\n"
                "Ваше имя в этих краях уже произносили — не всегда добрым словом. Кто-то ждёт вас как должника, "
                "кто-то как оружие, кто-то как последнюю надежду. Кто из них прав — вы пока не знаете.\n\n"
                "Так или иначе, дорога закончилась. Дальше — только выборы."
            ),
            (
                "Эта история начинается не с мира, а с человека, который в него въехал.\n\n"
                f"О вас в {name} известно немногое, и всё оно — правда наполовину: слухи обгоняют любого "
                "всадника, а эта земля умеет слушать. Кем вы были до — решать вам. Кем станете здесь — тоже.\n\n"
                "Пока одно известно точно: местные уже спорят, что с вами делать."
            ),
        ],
        "Kazakh": [
            (
            f"Бұл әңгіменің әлемі — {name}. Сіз келгенге дейін бұл жерде аңыздар үнсіз жинақталған: "
            "ескі жолдар, одан да ескі қарыздар және кез келген кемеден жылдам тарайтын сыбыстар. "
            "Әр есіктің өз тарихы бар, бірақ бәрі ашық айтыла бермейді.\n\n"
            "Сіз бөтен адам болып келесіз, бірақ атыңыз бұл жерде әлдеқашан белгілі. Кейбіреулер сізді "
            "мүмкіндік деп, басқалары қауіп деп көреді; мойындаған рөліңіз қай есіктің ашылатынын "
            "шешеді. Әзірге жолда көре алғаныңыз ғана белгілі — қалғанын бұл әлем өзі, өз уақытында "
            "айтып береді.\n\n"
            "Бәрі неге апарып соғатыны әлі жазылған жоқ. Сіздің әңгімеңіз осы жерден басталады."
            ),
            (
                f"Бұл жердің — {name} — жадысы ұзақ. Ата-бабаңыз туғанға дейін біткен соғыс мұнда әлі "
                "ұмытылған жоқ: қираған шекара бекіністері әлі тұрғызылмады, ал жеңімпаздар жеңісті кімге "
                "бөлерін білмей дауласып жүр. Гильдиялар ғасырлар бұрынғы қарыз кітаптарын сақтайды — және "
                "олар бойынша әлі төленеді.\n\n"
                "Сіздің атыңыз бұл жерде әлдеқашан айтылған — әрдайым мадақ емес. Біреу сізді борышкер "
                "ретінде, біреу қару ретінде, біреу соңғы үміт ретінде күтеді. Қайсысы ақ екенін әлі "
                "білмейсіз.\n\n"
                "Солай немесе бұлай, жол бітті. Бұдан әрі — тек таңдаулар."
            ),
            (
                "Бұл әңгіме әлемнен емес, оған келген адамнан басталады.\n\n"
                f"Сіз туралы {name} ішінде аз ғана белгілі, және оның жартысы ғана шындық: сыбыс кез келген "
                "аттыдан жылдам, ал бұл жер тыңдай біледі. Бұрын кім болғаныңызды өзіңіз шешесіз. Мұнда кім "
                "болатыныңызды да.\n\n"
                "Әзірге бір нәрсе анық: жергілікті тұрғындар сізді не істеу керегін талқылап жатыр."
            ),
        ],
    }
    variants = intros[lang]
    return variants[seed % len(variants)]


def _narration(lang: str, scene_index: int, turn_number: int) -> str:
    # Scene templates rotated by (seed + turn). Scene 0 is the classic shadowy
    # watcher; scene 1 puts the hero alone on the road; scene 2 drops them into
    # a public conflict where NPCs talk to each other, not to the player.
    texts: dict[str, list[str]] = {
        "English": [
            (
            f"Turn {turn_number}. The air tastes of rain and old smoke. Lantern light "
            "slides across wet stone as a figure detaches from the shadows — a watcher who has been "
            "waiting for someone exactly like you.\n\n"
            '"You walk loudly for someone with secrets," the stranger says, voice low and amused. '
            '"That can be fixed. What matters is whether you listen before you answer."\n\n'
            "Behind them, a narrow stair descends into lamplight and voices — a gathering that "
            "should not exist, planning something that should not be possible."
            ),
            (
                "Dawn catches you on the road: mist lies low over wet grass, and beyond the hill a thread "
                "of smoke rises — someone's breakfast or someone's misfortune. There is no one around, and "
                "that in itself is the answer to a question you never asked out loud.\n\n"
                "You shift the strap of your pack and check that everything is where it should be. "
                "Everything is. Almost everything.\n\n"
                "Ahead the road forks: left to the gates and people, right around through the fields, "
                "where only the wind looks."
            ),
            (
                "The square hums like a kicked hive. By a broken cart two men have collided: a merchant "
                "in a wine-soaked kaftan and a courier whose horse hasn't cooled from the road.\n\n"
                '"You put half my goods under hooves!" The merchant stabs a finger at a shattered clay '
                'jar. "Who pays for that, the royal post?"\n'
                '"The royal post doesn\'t pay those who feast in the middle of the highway," the courier '
                "snaps back, but his eyes dart.\n\n"
                "The crowd goes quiet — waiting to see who reaches for a knife first. And in that silence "
                "you hear your own name, whispered somewhere behind you."
            ),
        ],
        "Russian": [
            (
            f"Ход {turn_number}. Воздух пахнет дождём и старым дымом. Свет фонарей "
            "скользит по мокрому камню, и из тени отделяется фигура — наблюдатель, который ждал "
            "именно вас.\n\n"
            "— Вы шумно ходите для человека с тайнами, — говорит незнакомец тихо и с усмешкой. "
            "— Это поправимо. Важно лишь, слушаете ли вы, прежде чем ответить.\n\n"
            "За его спиной узкая лестница уходит вниз, к свету и голосам — к собранию, которого "
            "не должно существовать, замышляющему невозможное."
            ),
            (
                "Рассвет застаёт вас в дороге: туман стелется над мокрой травой, а за холмом поднимается "
                "дым — чей-то завтрак или чьё-то несчастье. Вокруг ни души, и это само по себе ответ на "
                "вопрос, который вы не задавали вслух.\n\n"
                "Вы перекидываете ремень сумы через плечо и проверяете, на месте ли всё, что должно быть "
                "на месте. Всё на месте. Почти всё.\n\n"
                "Впереди дорога раздваивается: налево — к воротам и людям, направо — в обход, полями, "
                "куда глядит только ветер."
            ),
            (
                "Площадь гудит, как растревоженный улей. У развороченной телеги столкнулись двое: "
                "торговец в залитом вином кафтане и гонец, чья лошадь ещё не остыла от дороги.\n\n"
                "— Ты мне половину товара пустил под копыта! — Торговец тычет пальцем в битый глиняный "
                "бок. — Кто платить будет, почта королевская?\n"
                "— Почта королевская не платит тем, кто пирует посреди тракта, — огрызается гонец, но "
                "глаза у него бегают.\n\n"
                "Толпа притихает — ждёт, кто первый полезет за ножом. И в этой тишине вы слышите "
                "собственное имя, произнесённое шёпотом где-то за спиной."
            ),
        ],
        "Kazakh": [
            (
            f"{turn_number}-жүріс. Ауада жаңбыр мен ескі түтіннің иісі бар. Шам жарығы "
            "жаңбырлы тасқа сырғанайды, ал көлеңкеден бір бейне бөлініп шығады — дәл сіз сияқты "
            "біреуді күткен бақылаушы.\n\n"
            "— Құпиясы бар адам үшін қатты жүресіз, — дейді бейтаныс төмен ғана күлкілі дауыспен. "
            "— Мұны түзетуге болады. Маңыздысы — жауап бермес бұрын тыңдайсыз ба.\n\n"
            "Оның артындағы тар баспалдақ жарық пен дауыстарға төмен түседі — болмауға тиіс жиналыс "
            "мүмкін емес нәрсені жоспарлап отыр."
            ),
            (
                "Таң сізді жолда ұстайды: тұман дымқыл шөп үстінде созылып жатыр, ал төбенің ар жағында "
                "түтін көтерілуде — біреудің таңғы асы ма, біреудің бақытсыздығы ма. Айналада жан жоқ, бұл "
                "өзі-ақ дауыссыз сұрақтың жауабы.\n\n"
                "Сіз ауаның белдігін иығыңызға ауыстырып, бәрі орнында ма деп тексересіз. Бәрі орнында. "
                "Ықтимал, бәрі.\n\n"
                "Алда жол екіге бөлінеді: солға — қақпа мен адамдарға, оңға — жел ғана қарайтын дала "
                "арқылы айналма жол."
            ),
            (
                "Алаң мазасыз ара ұясы сияқты гүрілдейді. Қираған арбаның қасында екеуі соқтығысты: "
                "шарапқа малынған кафтаны бар саудагер мен жаны әлі жолдан сумаған шабарман.\n\n"
                "— Тауарымның жартысын тұяқтың астына салдың! — Саудагер сынған құмыраға саусағын "
                "сілтейді. — Кім төлейді, патша поштасы ма?\n"
                "— Патша поштасы жол ортасында тойғанға төлемейді, — деп қарсылық білдіреді шабарман, "
                "бірақ көзі жүгіріп тұр.\n\n"
                "Көпшілік үнсіз қалады — пышаққа кім бірінші созыларын күтуде. Дәл осы тыныштықта сіз "
                "өз атыңыздың артыңыздан сыбырмен айтылғанын естисіз."
            ),
        ],
    }
    variants = texts[lang]
    return variants[scene_index % len(variants)]


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


def _options(lang: str, mode: str, scene_index: int) -> tuple[list[dict[str, str]], str]:
    # Options follow the scene template, so a solo morning on the road no
    # longer offers to "approach the stranger" who isn't there.
    option_texts: dict[str, list[dict[str, list[str]]]] = {
        "English": [
            {
                "open": ["Approach the stranger openly", "Watch from the shadows first", "Ask about the gathering below", "Demand to know how they knew you"],
                "locked": ["Follow the stranger down the stair", "Refuse and walk away", "Search the stranger's belongings"],
                "binary": ["Trust the stranger completely", "Turn your back forever"],
            },
            {
                "open": ["Look around and listen", "Check your gear and map", "Head for the smoke beyond the hill", "Turn toward the city gates"],
                "locked": ["Go left, toward the gates and people", "Go right, around through the fields", "Stay by the road and wait"],
                "binary": ["Step toward the unknown", "Turn back without looking"],
            },
            {
                "open": ["Step into the argument", "Listen silently from the crowd", "Find whoever whispered your name", "Move on about your business"],
                "locked": ["Side with the merchant", "Side with the courier", "Pull them apart"],
                "binary": ["Say your name out loud", "Melt into the crowd"],
            },
        ],
        "Russian": [
            {
                "open": ["Подойти к незнакомцу открыто", "Сначала понаблюдать из тени", "Спросить о собрании внизу", "Потребовать объяснить, откуда вас знают"],
                "locked": ["Пойти за незнакомцем по лестнице", "Отказаться и уйти", "Обыскать вещи незнакомца"],
                "binary": ["Довериться незнакомцу полностью", "Навсегда повернуться спиной"],
            },
            {
                "open": ["Осмотреться и прислушаться", "Проверить снаряжение и карту", "Идти к дыму за холмом", "Свернуть к городским воротам"],
                "locked": ["Пойти налево, к воротам и людям", "Пойти направо, полями в обход", "Остаться у дороги и ждать"],
                "binary": ["Шагнуть навстречу неизвестному", "Повернуть назад без оглядки"],
            },
            {
                "open": ["Вмешаться в спор", "Молча слушать из толпы", "Найти того, кто шептал ваше имя", "Пройти дальше по своим делам"],
                "locked": ["Поддержать торговца", "Поддержать гонца", "Разнять их обоих"],
                "binary": ["Назвать себя вслух", "Раствориться в толпе"],
            },
        ],
        "Kazakh": [
            {
                "open": ["Бейтанысқа ашық жақындау", "Алдымен көлеңкеден бақылау", "Төмендегі жиналыс туралы сұрау", "Сізді қайдан білетінін түсіндіруін талап ету"],
                "locked": ["Бейтанысқа еріп баспалдақпен түсу", "Бас тартып кету", "Бейтаныстың заттарын тексеру"],
                "binary": ["Бейтанысқа толық сену", "Мәңгілікке артқа бұрылу"],
            },
            {
                "open": ["Айналаға қарап, тыңдау", "Жабдық пен картаны тексеру", "Төбенің арғы түтініне бару", "Қала қақпасына бұрылу"],
                "locked": ["Солға, қақпа мен адамдарға бару", "Оңға, дала арқылы айналып өту", "Жол қасында тұрып күту"],
                "binary": ["Белгісіздікке бет бұру", "Артқа жалтақтамай қайту"],
            },
            {
                "open": ["Дауға араласу", "Топ ішінде үнсіз тыңдау", "Атыңызды сыбырлаған адамды іздеу", "Өз ісімен әрі қарай кету"],
                "locked": ["Саудагерді қолдау", "Шабарманды қолдау", "Екеуін де тежеп қалу"],
                "binary": ["Атыңызды дауыстап ату", "Топ ішінде жоғалу"],
            },
        ],
    }
    prompts = {
        "English": {"open": "What will you do?", "locked": "Choose your path.", "binary": "This is a decisive moment."},
        "Russian": {"open": "Что будете делать?", "locked": "Выберите путь.", "binary": "Это решающий момент."},
        "Kazakh": {"open": "Не істейсіз?", "locked": "Жолыңызды таңдаңыз.", "binary": "Бұл шешуші сәт."},
    }
    texts = option_texts[lang][scene_index % 3][mode]
    letters = ["a", "b", "c", "d"]
    return [{"id": letters[i], "text": text} for i, text in enumerate(texts)], prompts[lang][mode]


def _state(lang: str, turn_number: int, setting: str, scene_index: int) -> dict[str, Any]:
    name = _setting_display(lang, setting)
    scenes = {"English": f"{name} — turn {turn_number}", "Russian": f"{name} — ход {turn_number}", "Kazakh": f"{name} — {turn_number}-жүріс"}
    summaries = {
        "English": [
            f"Turn {turn_number}: the hero pressed deeper into {name} and met a key figure.",
            f"Turn {turn_number}: the hero walked on alone.",
            f"Turn {turn_number}: the hero found themselves at the center of a street conflict.",
        ],
        "Russian": [
            f"Ход {turn_number}: герой продвинулся дальше и встретил важную фигуру.",
            f"Ход {turn_number}: герой продолжил путь в одиночку.",
            f"Ход {turn_number}: герой оказался в центре уличного конфликта.",
        ],
        "Kazakh": [
            f"{turn_number}-жүріс: кейіпкер алға жылжып, маңызды тұлғамен кездесті.",
            f"{turn_number}-жүріс: кейіпкер жолды жалғыз жалғастырды.",
            f"{turn_number}-жүріс: кейіпкер көше дауының ортасында қалды.",
        ],
    }
    facts = {
        "English": [
            f"A stranger in {name} knew the hero's name.",
            "The hero entered this land alone, owing nothing to anyone.",
            "Someone in the square crowd knows the hero by sight.",
        ],
        "Russian": [
            "Незнакомец из этих мест знал имя героя.",
            "Герой вошёл в эти места в одиночку, ни от кого не завися.",
            "В толпе на площади кто-то знает героя в лицо.",
        ],
        "Kazakh": [
            "Бұл өлкедегі бейтаныс кейіпкердің атын білді.",
            "Кейіпкер бұл өлкеге жалғыз, ешкімге тәуелді болмай келді.",
            "Алаңдағы топтың ішінде біреу кейіпкерді жүзінен таниды.",
        ],
    }
    idx = scene_index % 3
    return {"scene": scenes[lang], "summary": summaries[lang][idx], "facts": [facts[lang][idx]]}


def call_model(
    system_prompt: str,
    user_prompt: str,
    settings: Settings,
    mock_index: int = 0,
    mock_language: str = "English",
    mock_setting: str = "a mysterious world",
    mock_hero_appearance: str = "",
    mock_hero_gender: str = "",
    mock_max_turns: int | None = None,
    mock_seed: int = 0,
    model_name: str | None = None,
    provider: str | None = None,
) -> str:
    if settings.mock_llm:
        turn_number = mock_index + 1
        contract = _mock_contract(turn_number, mock_max_turns, mock_language, mock_setting,
                                  hero_appearance=mock_hero_appearance, hero_gender=mock_hero_gender,
                                  seed=mock_seed)
        # Mock the note classification service fields, so the player-note
        # pipeline (pinning facts, one-shot events) works with MOCK_LLM=true.
        note = _mock_extract_note(user_prompt)
        if note:
            note_type, normalized = _mock_note_classification(note)
            contract["note_type"] = note_type
            contract["normalized_text"] = normalized
        return json.dumps(contract, ensure_ascii=False)

    # The per-story provider choice wins ("gemini" / "local" / "groq" /
    # "openrouter"); stories without it and direct callers follow the
    # server-wide LLM_PROVIDER. "openai" and "local" both mean the
    # OpenAI-compatible local server (Ollama, LM Studio, ...).
    resolved = (provider or settings.llm_provider or "gemini").lower()
    if resolved in ("openai", "local"):
        if not settings.openai_base_url:
            raise LLMConfigurationError(
                "OPENAI_BASE_URL is not configured. Point it at your local server "
                "(e.g. http://localhost:11434/v1 for Ollama)."
            )
        return _call_openai(model_name or settings.openai_model, system_prompt, user_prompt, settings)
    if resolved in ("groq", "openrouter", "mistral"):
        base_url, api_key, default_model = _cloud_endpoint(resolved, settings)
        # Only OpenRouter's API accepts the reasoning toggle (its free
        # reasoning models need it); Groq and Mistral reject unknown body
        # properties with a 400.
        reasoning_toggle = resolved == "openrouter"
        if resolved == "openrouter":
            return _call_cloud_with_fallback(
                model_name or default_model,
                OPENROUTER_FALLBACK_ORDER,
                system_prompt,
                user_prompt,
                settings,
                base_url=base_url,
                api_key=api_key,
                reasoning_toggle=True,
            )
        if resolved == "mistral":
            return _call_cloud_with_fallback(
                model_name or default_model,
                MISTRAL_FALLBACK_ORDER,
                system_prompt,
                user_prompt,
                settings,
                base_url=base_url,
                api_key=api_key,
                reasoning_toggle=False,
            )
        max_tokens = (
            min(settings.max_tokens, GROQ_MAX_OUTPUT_TOKENS) if resolved == "groq" else None
        )
        return _call_openai(
            model_name or default_model,
            system_prompt,
            user_prompt,
            settings,
            base_url=base_url,
            api_key=api_key,
            reasoning_toggle=reasoning_toggle,
            max_tokens=max_tokens,
        )
    if resolved != "gemini":
        raise LLMConfigurationError(
            f"Unknown LLM_PROVIDER '{resolved}' "
            "(expected 'gemini', 'openai', 'local', 'groq', 'openrouter' or 'mistral')."
        )

    if not settings.gemini_api_key:
        raise LLMConfigurationError(
            "Gemini API key is not configured. Add GEMINI_API_KEY to .env, pick the "
            "local model in the story setup, or enable MOCK_LLM=true."
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
            f"The model refused the prompt (reason: {prompt_block}). This is Gemini's hard content "
            "filter — no setting or age rating lifts it. Rephrase the setup (custom details, hero "
            "description: explicit wording there is the usual trigger), or create this story with "
            "the local model instead — pick it in the provider selector of the setup form; it has "
            "no such filter."
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


def _cloud_endpoint(provider: str, settings: Settings) -> tuple[str, str, str]:
    """Base URL, API key and default model for a named cloud provider."""
    if provider == "groq":
        if not settings.groq_api_key:
            raise LLMConfigurationError(
                "Groq API key is not configured. Add GROQ_API_KEY to .env "
                "(free key at console.groq.com), or pick another text model source."
            )
        return GROQ_BASE_URL, settings.groq_api_key, settings.groq_model
    if provider == "mistral":
        if not settings.mistral_api_key:
            raise LLMConfigurationError(
                "Mistral API key is not configured. Add MISTRAL_API_KEY to .env "
                "(free Experiment tier key at console.mistral.ai, no card needed), "
                "or pick another text model source."
            )
        return MISTRAL_BASE_URL, settings.mistral_api_key, settings.mistral_model
    if not settings.openrouter_api_key:
        raise LLMConfigurationError(
            "OpenRouter API key is not configured. Add OPENROUTER_API_KEY to .env "
            "(key at openrouter.ai/keys), or pick another text model source."
        )
    return OPENROUTER_BASE_URL, settings.openrouter_api_key, settings.openrouter_model


def _call_cloud_with_fallback(
    model: str,
    fallback_order: list[str],
    system_prompt: str,
    user_prompt: str,
    settings: Settings,
    base_url: str,
    api_key: str,
    reasoning_toggle: bool,
) -> str:
    """Named cloud provider with an automatic fallback chain: free tiers are
    shared pools, so a congested (429), removed (404) or down (503) model
    retries on the next model instead of failing the turn."""
    candidates = [model] + [m for m in fallback_order if m != model]
    last_error: LLMResponseError | None = None
    for candidate in candidates:
        try:
            return _call_openai(
                candidate,
                system_prompt,
                user_prompt,
                settings,
                base_url=base_url,
                api_key=api_key,
                reasoning_toggle=reasoning_toggle,
            )
        except LLMResponseError as exc:
            if any(code in str(exc) for code in ("429", "404", "503")):
                logger.warning("model %s unavailable at %s, falling back: %s", candidate, base_url, exc)
                last_error = exc
                continue
            raise
    raise last_error or LLMResponseError("The AI service returned an error.")


def _call_openai(
    model: str,
    system_prompt: str,
    user_prompt: str,
    settings: Settings,
    base_url: str | None = None,
    api_key: str | None = None,
    reasoning_toggle: bool = True,
    max_tokens: int | None = None,
) -> str:
    """Any OpenAI-compatible chat endpoint (Ollama, LM Studio, llama.cpp, Groq,
    OpenRouter).

    Local servers are slower than the cloud, so the timeout is generous; there
    is no safety layer here — content is governed solely by our narrator prompt.
    """
    base = (base_url or settings.openai_base_url).rstrip("/")
    key = settings.openai_api_key if api_key is None else api_key
    url = base + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.9,
        "max_tokens": max_tokens if max_tokens is not None else settings.max_tokens,
        "response_format": {"type": "json_object"},
    }
    if reasoning_toggle:
        # Reasoning models (Nemotron, Qwen-thinking, …) otherwise burn the
        # token budget on chain-of-thought — or leak it into the content and
        # break the JSON contract. Strict APIs (Groq) reject this property
        # with a 400, so the caller omits it there.
        payload["reasoning"] = {"enabled": False}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=300.0)
    except httpx.HTTPError as exc:
        raise LLMResponseError(
            f"The model server could not be reached at {base}: {exc}. "
            "Start Ollama/LM Studio, check the cloud endpoint, or switch the story "
            "to another text model source."
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


def faithful_appearance_tags(
    appearance: str,
    gender: str,
    settings: Settings,
    model_name: str | None = None,
    provider: str | None = None,
) -> str | None:
    """Convert the player's freeform hero description into danbooru tags with a
    dedicated, narrowly-scoped call. Small narrators compress the description
    when they invent hero.appearance_tags inside the big turn JSON (figure,
    haircut, fabric and fit details vanish) — a single-task prompt is lossless
    by comparison. Returns None on any failure; the caller then keeps the
    narrator's tags. In mock mode the mock already converts the description
    itself, so this stays out of the way."""
    if settings.mock_llm or not appearance.strip():
        return None
    gender_tag = GENDER_TAGS.get(gender or "", "1girl")
    user = (
        "Convert this character description into comma-separated danbooru-style image tags.\n"
        "Rules: English tags only; keep EVERY visual detail the player stated — figure (breast size, "
        "waist, hips, legs, height, build), hair (color, length, style, bangs), eyes, lips, skin, "
        "makeup, every clothing item with its fabric and how it is worn, accessories. Translate "
        "faithfully; do not soften, drop or censor anything, and NEVER replace a stated proportion "
        "with another one: a described large chest stays large, wide hips stay wide.\n"
        "If the description is sparse, COMPLETE the look with plausible details for the parts it "
        "leaves unstated (hair style, eye color, outfit), chosen to fit what the player DID write — "
        "the character must be a complete, specific person, never a vague sketch. Never contradict "
        "the description and never change the gender.\n"
        "No sentences, no commentary, no quality or rating words.\n"
        f'Start the list with "{gender_tag}, solo" and end it with ", adult".\n\n'
        f"DESCRIPTION:\n{appearance.strip()}"
    )
    try:
        raw = call_model(
            "You convert character descriptions into image tags. Answer with the tag list only.",
            user,
            settings,
            model_name=model_name,
            provider=provider,
        )
    except (LLMConfigurationError, LLMResponseError) as exc:
        logger.warning("faithful hero tag conversion failed, keeping narrator tags: %s", exc)
        return None
    tags = clean_tag_string(raw)
    if not tags or len(tags) > 900 or "1girl" not in tags and "1boy" not in tags and "1other" not in tags:
        logger.warning("faithful hero tag conversion returned unusable text, keeping narrator tags")
        return None
    return tags


def translate_image_tags(
    tags: str,
    settings: Settings,
    model_name: str | None = None,
    provider: str | None = None,
) -> str | None:
    """Re-emit a tag string in English when the narrator answered in Russian.

    The image model reads English danbooru tags: Cyrillic tags are ignored or
    turn into visual noise, so a narrator that wrote the picture description in
    the story's language gets one narrow translation call instead of a picture
    that ignores its own prompt. Returns None on any failure — the caller then
    keeps the original text.
    """
    if settings.mock_llm or not tags.strip():
        return None
    user = (
        "Translate these image tags into English danbooru-style tags.\n"
        "Rules: keep every detail and the tag order, add nothing, drop nothing, "
        "translate the wording only. Answer with the comma-separated tag list only — "
        "no sentences, no commentary.\n\n"
        f"TAGS:\n{tags.strip()}"
    )
    try:
        raw = call_model(
            "You translate image tags into English danbooru tags. Answer with the tag list only.",
            user,
            settings,
            model_name=model_name,
            provider=provider,
        )
    except (LLMConfigurationError, LLMResponseError) as exc:
        logger.warning("image tag translation failed, keeping the original tags: %s", exc)
        return None
    translated = clean_tag_string(raw)
    if not translated or has_cyrillic(translated) or len(translated) > 900:
        logger.warning("image tag translation returned unusable text, keeping the original tags")
        return None
    return translated


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
            "the story's age rating — soften the scene or the setup wording and try again, or "
            "switch this kind of story to the local model (provider selector in the setup form), "
            "which has no safety layer."
        )
    if finish_reason == "MAX_TOKENS":
        return "The model's answer did not fit the token limit. Try again or raise MAX_TOKENS in .env."
    if finish_reason == "RECITATION":
        return "The model stopped its answer to avoid reproducing existing text. Try again."
    if finish_reason:
        return f"The model stopped without producing text (reason: {finish_reason}). Try again."
    return "The AI service returned an unexpected response shape."
