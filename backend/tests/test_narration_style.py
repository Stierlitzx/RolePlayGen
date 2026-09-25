"""The narration guards: readability (wall of dialogue) and novelty (repeats)."""

from app.services.narration_style import (
    narration_problems,
    paragraphs,
    quotes_in,
    repetition_problems,
    speech_word_share,
)

PROSE_TURN = (
    "Дождь начался ещё до рассвета, и к утру тропа превратилась в грязную ленту между мокрыми "
    "ёлами. Лирна шла первой, потому что чужие шаги за спиной успокаивали её меньше, чем "
    "собственные. Ветка хлестнула по плечу, и она даже не обернулась.\n\n"
    "Гаррет догнал её у ручья и долго молчал, глядя на воду. «Ты не должна идти туда одна», — "
    "сказал он наконец, и в голосе его не было уверенности. Лирна посмотрела на его руки: они "
    "дрожали, и это было честнее любых слов.\n\n"
    "Они вошли в деревню на закате. Дым поднимался из труб ровно, как в мирные дни, и от этого "
    "становилось только тревожнее. Старуха у колодца подняла голову, долго смотрела им вслед, "
    "а потом отвернулась и стала считать узлы на своей верёвке."
)


def _wall(separator: str) -> str:
    """A Mistral-style turn: mostly speech and thoughts, little narration."""
    lines = [
        "Лирна замерла на пороге хижины, сердце колотилось так сильно, что она боялась, "
        "как бы оно не выпрыгнуло из груди.",
        "*«Бабушка…»* — мысль об этом не давала ей дышать.",
        "— Уходи, эльфийка, — сказал он, голос дрожа от ненависти.",
        "— Или я действительно её убью.",
        "*«Я не уйду. Я не оставлю её.»*",
        "— Тогда отпусти её! — крикнула Лирна, и в её голосе зазвучала такая сила.",
        "— Ты не понимаешь, что делаешь, — сказал он, голос низкий и хриплый.",
        "*«Магия… она внутри меня.»*",
        "— Что это?! — закричал он, но Лирна не обратила на него внимания.",
        "— Оставь её, — сказал он, голос теперь звучал как предупреждение.",
        "— Это не твоя война, мальчик.",
        "— Моя девочка… — прошептала она.",
        "— Нет, — сказала она. — Я не их. Я не твоя. Я — мага.",
    ]
    return separator.join(lines)


def test_a_prose_turn_raises_nothing() -> None:
    assert paragraphs(PROSE_TURN)
    assert narration_problems(PROSE_TURN) == []


def test_a_short_turn_is_never_checked() -> None:
    # The rules explicitly allow a tense exchange or a transition to be short
    # and sharp — a short dialogue-only beat must not be rewritten.
    short = "— Уходи, эльфийка, — сказал он. — Или я действительно её убью."
    assert len(short) < 700
    assert narration_problems(short) == []


def test_a_single_block_of_text_is_flagged() -> None:
    wall = _wall(" ")
    problems = narration_problems(wall)
    assert len(paragraphs(wall)) == 1
    assert any("single block" in problem for problem in problems)
    assert any("paragraphs separated by blank lines" in problem for problem in problems)


def test_a_paragraph_per_line_dialogue_wall_is_flagged() -> None:
    # The other shape of the same defect: the model does use blank lines, but
    # every paragraph is one more quoted line or one more italic thought.
    wall = _wall("\n\n")
    assert len(paragraphs(wall)) >= 3
    assert speech_word_share(wall) > 0.6
    assert any("quoted lines" in problem for problem in narration_problems(wall))


def test_speech_share_counts_quotes_italics_and_dash_lines() -> None:
    assert speech_word_share("Он молчал всю дорогу и смотрел под ноги.") == 0.0
    assert speech_word_share("— Уходи, — сказал он.") == 1.0
    assert 0.0 < speech_word_share('Лирна кивнула. "Get out," he says, stepping back.') < 1.0
    assert speech_word_share("*«Я не уйду.»*") == 1.0


# The shape the player actually reported: enough paragraphs and a low speech
# share (so the old checks stay green), yet one paragraph holds the whole
# back-and-forth in a single unreadable block.
DENSE_EXCHANGE_TURN = (
    "Лилиана медленно вошла в дом и прислонилась к ней спиной, чувствуя, как дверная "
    "фурнитура отдаёт холодом в лопатки. Утро было тихое, и только где-то за стеной "
    "журчала вода из пригоршни, которую она набрала у источника. Соседи уже следили за "
    "ней: сначала любопытно, потом подозрительно, а теперь просто с холодной "
    "расчётливостью, с какой в деревне смотрят на тех, кто разговаривает с чужаками.\n\n"
    "Эйден поднял брови, но не отступил. *«Тогда ты останешься здесь и станешь частью "
    "того, о чём я предупреждал»*, — сказал он, и в его голосе появилась странная "
    "уверенность. *«Мне не нужны твои предупреждения, эльф»*, — ответила Лилиана, и её "
    "голос звучал холодно. *«Ты не понимаешь, о чём идёт речь, смертный»*, — Эйден "
    "обернулся к Таррику, и в его голосе прозвучала угроза. *«Я не собираюсь никуда идти "
    "с тобой»*, — Лилиана подняла подбородок, пытаясь скрыть, как сильно бьётся её "
    "сердце. *«Но если ты действительно знаешь что-то важное, то давай встретимся позже»*, "
    "— сказала она наконец, и в этом предложении было больше усталости, чем решимости. "
    "*«Хорошо»*, — сказал он, делая шаг назад. *«Но помни: время работает против тебя»*, "
    "— и в этой фразе она услышала не обещание, а приговор.\n\n"
    "Она вошла в дом, закрыв за собой дверь, и прислонилась к ней спиной. Её лицо в "
    "маленьком зеркале выглядело усталым, но глаза горели решимостью, которой она сама в "
    "себе не ожидала. Соседи уже шептались о том, что она разговаривала с эльфом, а в "
    "деревне шепот распространяется быстрее пожара. Она не собиралась объясняться: время "
    "надо было найти ответы, а ответы требовали одиночества и хладнокровия."
)


def test_a_chain_of_exchanges_in_one_paragraph_is_flagged() -> None:
    # Both legacy checks look fine here — that is the point of the regression:
    # the paragraph count and the speech share both stay inside their limits,
    # yet the middle paragraph packs seven replies into one block.
    assert len(DENSE_EXCHANGE_TURN) >= 700
    assert len(paragraphs(DENSE_EXCHANGE_TURN)) >= 3
    assert speech_word_share(DENSE_EXCHANGE_TURN) <= 0.6
    assert max(quotes_in(block) for block in paragraphs(DENSE_EXCHANGE_TURN)) > 5

    problems = narration_problems(DENSE_EXCHANGE_TURN)
    assert any("wall of text" in problem for problem in problems)
    assert any("every reply starts its own paragraph" in problem for problem in problems)


def test_a_normal_few_replies_per_paragraph_stay_unflagged() -> None:
    # Two replies in a paragraph are fine — the guard must not rewrite every
    # turn that contains any dialogue.
    ok = (
        "Лилиана вошла в дом и села на кровать, всё ещё слушая шаги за дверью. Утро "
        "было тихое, и в этой тишине ей было легче собирать мысли, чем перед чужим "
        "лицом, которое ничего от неё не ждало. Она знала, что разговор только что "
        "начался, и что сегодня вечером ему придётся дать ответ.\n\n"
        "*«Ты пришёл с предупреждением, но я не собираюсь бросать всё ради твоих "
        "загадок»*, — сказала она вслух, проверяя, как звучат эти слова. *«Тогда ты "
        "останешься здесь»*, — ответил Эйден, и в его голосе не было ни угрозы, ни "
        "упрёка, только усталость.\n\n"
        "За окном шумел лес, и этот шум казался ей обещанием, которое она не сумеет "
        "выполнить. Она знала, что разговор был только началом, и что до вечера "
        "пройдёт много времени, прежде чем она решится ответить — если вообще решится "
        "что-то говорить с этим незнакомцем."
    )
    # The guard must not rewrite every turn that contains any dialogue: two
    # replies in a paragraph are fine. The fixture is long enough to actually be
    # checked (the style guard only looks at real turns).
    assert len(ok) >= 700
    assert narration_problems(ok) == []


# The shape the player actually reported: three turns in a row, each of them
# replaying the same staged entrance, the same stock thought and the same
# farewell — while every per-turn format check stays green.
REPEATED_TURN_ONE = (
    "Лилиана шагала по лесу, и её босые ноги почти не оставляли следов на мокрой от росы "
    "траве. *«Кто-то там»*, — подумала она, инстинктивно сжимая рукоятку ножа. Когда она "
    "осторожно раздвинула ветви, перед ней открылись руины заброшенного замка. *«Это то, "
    "что мне нужно»*, — шепнула она, и её сердце забилось чуть быстрее.\n\n"
    "Внутри замок был почти полностью разрушен, и пыль висела в воздухе, танцуя в лучах "
    "солнца, проникавших через разбитые окна. Таррик вышел из-за руин, и его глаза "
    "расширились, когда он увидел её. *«Лилиана!»* — воскликнул он, но его голос дрогнул."
)

REPEATED_TURN_TWO = (
    "Лилиана шагала по лесу, и её босые ноги почти не оставляли следов на мокрой от росы "
    "траве. *«Кто-то там»*, — подумала она, инстинктивно сжимая рукоятку ножа. Когда она "
    "осторожно раздвинула ветви, перед ней открылись руины заброшенного замка. *«Это то, "
    "что мне нужно»*, — шепнула она, и её сердце забилось чуть быстрее.\n\n"
    "В воздухе пахло сыростью и гнилью, и каждый шаг по мху звучал глуше, чем прежде. "
    "Таррик вышел из-за руин, и его глаза расширились, когда он увидел её. *«Лилиана!»* — "
    "воскликнул он, но его голос дрогнул."
)

FRESH_TURN = (
    "На рассвете караван свернул с тракта к самой кромке леса, и Лилиана увидела, как "
    "впереди, среди мёрзлых кустов, кто-то развёл костёр: тонкий дым уносило ветром. "
    "Она придержала лошадь и сошла с седла, прикрывая глаза от низкого солнца.\n\n"
    "Песчаник под копытами был рыхлым, и следы вели не в лес, а по обрыву к реке — "
    "свежие, вчерашние. Так уходят отрядом, спешащим и не желающим оставлять знаков, и "
    "это было хуже, чем следы одного человека."
)


def test_a_turn_replaying_an_earlier_turn_is_flagged() -> None:
    # Every per-turn format check is happy — three paragraphs, few quotes per
    # paragraph, a low speech share. Only a comparison with the previous turns
    # sees that the whole scene is a copy.
    assert narration_problems(REPEATED_TURN_TWO) == []
    problems = repetition_problems(REPEATED_TURN_TWO, [REPEATED_TURN_ONE])
    assert any("REPEATED CONTENT" in problem for problem in problems)
    assert any("REPEATED DIALOGUE" in problem for problem in problems)


def test_the_repetition_complaint_names_the_reused_words() -> None:
    problems = repetition_problems(REPEATED_TURN_TWO, [REPEATED_TURN_ONE])
    repeated = " ".join(problems)
    # The instruction is handed back to the model, so it has to show the reuse.
    assert "почти не оставляли следов" in repeated
    assert "Кто-то там" in repeated  # the quote is shown as the narrator wrote it


def test_a_fresh_turn_raises_nothing() -> None:
    assert repetition_problems(FRESH_TURN, [REPEATED_TURN_ONE, REPEATED_TURN_TWO]) == []


def test_nothing_to_compare_against_is_never_a_problem() -> None:
    # The first turn of a story has no history: the guard must stay silent.
    assert repetition_problems(REPEATED_TURN_ONE, []) == []
    assert repetition_problems(REPEATED_TURN_ONE, ["", "   "]) == []


def test_a_short_turn_is_never_checked_for_repetition() -> None:
    # A terse exchange can legitimately echo a name or a place from the turn
    # before it; only a real turn is compared.
    short = "— Уходи, — сказала Таррик у порога."
    assert len(short) < 700
    assert repetition_problems(short, [REPEATED_TURN_ONE]) == []


def test_names_and_places_alone_are_not_repetition() -> None:
    # Two turns that both mention Лилиана, Таррик and the forest are not a copy.
    turn = (
        "Лилиана пересекла мост из серого камня и оглянулась: Таррик стоял на том "
        "берегу, где лес подступал к самой воде. Ветер срывал с деревьев последние "
        "жёлтые листья, и они ложились на воду, как медленные жёлтые птицы. *«Иди»*, — "
        "сказал он, не поднимая голоса, и она кивнула, потому что спорить было не о чем."
    )
    assert repetition_problems(turn, [REPEATED_TURN_ONE]) == []
