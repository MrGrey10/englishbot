import asyncio
import http.server
import io
import json
import logging
import os
import random
import re
import threading

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db
import srs
from ai_generator import generate_grammar_exercises, generate_grammar_lesson, generate_new_words, generate_patterns, generate_phrases, generate_reading_text, generate_speak_sentences, generate_tense_lesson, generate_tense_phrases, score_speak_answer, text_to_speech, transcribe_audio
from tutor_chat import tutor_open, tutor_reply, roleplay_open, roleplay_reply

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

PHRASE, TRANSLATION, EXAMPLE = range(3)
GEN_LEVEL, GEN_TOPIC = range(2)
CHAT_ACTIVE = 0
GRAM_LEVEL, GRAM_ANSWER = range(2)
PAT_MENU, PAT_LEVEL = range(2)
DRILL_LEVEL, DRILL_ACTIVE = range(2)
READ_LEVEL = 0
SPEAK_LEVEL, SPEAK_ACTIVE = range(2)
REPEAT_ACTIVE = 0
TENSE_SELECT = 0
LESSON_LEVEL = 0
ROLEPLAY_TOPIC, ROLEPLAY_ACTIVE = range(2)
DRILL_WORDS_ACTIVE = 0
NEW_WORDS_LEVEL, NEW_WORDS_TOPIC = range(2)

_ROLEPLAY_TOPICS = [
    "Work Interview",
    "Scrum Meeting",
    "In restaurant",
    "In hotel reception",
    "In airport",
    "With taxi driver",
    "Small talk",
    "In shop",
]

MENU_TEXT = "English Phrases Bot — learn with spaced repetition (SM-2)\n\nWhat would you like to do?"

_GEN_TOPICS = ["Small talk", "Work", "IT Interview", "Travel", "Food & drink", "Relationships", "Sports", "Slang", "Any"]

_TENSES = [
    "Present Simple",
    "Present Continuous",
    "Present Perfect",
    "Present Perfect Continuous",
    "Past Simple",
    "Past Continuous",
    "Past Perfect",
    "Future Simple",
    "Future Continuous",
    "Future Perfect",
    "Going to Future",
    "Second Conditional",
    "Third Conditional",
]


# ── Utility ──────────────────────────────────────────────────────────────────

_FIXED_KB = ReplyKeyboardMarkup(
    [["🏠 Home", "🔄 Drill Phrases"]],
    resize_keyboard=True,
    is_persistent=True,
)


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 Add Phrase", callback_data="menu:add"),
            InlineKeyboardButton("🤖 Generate AI", callback_data="menu:generate"),
        ],
        [
            InlineKeyboardButton("📚 Phrases", callback_data="menu:phrases"),
            InlineKeyboardButton("💬 Chatting", callback_data="menu:chat"),
        ],
        [
            InlineKeyboardButton("✍️ Grammar", callback_data="menu:grammar"),
            InlineKeyboardButton("🎯 Patterns", callback_data="menu:patterns"),
        ],
        [
            InlineKeyboardButton("📖 Reading", callback_data="menu:reading"),
            InlineKeyboardButton("🗣 Speak", callback_data="menu:speak"),
        ],
        [
            InlineKeyboardButton("🔄 Drill Phrases", callback_data="menu:drill"),
            InlineKeyboardButton("🕐 Tense", callback_data="menu:tense"),
        ],
        [
            InlineKeyboardButton("🎓 Lesson", callback_data="menu:lesson"),
            InlineKeyboardButton("🎭 Role Play", callback_data="menu:roleplay"),
        ],
        [
            InlineKeyboardButton("📋 Irregular Verbs", callback_data="menu:irreg"),
            InlineKeyboardButton("🆕 New Words", callback_data="menu:new_words"),
        ],
        [
            InlineKeyboardButton("📖 Vocabulary", callback_data="menu:vocab"),
            InlineKeyboardButton("🔤 Drill Words", callback_data="menu:drill_words"),
        ],
    ])


def _back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")]])


def _rating_keyboard(phrase_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Again", callback_data=f"rate:{phrase_id}:0"),
            InlineKeyboardButton("Hard",  callback_data=f"rate:{phrase_id}:2"),
        ],
        [
            InlineKeyboardButton("Good",  callback_data=f"rate:{phrase_id}:4"),
            InlineKeyboardButton("Easy",  callback_data=f"rate:{phrase_id}:5"),
        ],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])


# ── Generic commands ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Quick access buttons:", reply_markup=_FIXED_KB)
    await update.message.reply_text(MENU_TEXT, reply_markup=_main_menu_keyboard())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(MENU_TEXT, reply_markup=_main_menu_keyboard())


async def cb_show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(MENU_TEXT, reply_markup=_main_menu_keyboard())
    return ConversationHandler.END


async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler for the fixed 🏠 Home / 🔄 Drill reply-keyboard buttons inside any conversation."""
    context.user_data.clear()
    await update.message.reply_text(MENU_TEXT, reply_markup=_main_menu_keyboard())
    return ConversationHandler.END


# ── Add phrase conversation ───────────────────────────────────────────────────

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message
    await msg.reply_text("Send me the English phrase or word:")
    return PHRASE


async def add_got_phrase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["phrase"] = update.message.text.strip()
    await update.message.reply_text("Now send the translation:")
    return TRANSLATION


async def add_got_translation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["translation"] = update.message.text.strip()
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Skip", callback_data="skip_example")]])
    await update.message.reply_text("Example sentence? (or tap Skip)", reply_markup=keyboard)
    return EXAMPLE


async def add_got_example(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _finish_add(update.message, context, example=update.message.text.strip())
    return ConversationHandler.END


async def add_skip_example(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    await _finish_add(update.callback_query.message, context, example=None)
    return ConversationHandler.END


async def _finish_add(message, context: ContextTypes.DEFAULT_TYPE, example: str | None) -> None:
    user_id = message.chat.id
    phrase      = context.user_data.pop("phrase", "")
    translation = context.user_data.pop("translation", "")
    db.add_phrase(user_id, phrase, translation, example)
    await message.reply_text(
        f'Saved: <b>{phrase}</b> — {translation}',
        parse_mode="HTML",
        reply_markup=_back_to_menu_keyboard(),
    )


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Cancelled.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


# ── Review ────────────────────────────────────────────────────────────────────

async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.message

    user_id = update.effective_user.id
    due = db.get_due_phrases(user_id)
    if not due:
        await message.reply_text(
            "Nothing due right now. Come back later or add more phrases!",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    context.user_data["queue"] = [dict(row) for row in due]
    context.user_data["reviewed"] = 0
    await _show_next(message, context)


async def _show_next(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    queue = context.user_data.get("queue", [])
    if not queue:
        reviewed = context.user_data.pop("reviewed", 0)
        await message.reply_text(
            f"Session done! Reviewed {reviewed} phrase(s).",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    item = queue[0]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Show Answer", callback_data=f"show:{item['id']}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])
    remaining = len(queue)
    await message.reply_text(
        f"[{remaining} left]\n\nTranslate:\n\n<b>{item['phrase']}</b>",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def cb_show_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    phrase_id = int(query.data.split(":")[1])
    queue = context.user_data.get("queue", [])

    if not queue or queue[0]["id"] != phrase_id:
        await query.edit_message_text(
            "Session expired.",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    item = queue[0]
    example_line = f"\n\nExample: <i>{item['example']}</i>" if item.get("example") else ""

    await query.edit_message_text(
        f"<b>{item['phrase']}</b>\n\n{item['translation']}{example_line}\n\nHow well did you remember?",
        parse_mode="HTML",
        reply_markup=_rating_keyboard(phrase_id),
    )


async def cb_rate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    _, phrase_id_s, quality_s = query.data.split(":")
    phrase_id, quality = int(phrase_id_s), int(quality_s)

    queue = context.user_data.get("queue", [])
    if not queue or queue[0]["id"] != phrase_id:
        await query.edit_message_text(
            "Session expired.",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    item = queue.pop(0)
    context.user_data["reviewed"] = context.user_data.get("reviewed", 0) + 1

    new_interval, new_ef, new_reps = srs.sm2(
        item["repetitions"], item["ease_factor"], item["interval"], quality
    )
    db.update_srs(phrase_id, new_ef, new_interval, new_reps)

    label = {0: "Again", 2: "Hard", 4: "Good", 5: "Easy"}.get(quality, "?")
    await query.edit_message_text(
        f"<b>{item['phrase']}</b> — {label}\nNext review in {new_interval} day(s).",
        parse_mode="HTML",
    )
    await _show_next(query.message, context)


# ── List ──────────────────────────────────────────────────────────────────────

PAGE = 5


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.message

    user_id = update.effective_user.id
    total = db.count_phrases(user_id)
    if total == 0:
        await message.reply_text(
            "No phrases yet. Use the Add Phrase button to start!",
            reply_markup=_back_to_menu_keyboard(),
        )
        return
    await _send_list(message, user_id, 0)


async def cb_list_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    offset = int(query.data.split(":")[1])
    rows = db.get_all_phrases(user_id, offset, PAGE)
    total = db.count_phrases(user_id)
    text, markup = _build_list_view(rows, total, offset)
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)


async def _send_list(message, user_id: int, offset: int) -> None:
    rows = db.get_all_phrases(user_id, offset, PAGE)
    total = db.count_phrases(user_id)
    text, markup = _build_list_view(rows, total, offset)
    await message.reply_text(text, parse_mode="HTML", reply_markup=markup)


def _build_list_view(rows, total: int, offset: int):
    lines = []
    delete_btns = []
    for i, r in enumerate(rows, offset + 1):
        lines.append(f"{i}. <b>{r['phrase']}</b> — {r['translation']}")
        delete_btns.append(InlineKeyboardButton(f"🗑 {i}", callback_data=f"del_phrase:{r['id']}:{offset}"))
    text = "\n".join(lines) + f"\n\n<i>{total} phrase(s) total</i>"

    rows_kb = []
    if delete_btns:
        rows_kb.append(delete_btns)

    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton("← Prev", callback_data=f"page:{offset - PAGE}"))
    if offset + PAGE < total:
        nav.append(InlineKeyboardButton("Next →", callback_data=f"page:{offset + PAGE}"))

    if nav:
        rows_kb.append(nav)
    rows_kb.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")])
    markup = InlineKeyboardMarkup(rows_kb)
    return text, markup


async def cb_delete_phrase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Deleted!")

    parts = query.data.split(":")
    phrase_id, offset = int(parts[1]), int(parts[2])
    user_id = update.effective_user.id

    db.delete_phrase(phrase_id, user_id)

    total = db.count_phrases(user_id)
    if total == 0:
        await query.edit_message_text("No phrases left.", reply_markup=_back_to_menu_keyboard())
        return

    if offset >= total:
        offset = max(0, offset - PAGE)

    rows = db.get_all_phrases(user_id, offset, PAGE)
    text, markup = _build_list_view(rows, total, offset)
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)


# ── Generate (AI phrases) ─────────────────────────────────────────────────────

async def gen_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(l, callback_data=f"level:{l}") for l in ("A1", "A2", "B1")],
        [InlineKeyboardButton(l, callback_data=f"level:{l}") for l in ("B2", "C1", "C2")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])
    await msg.reply_text("Choose your English level:", reply_markup=keyboard)
    return GEN_LEVEL


async def gen_got_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    level = query.data.split(":")[1]
    context.user_data["gen_level"] = level

    rows = [
        [InlineKeyboardButton(t, callback_data=f"topic:{t}") for t in pair]
        for pair in [_GEN_TOPICS[i:i+2] for i in range(0, len(_GEN_TOPICS), 2)]
    ]
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:home")])
    await query.edit_message_text(
        f"Level: <b>{level}</b>\n\nChoose a topic or type your own:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return GEN_TOPIC


async def gen_got_topic_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    topic = query.data.split(":", 1)[1]
    context.user_data["gen_topic"] = None if topic == "Any" else topic

    level = context.user_data.get("gen_level", "B1")
    await query.edit_message_text(
        f"Level: <b>{level}</b> · Topic: <b>{topic}</b>",
        parse_mode="HTML",
    )
    await _run_generation(query.message, context)
    return ConversationHandler.END


async def gen_got_topic_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    topic = update.message.text.strip()
    context.user_data["gen_topic"] = topic

    level = context.user_data.get("gen_level", "B1")
    await update.message.reply_text(
        f"Level: <b>{level}</b> · Topic: <b>{topic}</b>",
        parse_mode="HTML",
    )
    await _run_generation(update.message, context)
    return ConversationHandler.END


async def gen_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Cancelled.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


async def _run_generation(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    level = context.user_data.get("gen_level", "B1")
    topic = context.user_data.get("gen_topic")

    wait_msg = await message.reply_text("Generating phrases... ⏳")
    try:
        phrases = await generate_phrases(level, topic)
        context.user_data["gen_phrases"] = phrases
        context.user_data["gen_saved"] = 0
        await wait_msg.delete()
        await _show_generated_phrase(message, context, 0)
    except Exception as e:
        logger.error("generate_phrases error: %s", e)
        await wait_msg.edit_text(
            "Could not generate phrases.\n"
            "Make sure GROQ_API_KEY is set in .env and restart the bot.",
            reply_markup=_back_to_menu_keyboard(),
        )


async def _show_generated_phrase(message, context: ContextTypes.DEFAULT_TYPE, index: int) -> None:
    phrases = context.user_data.get("gen_phrases", [])

    if index >= len(phrases):
        saved = context.user_data.pop("gen_saved", 0)
        total = len(phrases)
        context.user_data.pop("gen_phrases", None)
        await message.reply_text(
            f"Done! Saved {saved}/{total} phrase(s).",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    p = phrases[index]
    level = context.user_data.get("gen_level", "")
    example_uk_line = f"\n   🇺🇦 {p['example_uk']}" if p.get("example_uk") else ""
    text = (
        f"<b>Phrase {index + 1}/{len(phrases)}</b>  [{level}]\n\n"
        f"🔤 <b>{p['phrase']}</b>\n"
        f"📖 {p['translation']}\n\n"
        f"💬 <i>{p['example']}</i>{example_uk_line}\n\n"
        f"🏷 {p['context']}"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("💾 Save", callback_data=f"gen_save:{index}"),
        InlineKeyboardButton("⏭ Skip", callback_data=f"gen_skip:{index}"),
    ]])
    await message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def cb_gen_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    index = int(query.data.split(":")[1])
    phrases = context.user_data.get("gen_phrases", [])

    if index < len(phrases):
        p = phrases[index]
        example_sentence = p.get("example", "")
        example_uk = p.get("example_uk", "")
        translation = example_uk or p.get("translation", "")
        note = f"{p['phrase']} — {p['translation']}" if p.get("translation") else p.get("phrase", "")
        db.add_phrase(
            update.effective_user.id,
            example_sentence,
            translation,
            note,
        )
        context.user_data["gen_saved"] = context.user_data.get("gen_saved", 0) + 1
        await query.answer("Saved!")
    else:
        await query.answer()

    await query.edit_message_reply_markup(None)
    await _show_generated_phrase(query.message, context, index + 1)


async def cb_gen_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    index = int(query.data.split(":")[1])
    await query.edit_message_reply_markup(None)
    await _show_generated_phrase(query.message, context, index + 1)


# ── Tutor Chat ────────────────────────────────────────────────────────────────

_CHAT_END_KB = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 End Chat", callback_data="chat:end")]])


def _split_chat_reply(reply: str) -> tuple[str, str]:
    """Split reply into (corrections, response). Corrections are leading ✏️ lines."""
    lines = reply.split('\n')
    correction_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith('✏️'):
            correction_lines.append(line)
        elif line.strip() == '' and correction_lines:
            i += 1
            break
        else:
            break
        i += 1
    return '\n'.join(correction_lines).strip(), '\n'.join(lines[i:]).strip()


def _tts_safe(text: str) -> str:
    """Strip all correction lines so TTS only speaks the dialogue part."""
    lines = [l for l in text.split('\n') if '✏️' not in l]
    return '\n'.join(lines).strip()


async def chat_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    context.user_data["chat_history"] = []

    wait_msg = await msg.reply_text("💬 Picking a topic... ⏳")
    try:
        topic, opening = await tutor_open()
    except Exception as e:
        logger.error("tutor_open error: %s", e)
        await wait_msg.delete()
        await msg.reply_text(
            "👋 Hey! I'm your English tutor. What would you like to talk about today?\n\n"
            "Tap <b>End Chat</b> or send /cancel to go back.",
            parse_mode="HTML",
            reply_markup=_CHAT_END_KB,
        )
        return CHAT_ACTIVE

    context.user_data["chat_history"].append({"role": "assistant", "content": opening})

    await wait_msg.delete()
    await msg.reply_text(
        f"💬 Topic: <b>{topic.title()}</b>\n\n{opening}",
        parse_mode="HTML",
        reply_markup=_CHAT_END_KB,
    )

    await update.effective_chat.send_action(ChatAction.RECORD_VOICE)
    try:
        audio = await text_to_speech(opening)
        await msg.reply_voice(io.BytesIO(audio))
    except Exception as e:
        logger.error("TTS error in chat_start: %s", e)

    return CHAT_ACTIVE


async def _process_chat_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str
) -> int:
    message = update.message
    history = context.user_data.get("chat_history", [])

    await update.effective_chat.send_action(ChatAction.TYPING)

    try:
        reply = await tutor_reply(user_text, history)
    except Exception as e:
        logger.error("tutor_reply error: %s", e)
        await message.reply_text("Something went wrong. Try again.", reply_markup=_CHAT_END_KB)
        return CHAT_ACTIVE

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply})
    if len(history) > 20:
        history = history[-20:]
    context.user_data["chat_history"] = history

    corrections, response = _split_chat_reply(reply)

    if corrections:
        await message.reply_text(corrections)

    response_text = response or reply
    await message.reply_text(response_text, reply_markup=_CHAT_END_KB)

    await update.effective_chat.send_action(ChatAction.RECORD_VOICE)
    try:
        audio = await text_to_speech(_tts_safe(response_text))
        await message.reply_voice(io.BytesIO(audio))
    except Exception as e:
        logger.error("TTS error: %s", e)

    return CHAT_ACTIVE


async def chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _process_chat_message(update, context, update.message.text.strip())


async def chat_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tg_file = await update.message.voice.get_file()
    audio_bytes = bytes(await tg_file.download_as_bytearray())

    wait = await update.message.reply_text("🎧 Transcribing... ⏳")
    try:
        transcription = await transcribe_audio(audio_bytes)
    except Exception as e:
        logger.error("transcribe_audio error in chat: %s", e)
        await wait.edit_text("Could not transcribe. Please type your message instead.")
        return CHAT_ACTIVE

    await wait.delete()
    await update.message.reply_text(f"🎤 You said: <i>{transcription}</i>", parse_mode="HTML")
    return await _process_chat_message(update, context, transcription)


async def chat_end_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.pop("chat_history", None)
    await query.message.reply_text("Chat ended! Keep practising. 💪", reply_markup=_main_menu_keyboard())
    return ConversationHandler.END


async def chat_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("chat_history", None)
    await update.message.reply_text("Chat ended.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


# ── Grammar (fill-in-the-blank) ───────────────────────────────────────────────

async def gram_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(l, callback_data=f"gram_level:{l}") for l in ("A1", "A2", "B1")],
        [InlineKeyboardButton(l, callback_data=f"gram_level:{l}") for l in ("B2", "C1", "C2")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])
    await msg.reply_text("Choose your English level for grammar practice:", reply_markup=keyboard)
    return GRAM_LEVEL


async def gram_got_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    level = query.data.split(":")[1]
    context.user_data["gram_level"] = level

    wait_msg = await query.message.reply_text("Generating exercises... ⏳")
    try:
        exercises = await generate_grammar_exercises(level)
        context.user_data["gram_exercises"] = exercises
        context.user_data["gram_index"] = 0
        context.user_data["gram_score"] = 0
        await wait_msg.delete()
        await _show_gram_exercise(query.message, context)
    except Exception as e:
        logger.error("generate_grammar_exercises error: %s", e)
        await wait_msg.edit_text(
            "Could not generate exercises. Make sure GROQ_API_KEY is set.",
            reply_markup=_back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    return GRAM_ANSWER


async def _show_gram_exercise(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    exercises = context.user_data.get("gram_exercises", [])
    index = context.user_data.get("gram_index", 0)
    level = context.user_data.get("gram_level", "")

    if index >= len(exercises):
        score = context.user_data.pop("gram_score", 0)
        total = len(exercises)
        context.user_data.pop("gram_exercises", None)
        context.user_data.pop("gram_index", None)
        context.user_data.pop("gram_level", None)
        await message.reply_text(
            f"Exercise complete! Your score: {score}/{total} 🎉",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    ex = exercises[index]
    await message.reply_text(
        f"<b>Exercise {index + 1}/{len(exercises)}</b>  [{level}]\n\n"
        f"Fill in the blank:\n\n"
        f"<b>{ex['sentence']}</b>\n\n"
        f"Type the missing word:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]]),
    )


async def gram_got_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_answer = update.message.text.strip().lower()
    exercises = context.user_data.get("gram_exercises", [])
    index = context.user_data.get("gram_index", 0)

    if index >= len(exercises):
        return ConversationHandler.END

    ex = exercises[index]
    correct = ex["answer"].strip().lower()
    is_correct = user_answer == correct

    if is_correct:
        context.user_data["gram_score"] = context.user_data.get("gram_score", 0) + 1
        result_line = "✅ Correct!"
    else:
        result_line = f"❌ Wrong. The answer is: <b>{ex['answer']}</b>"

    context.user_data["gram_index"] = index + 1

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Next ➡️", callback_data="gram:next"),
        InlineKeyboardButton("🏠 Menu", callback_data="menu:home"),
    ]])
    await update.message.reply_text(
        f"{result_line}\n\n"
        f"<i>{ex['full_sentence']}</i>\n\n"
        f"💡 {ex['hint']}",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return GRAM_ANSWER


async def gram_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await _show_gram_exercise(query.message, context)

    exercises = context.user_data.get("gram_exercises", [])
    index = context.user_data.get("gram_index", 0)
    if index >= len(exercises):
        return ConversationHandler.END
    return GRAM_ANSWER


async def gram_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("gram_exercises", "gram_index", "gram_score", "gram_level"):
        context.user_data.pop(key, None)
    await update.message.reply_text("Grammar practice cancelled.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


# ── Patterns ─────────────────────────────────────────────────────────────────

async def pat_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    user_id = update.effective_user.id
    count = db.count_patterns(user_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Generate New Patterns", callback_data="pat_menu:generate")],
        [InlineKeyboardButton(f"📚 My Saved Patterns ({count})", callback_data="pat_menu:my")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")],
    ])
    await msg.reply_text("🎯 Grammar Patterns\n\nLearn grammar by feeling patterns, not memorizing rules.", reply_markup=keyboard)
    return PAT_MENU


async def cb_pat_menu_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(l, callback_data=f"pat_level:{l}") for l in ("A1", "A2", "B1")],
        [InlineKeyboardButton(l, callback_data=f"pat_level:{l}") for l in ("B2", "C1", "C2")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])
    await query.message.reply_text("Choose your English level:", reply_markup=keyboard)
    return PAT_LEVEL


async def cb_pat_menu_my(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    rows = db.get_patterns(user_id)
    if not rows:
        await query.message.reply_text(
            "No saved patterns yet. Generate some first!",
            reply_markup=_back_to_menu_keyboard(),
        )
        return ConversationHandler.END
    context.user_data["pat_browse"] = [dict(row) for row in rows]
    await _show_browse_pattern(query.message, context, 0)
    return ConversationHandler.END


async def pat_got_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    level = query.data.split(":")[1]
    context.user_data["pat_level"] = level

    wait_msg = await query.message.reply_text("Generating patterns... ⏳")
    try:
        patterns = await generate_patterns(level)
        context.user_data["pat_patterns"] = patterns
        context.user_data["pat_saved"] = 0
        await wait_msg.delete()
        await _show_pattern(query.message, context, 0)
    except Exception as e:
        logger.error("generate_patterns error: %s", e)
        await wait_msg.edit_text(
            "Could not generate patterns. Make sure GROQ_API_KEY is set.",
            reply_markup=_back_to_menu_keyboard(),
        )

    return ConversationHandler.END


async def _show_pattern(message, context: ContextTypes.DEFAULT_TYPE, index: int) -> None:
    patterns = context.user_data.get("pat_patterns", [])

    if index >= len(patterns):
        saved = context.user_data.pop("pat_saved", 0)
        total = len(patterns)
        context.user_data.pop("pat_patterns", None)
        context.user_data.pop("pat_level", None)
        await message.reply_text(
            f"Done! Saved {saved}/{total} pattern(s).",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    p = patterns[index]
    level = context.user_data.get("pat_level", "")

    examples_text = "\n".join(
        f"• <i>{ex['en']}</i>\n  {ex['uk']}"
        for ex in p.get("examples", [])
    )

    text = (
        f"<b>Pattern {index + 1}/{len(patterns)}</b>  [{level}]\n\n"
        f"📌 <b>{p['name']}</b>\n"
        f"🔧 <code>{p['structure']}</code>\n\n"
        f"{examples_text}\n\n"
        f"💡 {p['note']}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💾 Save", callback_data=f"pat_save:{index}"),
            InlineKeyboardButton("⏭ Skip", callback_data=f"pat_skip:{index}"),
        ],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])
    await message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def cb_pat_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    index = int(query.data.split(":")[1])
    patterns = context.user_data.get("pat_patterns", [])

    if index < len(patterns):
        p = patterns[index]
        level = context.user_data.get("pat_level", "")
        db.add_pattern(
            update.effective_user.id,
            p["name"],
            p["structure"],
            p.get("note", ""),
            json.dumps(p.get("examples", []), ensure_ascii=False),
            level,
        )
        context.user_data["pat_saved"] = context.user_data.get("pat_saved", 0) + 1
        await query.answer("Saved!")
    else:
        await query.answer()

    await query.edit_message_reply_markup(None)
    await _show_pattern(query.message, context, index + 1)


async def cb_pat_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    index = int(query.data.split(":")[1])
    await query.edit_message_reply_markup(None)
    await _show_pattern(query.message, context, index + 1)


async def _show_browse_pattern(message, context: ContextTypes.DEFAULT_TYPE, index: int) -> None:
    patterns = context.user_data.get("pat_browse", [])
    if not patterns:
        return

    p = patterns[index]
    examples = json.loads(p.get("examples") or "[]")
    examples_text = "\n".join(
        f"• <i>{ex['en']}</i>\n  {ex['uk']}"
        for ex in examples
    )
    text = (
        f"<b>Pattern {index + 1}/{len(patterns)}</b>  [{p.get('level', '')}]\n\n"
        f"📌 <b>{p['pattern_name']}</b>\n"
        f"🔧 <code>{p['structure']}</code>\n\n"
        f"{examples_text}\n\n"
        f"💡 {p.get('note', '')}"
    )

    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"pat_browse:{index - 1}"))
    if index + 1 < len(patterns):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"pat_browse:{index + 1}"))

    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton("🏠 Done", callback_data="menu:home")])
    await message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))


async def cb_pat_browse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    index = int(query.data.split(":")[1])
    await _show_browse_pattern(query.message, context, index)


async def pat_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("pat_patterns", "pat_saved", "pat_level", "pat_browse"):
        context.user_data.pop(key, None)
    await update.message.reply_text("Patterns cancelled.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


# ── Drill ─────────────────────────────────────────────────────────────────────

def _normalize_answer(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.strip().lower())


def _build_saved_drill_items(user_id: int) -> list[dict]:
    items = []

    phrases = db.get_all_phrases(user_id, 0, 50)
    if phrases:
        sample = random.sample(list(phrases), min(6, len(phrases)))
        mid = max(1, len(sample) // 2)
        for p in sample[:mid]:
            items.append({
                "type": "voice",
                "question": (
                    f"🎤 <b>Say it in English!</b>\n\n"
                    f"Listen to the Ukrainian and speak the English phrase:\n\n"
                    f"<i>{p['translation']}</i>\n\n"
                    f"Send a 🎙 voice message:"
                ),
                "answer": p["phrase"],
                "hint": f"✏️ {p['phrase']}",
            })
        for p in sample[mid:]:
            items.append({
                "type": "phrase",
                "question": f"📝 <b>Saved Phrase</b>\n\nTranslate to English:\n\n<i>{p['translation']}</i>",
                "answer": p["phrase"],
                "hint": f"✏️ {p['phrase']}",
            })

    patterns = db.get_patterns(user_id)
    if patterns:
        for p in random.sample(list(patterns), min(5, len(patterns))):
            examples = json.loads(p.get("examples") or "[]")
            if examples:
                ex = random.choice(examples)
                items.append({
                    "type": "pattern",
                    "question": (
                        f"🎯 <b>Pattern: {p['pattern_name']}</b>\n"
                        f"<code>{p['structure']}</code>\n\n"
                        f"Translate to English:\n\n<i>{ex['uk']}</i>"
                    ),
                    "answer": ex["en"],
                    "hint": f"✏️ {ex['en']}",
                })

    return items


async def drill_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(l, callback_data=f"drill_level:{l}") for l in ("A1", "A2", "B1")],
        [InlineKeyboardButton(l, callback_data=f"drill_level:{l}") for l in ("B2", "C1", "C2")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])
    await msg.reply_text(
        "🔥 <b>Drill</b>\n\n"
        "Mixed exercises from your saved phrases, patterns, and AI grammar.\n\n"
        "Choose a level for grammar exercises:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return DRILL_LEVEL


async def drill_got_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    level = query.data.split(":")[1]
    context.user_data["drill_level"] = level

    user_id = update.effective_user.id
    wait_msg = await query.message.reply_text("Building your drill session... ⏳")

    items = _build_saved_drill_items(user_id)
    try:
        exercises = await asyncio.wait_for(
            generate_grammar_exercises(level, count=5), timeout=25
        )
        for ex in exercises:
            items.append({
                "type": "grammar",
                "question": (
                    f"✍️ <b>Grammar [{level}]</b>\n\n"
                    f"Fill in the blank:\n\n"
                    f"<b>{ex['sentence']}</b>\n\n"
                    f"Type the missing word:"
                ),
                "answer": ex["answer"],
                "hint": f"✏️ {ex['full_sentence']}\n💡 {ex['hint']}",
            })
    except asyncio.TimeoutError:
        logger.warning("Grammar generation timed out; proceeding without grammar exercises")
    except Exception as e:
        logger.error("drill grammar generation error: %s", e)

    if not items:
        await wait_msg.edit_text(
            "No drill content available. Add phrases or patterns first!",
            reply_markup=_back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    random.shuffle(items)
    context.user_data["drill_queue"] = items
    context.user_data["drill_index"] = 0
    context.user_data["drill_score"] = 0
    context.user_data["drill_streak"] = 0
    context.user_data["drill_max_streak"] = 0
    context.user_data["drill_correct"] = 0
    context.user_data["drill_total"] = len(items)

    await wait_msg.delete()
    await _show_drill_question(query.message, context)
    return DRILL_ACTIVE


async def _show_drill_question(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    queue = context.user_data["drill_queue"]
    index = context.user_data["drill_index"]
    total = context.user_data["drill_total"]
    score = context.user_data["drill_score"]
    streak = context.user_data["drill_streak"]

    if index >= len(queue):
        await _show_drill_result(message, context)
        return

    item = queue[index]
    streak_tag = f" · 🔥×{streak}" if streak >= 2 else ""
    header = f"[{index + 1}/{total}] · 🏆 {score} pts{streak_tag}"

    await message.reply_text(
        f"<b>{header}</b>\n\n{item['question']}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]]),
    )


async def _process_drill_answer(
    message, context: ContextTypes.DEFAULT_TYPE, user_answer: str, is_voice: bool = False
) -> int:
    queue = context.user_data.get("drill_queue", [])
    index = context.user_data.get("drill_index", 0)

    if index >= len(queue):
        return ConversationHandler.END

    item = queue[index]
    is_correct = _normalize_answer(user_answer) == _normalize_answer(item["answer"])

    if is_correct:
        context.user_data["drill_score"] += 10
        context.user_data["drill_streak"] += 1
        context.user_data["drill_correct"] = context.user_data.get("drill_correct", 0) + 1
        streak = context.user_data["drill_streak"]
        if streak > context.user_data.get("drill_max_streak", 0):
            context.user_data["drill_max_streak"] = streak
        if streak % 3 == 0:
            context.user_data["drill_score"] += 5
            result_line = "✅ Correct! 🔥 Streak bonus +5 pts!"
        else:
            result_line = "✅ Correct!"
    else:
        context.user_data["drill_streak"] = 0
        heard = f"\nI heard: <i>{user_answer}</i>" if is_voice else ""
        result_line = f"❌ Wrong!{heard}"

    context.user_data["drill_index"] = index + 1

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Next ➡️", callback_data="drill:next"),
        InlineKeyboardButton("🏠 Menu", callback_data="menu:home"),
    ]])
    await message.reply_text(
        f"{result_line}\n\n{item['hint']}",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return DRILL_ACTIVE


async def drill_got_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _process_drill_answer(update.message, context, update.message.text.strip())


async def drill_got_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    voice = update.message.voice
    tg_file = await voice.get_file()
    audio_bytes = bytes(await tg_file.download_as_bytearray())

    wait = await update.message.reply_text("🎧 Transcribing... ⏳")
    try:
        transcription = await transcribe_audio(audio_bytes)
    except Exception as e:
        logger.error("transcribe_audio error: %s", e)
        await wait.edit_text("Could not transcribe audio. Please type your answer instead.")
        return DRILL_ACTIVE

    await wait.delete()
    await update.message.reply_text(f"🎤 I heard: <i>{transcription}</i>", parse_mode="HTML")
    return await _process_drill_answer(update.message, context, transcription, is_voice=True)


async def drill_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    index = context.user_data.get("drill_index", 0)
    total = context.user_data.get("drill_total", 0)

    if index >= total:
        await _show_drill_result(query.message, context)
        return ConversationHandler.END

    await _show_drill_question(query.message, context)
    return DRILL_ACTIVE


async def _show_drill_result(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    score = context.user_data.pop("drill_score", 0)
    correct = context.user_data.pop("drill_correct", 0)
    total = context.user_data.pop("drill_total", 0)
    max_streak = context.user_data.pop("drill_max_streak", 0)
    for key in ("drill_queue", "drill_index", "drill_streak", "drill_level"):
        context.user_data.pop(key, None)

    pct = (correct / total * 100) if total else 0
    if pct >= 90:
        grade = "🌟 Excellent!"
    elif pct >= 70:
        grade = "🔥 Great job!"
    elif pct >= 50:
        grade = "💪 Good effort!"
    else:
        grade = "📚 Keep practicing!"

    await message.reply_text(
        f"<b>Drill Complete!</b>\n\n"
        f"{grade}\n\n"
        f"✅ Correct: {correct}/{total}\n"
        f"🏆 Score: {score} pts\n"
        f"🔥 Best streak: {max_streak}",
        parse_mode="HTML",
        reply_markup=_back_to_menu_keyboard(),
    )


async def drill_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("drill_queue", "drill_index", "drill_score", "drill_streak",
                "drill_max_streak", "drill_correct", "drill_total", "drill_level"):
        context.user_data.pop(key, None)
    await update.message.reply_text("Drill cancelled.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


# ── Reading ───────────────────────────────────────────────────────────────────

async def read_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(l, callback_data=f"read_level:{l}") for l in ("A1", "A2", "B1")],
        [InlineKeyboardButton(l, callback_data=f"read_level:{l}") for l in ("B2", "C1", "C2")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])
    await msg.reply_text("📖 Reading\n\nChoose your English level:", reply_markup=keyboard)
    return READ_LEVEL


async def read_got_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    level = query.data.split(":")[1]
    wait_msg = await query.message.reply_text("Generating reading text... ⏳")

    try:
        result = await generate_reading_text(level)
    except Exception as e:
        logger.error("generate_reading_text error: %s", e)
        await wait_msg.edit_text(
            "Could not generate text. Make sure GROQ_API_KEY is set.",
            reply_markup=_back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    vocab_lines = "\n".join(
        f"• <b>{v['word']}</b> — {v['meaning']}"
        for v in result.get("vocabulary", [])
    )

    text = (
        f"📖 <b>{result['title']}</b>  [{level}]\n\n"
        f"{result['text']}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"📚 <b>Vocabulary</b>\n{vocab_lines}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"🇺🇦 <i>{result['translation']}</i>"
    )

    await wait_msg.delete()
    await query.message.reply_text(text, parse_mode="HTML", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


async def read_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Reading cancelled.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


# ── Stats ─────────────────────────────────────────────────────────────────────

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.message

    user_id = update.effective_user.id
    s = db.get_stats(user_id)
    await message.reply_text(
        f"Your progress:\n\n"
        f"Total phrases:  {s['total']}\n"
        f"Due for review: {s['due']}\n"
        f"Well-learned:   {s['learned']} (3+ successful reviews)",
        reply_markup=_back_to_menu_keyboard(),
    )


# ── Phrases hub ──────────────────────────────────────────────────────────────

async def cb_phrases_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    stats = db.get_stats(user_id)
    pat_count = db.count_patterns(user_id)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✍️ Grammar (0)",
            callback_data="phrases:grammar",
        )],
        [InlineKeyboardButton(
            f"🎯 Patterns ({pat_count})",
            callback_data="phrases:patterns",
        )],
        [InlineKeyboardButton(
            f"📝 Topic Phrases ({stats['total']})  ·  {stats['due']} due",
            callback_data="phrases:topic",
        )],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")],
    ])
    await query.message.reply_text("📚 All Saved Content", reply_markup=keyboard)


async def cb_phrases_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    s = db.get_stats(user_id)
    if s["total"] == 0:
        await query.message.reply_text(
            "No phrases yet. Use Add Phrase or Generate AI to start!",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    review_label = f"🔁 Review ({s['due']} due)" if s["due"] > 0 else "🔁 Review (none due)"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(review_label, callback_data="phrases:review")],
        [InlineKeyboardButton("📋 Browse All", callback_data="phrases:browse")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu:phrases")],
    ])
    await query.message.reply_text(
        f"📝 Topic Phrases\n\n"
        f"Total: {s['total']}  ·  Due: {s['due']}  ·  Learned: {s['learned']}",
        reply_markup=keyboard,
    )


async def cb_phrases_patterns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    rows = db.get_patterns(user_id)
    if not rows:
        await query.message.reply_text(
            "No saved patterns yet. Generate some via 🎯 Patterns!",
            reply_markup=_back_to_menu_keyboard(),
        )
        return
    context.user_data["pat_browse"] = [dict(row) for row in rows]
    await _show_browse_pattern(query.message, context, 0)


async def cb_phrases_grammar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "✍️ Grammar\n\nNo saved grammar exercises yet.\n\nPractise via ✍️ Grammar in the main menu — saving will be added soon.",
        reply_markup=_back_to_menu_keyboard(),
    )


# ── Speak ─────────────────────────────────────────────────────────────────────

async def speak_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(l, callback_data=f"speak_level:{l}") for l in ("A1", "A2", "B1")],
        [InlineKeyboardButton(l, callback_data=f"speak_level:{l}") for l in ("B2", "C1", "C2")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])
    await msg.reply_text(
        "🗣 <b>Speak</b>\n\n"
        "I'll show you a Ukrainian sentence — record a 🎙 voice message with the English translation.\n"
        "I'll transcribe, score, and correct each attempt.\n\n"
        "Choose your level:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return SPEAK_LEVEL


async def speak_got_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    level = query.data.split(":")[1]
    context.user_data["speak_level"] = level

    wait_msg = await query.message.reply_text("Generating sentences... ⏳")
    try:
        sentences = await generate_speak_sentences(level)
        context.user_data["speak_sentences"] = sentences
        context.user_data["speak_index"] = 0
        context.user_data["speak_scores"] = []
        context.user_data["speak_total"] = len(sentences)
        await wait_msg.delete()
        await _show_speak_sentence(query.message, context)
    except Exception as e:
        logger.error("generate_speak_sentences error: %s", e)
        await wait_msg.edit_text(
            "Could not generate sentences. Make sure GROQ_API_KEY is set.",
            reply_markup=_back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    return SPEAK_ACTIVE


async def _show_speak_sentence(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    sentences = context.user_data["speak_sentences"]
    index = context.user_data["speak_index"]
    total = context.user_data["speak_total"]
    scores = context.user_data["speak_scores"]

    if index >= len(sentences):
        await _show_speak_result(message, context)
        return

    item = sentences[index]
    done = len(scores)
    score_tag = f"  🏆 {sum(scores)}/{done * 10}" if done > 0 else ""

    await message.reply_text(
        f"<b>[{index + 1}/{total}]{score_tag}</b>\n\n"
        f"🇺🇦 <b>{item['uk']}</b>\n\n"
        "Record a 🎙 voice message with the English translation:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]]),
    )


async def speak_got_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    sentences = context.user_data.get("speak_sentences", [])
    index = context.user_data.get("speak_index", 0)

    if index >= len(sentences):
        return ConversationHandler.END

    tg_file = await update.message.voice.get_file()
    audio_bytes = bytes(await tg_file.download_as_bytearray())

    wait = await update.message.reply_text("🎧 Transcribing... ⏳")
    try:
        transcription = await transcribe_audio(audio_bytes)
    except Exception as e:
        logger.error("transcribe_audio error in speak: %s", e)
        await wait.edit_text("Could not transcribe. Try recording again.")
        return SPEAK_ACTIVE

    await wait.delete()

    item = sentences[index]
    score_msg = await update.message.reply_text("🤔 Scoring... ⏳")
    try:
        result = await score_speak_answer(item["en"], transcription)
    except Exception as e:
        logger.error("score_speak_answer error: %s", e)
        context.user_data["speak_scores"].append(0)
        context.user_data["speak_index"] = index + 1
        is_last = context.user_data["speak_index"] >= context.user_data["speak_total"]
        await score_msg.edit_text(
            f"🎤 You said: <i>{transcription}</i>\n\nCould not score this one.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Finish 🏁" if is_last else "Next ➡️", callback_data="speak:next"),
                InlineKeyboardButton("🏠 Menu", callback_data="menu:home"),
            ]]),
        )
        return SPEAK_ACTIVE

    score = max(0, min(10, int(result.get("score", 0))))
    context.user_data["speak_scores"].append(score)
    context.user_data["speak_index"] = index + 1
    is_last = context.user_data["speak_index"] >= context.user_data["speak_total"]

    stars = "⭐" * score + "☆" * (10 - score)

    await score_msg.edit_text(
        f"🎤 You said: <i>{transcription}</i>\n\n"
        f"Score: <b>{score}/10</b>  {stars}\n\n"
        f"💡 {result.get('feedback', '')}\n\n"
        f"✅ <b>{result.get('corrected', item['en'])}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Finish 🏁" if is_last else "Next ➡️", callback_data="speak:next"),
                InlineKeyboardButton("💾 Save", callback_data=f"speak_save:{index}"),
            ],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
        ]),
    )
    return SPEAK_ACTIVE


async def speak_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    index = context.user_data.get("speak_index", 0)
    total = context.user_data.get("speak_total", 0)

    if index >= total:
        await _show_speak_result(query.message, context)
        return ConversationHandler.END

    await _show_speak_sentence(query.message, context)
    return SPEAK_ACTIVE


async def cb_speak_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query

    orig_index = int(query.data.split(":")[1])
    sentences = context.user_data.get("speak_sentences", [])

    if orig_index < len(sentences):
        item = sentences[orig_index]
        db.add_phrase(update.effective_user.id, item["en"], item["uk"], None)
        await query.answer("Saved!")
    else:
        await query.answer()

    cur_index = context.user_data.get("speak_index", 0)
    total = context.user_data.get("speak_total", 0)
    is_last = cur_index >= total
    await query.edit_message_reply_markup(InlineKeyboardMarkup([
        [InlineKeyboardButton("Finish 🏁" if is_last else "Next ➡️", callback_data="speak:next")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ]))
    return SPEAK_ACTIVE


async def _show_speak_result(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    scores = context.user_data.pop("speak_scores", [])
    total = context.user_data.pop("speak_total", 0)
    level = context.user_data.pop("speak_level", "")
    context.user_data.pop("speak_sentences", None)
    context.user_data.pop("speak_index", None)

    if not scores:
        await message.reply_text("Session ended.", reply_markup=_back_to_menu_keyboard())
        return

    total_score = sum(scores)
    max_score = total * 10
    pct = (total_score / max_score * 100) if max_score else 0

    if pct >= 90:
        grade = "🌟 Excellent!"
    elif pct >= 70:
        grade = "🔥 Great job!"
    elif pct >= 50:
        grade = "💪 Good effort!"
    else:
        grade = "📚 Keep practicing!"

    per_question = "  ".join(f"{s}/10" for s in scores)

    await message.reply_text(
        f"<b>Speak Complete!</b>  [{level}]\n\n"
        f"{grade}\n\n"
        f"🏆 Total: <b>{total_score}/{max_score}</b> ({pct:.0f}%)\n\n"
        f"Per sentence: {per_question}",
        parse_mode="HTML",
        reply_markup=_back_to_menu_keyboard(),
    )


async def speak_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("speak_sentences", "speak_index", "speak_scores", "speak_total", "speak_level"):
        context.user_data.pop(key, None)
    await update.message.reply_text("Speak practice cancelled.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


# ── Tense Lesson ─────────────────────────────────────────────────────────────

async def tense_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    rows = [
        [InlineKeyboardButton(t, callback_data=f"tense:{t}") for t in _TENSES[i:i+2]]
        for i in range(0, len(_TENSES), 2)
    ]
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:home")])
    await msg.reply_text(
        "🕐 <b>Tense Lesson</b>\n\nChoose a tense to learn:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return TENSE_SELECT


async def tense_got_tense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    tense = query.data.split(":", 1)[1]
    wait_msg = await query.message.reply_text(
        f"Generating lesson for <b>{tense}</b>... ⏳", parse_mode="HTML"
    )

    try:
        result = await generate_tense_lesson(tense)
    except Exception as e:
        logger.error("generate_tense_lesson error: %s", e)
        await wait_msg.edit_text(
            "Could not generate lesson. Make sure GROQ_API_KEY is set.",
            reply_markup=_back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    phrases = result.get("phrases", [])
    context.user_data["tense_name"] = tense
    context.user_data["tense_page"] = 1
    context.user_data["tense_shown"] = [p["en"] for p in phrases]
    context.user_data["tense_phrases"] = phrases

    signal_words = " · ".join(result.get("signal_words", []))
    phrases_text = "\n\n".join(
        f"{i+1}. <i>{p['en']}</i>\n  🇺🇦 {p['uk']}\n  💡 {p.get('note', '')}"
        for i, p in enumerate(phrases)
    )

    text = (
        f"🕐 <b>{result.get('tense', tense)}</b>  <i>Page 1</i>\n\n"
        f"📐 <b>Formation</b>\n{result.get('formation', '')}\n\n"
        f"✅ <b>When to use</b>\n{result.get('when_to_use', '')}\n\n"
        f"⏰ <b>Signal words:</b> {signal_words}\n\n"
        f"💬 <b>Common phrases</b>\n\n{phrases_text}"
    )

    save_buttons = [
        InlineKeyboardButton(f"💾 {i+1}", callback_data=f"tense_save:{i}")
        for i in range(len(phrases))
    ]
    save_rows = [save_buttons[i:i+3] for i in range(0, len(save_buttons), 3)]
    markup = InlineKeyboardMarkup(
        save_rows + [[
            InlineKeyboardButton("➡️ Next 6 phrases", callback_data="tense:next"),
            InlineKeyboardButton("🏠 Menu", callback_data="menu:home"),
        ]]
    )

    await wait_msg.delete()
    await query.message.reply_text(text, parse_mode="HTML", reply_markup=markup)
    return ConversationHandler.END


async def cb_tense_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    tense = context.user_data.get("tense_name")
    if not tense:
        await query.message.reply_text(
            "Session expired. Please start a new tense lesson from the menu.",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    page = context.user_data.get("tense_page", 1) + 1
    shown = context.user_data.get("tense_shown", [])

    wait_msg = await query.message.reply_text(f"Generating page {page}... ⏳")
    try:
        phrases = await generate_tense_phrases(tense, shown)
    except Exception as e:
        logger.error("generate_tense_phrases error: %s", e)
        await wait_msg.edit_text(
            "Could not generate phrases. Please try again.",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    context.user_data["tense_page"] = page
    context.user_data["tense_shown"] = shown + [p["en"] for p in phrases]
    context.user_data["tense_phrases"] = phrases

    phrases_text = "\n\n".join(
        f"{i+1}. <i>{p['en']}</i>\n  🇺🇦 {p['uk']}\n  💡 {p.get('note', '')}"
        for i, p in enumerate(phrases)
    )
    text = (
        f"🕐 <b>{tense}</b>  <i>Page {page}</i>\n\n"
        f"💬 <b>More phrases</b>\n\n{phrases_text}"
    )

    save_buttons = [
        InlineKeyboardButton(f"💾 {i+1}", callback_data=f"tense_save:{i}")
        for i in range(len(phrases))
    ]
    save_rows = [save_buttons[i:i+3] for i in range(0, len(save_buttons), 3)]
    markup = InlineKeyboardMarkup(
        save_rows + [[
            InlineKeyboardButton("➡️ Next 6 phrases", callback_data="tense:next"),
            InlineKeyboardButton("🏠 Menu", callback_data="menu:home"),
        ]]
    )

    await wait_msg.delete()
    await query.message.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def cb_tense_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    idx = int(query.data.split(":")[1])
    phrases = context.user_data.get("tense_phrases", [])
    if idx < len(phrases):
        p = phrases[idx]
        db.add_phrase(update.effective_user.id, p["en"], p["uk"], p.get("note") or None)
        await query.answer(f"Saved: {p['en'][:40]}!")
    else:
        await query.answer()


async def tense_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("tense_name", "tense_page", "tense_shown", "tense_phrases"):
        context.user_data.pop(key, None)
    await update.message.reply_text("Tense lesson cancelled.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


# ── Vocabulary ────────────────────────────────────────────────────────────────

_VOCAB_PAGE_SIZE = 8


async def vocab_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    await _show_vocab_page(msg, update.effective_user.id, 0)


async def _show_vocab_page(message, user_id: int, offset: int) -> None:
    total = db.count_phrases(user_id)
    if total == 0:
        await message.reply_text(
            "📖 <b>Vocabulary</b>\n\nNo saved words yet!\n\nUse 🆕 <b>New Words</b> to discover and save vocabulary.",
            parse_mode="HTML",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    phrases = db.get_all_phrases(user_id, offset, _VOCAB_PAGE_SIZE)
    lines = "\n\n".join(
        f"<b>{p['phrase']}</b> — {p['translation']}"
        for p in phrases
    )
    end = min(offset + _VOCAB_PAGE_SIZE, total)
    text = f"📖 <b>Vocabulary</b> ({total} words · {offset + 1}–{end})\n\n{lines}"

    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"vocab_page:{offset - _VOCAB_PAGE_SIZE}"))
    if offset + _VOCAB_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"vocab_page:{offset + _VOCAB_PAGE_SIZE}"))

    rows = ([nav] if nav else []) + [[InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]]
    await message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))


async def cb_vocab_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    offset = int(query.data.split(":")[1])
    await _show_vocab_page(query.message, update.effective_user.id, offset)


# ── Drill Words ───────────────────────────────────────────────────────────────

async def drill_words_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    user_id = update.effective_user.id
    phrases = db.get_all_phrases(user_id, 0, 50)
    if not phrases:
        await msg.reply_text(
            "No saved words yet! Save some vocabulary or phrases first.",
            reply_markup=_back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    sample = random.sample(list(phrases), min(10, len(phrases)))
    random.shuffle(sample)

    context.user_data["dw_queue"] = sample
    context.user_data["dw_index"] = 0
    context.user_data["dw_correct"] = 0

    await _show_drill_words_question(msg, context)
    return DRILL_WORDS_ACTIVE


async def _show_drill_words_question(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    queue = context.user_data["dw_queue"]
    index = context.user_data["dw_index"]
    total = len(queue)

    if index >= total:
        await _show_drill_words_result(message, context)
        return

    p = queue[index]
    await message.reply_text(
        f"<b>Word {index + 1}/{total}</b>\n\n"
        f"🔤 What does this mean in Ukrainian?\n\n"
        f"<b>{p['phrase']}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]]),
    )


async def drill_words_got_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    queue = context.user_data.get("dw_queue", [])
    index = context.user_data.get("dw_index", 0)
    if index >= len(queue):
        return ConversationHandler.END

    p = queue[index]
    user_answer = update.message.text.strip()
    is_correct = _normalize_answer(user_answer) == _normalize_answer(p["translation"])

    if is_correct:
        context.user_data["dw_correct"] = context.user_data.get("dw_correct", 0) + 1

    context.user_data["dw_index"] = index + 1
    is_last = context.user_data["dw_index"] >= len(queue)

    result_line = "✅ Correct!" if is_correct else f"❌ Wrong! Answer: <b>{p['translation']}</b>"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Finish 🏁" if is_last else "Next ➡️", callback_data="dw:next"),
        InlineKeyboardButton("🏠 Menu", callback_data="menu:home"),
    ]])
    await update.message.reply_text(result_line, parse_mode="HTML", reply_markup=keyboard)
    return DRILL_WORDS_ACTIVE


async def drill_words_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    index = context.user_data.get("dw_index", 0)
    total = len(context.user_data.get("dw_queue", []))

    if index >= total:
        await _show_drill_words_result(query.message, context)
        return ConversationHandler.END

    await _show_drill_words_question(query.message, context)
    return DRILL_WORDS_ACTIVE


async def _show_drill_words_result(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    correct = context.user_data.pop("dw_correct", 0)
    total = len(context.user_data.pop("dw_queue", []))
    context.user_data.pop("dw_index", None)

    pct = (correct / total * 100) if total else 0
    if pct >= 90:
        grade = "🌟 Excellent!"
    elif pct >= 70:
        grade = "🔥 Great job!"
    elif pct >= 50:
        grade = "💪 Good effort!"
    else:
        grade = "📚 Keep practicing!"

    await message.reply_text(
        f"<b>Drill Words Complete!</b>\n\n"
        f"{grade}\n\n"
        f"✅ Correct: {correct}/{total}",
        parse_mode="HTML",
        reply_markup=_back_to_menu_keyboard(),
    )


async def drill_words_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("dw_queue", "dw_index", "dw_correct"):
        context.user_data.pop(key, None)
    await update.message.reply_text("Drill Words cancelled.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


# ── New Words ─────────────────────────────────────────────────────────────────

async def new_words_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(l, callback_data=f"nw_level:{l}") for l in ("A1", "A2", "B1")],
        [InlineKeyboardButton(l, callback_data=f"nw_level:{l}") for l in ("B2", "C1", "C2")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])
    await msg.reply_text(
        "🆕 <b>New Words</b>\n\nChoose your level:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return NEW_WORDS_LEVEL


async def new_words_got_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    level = query.data.split(":")[1]
    context.user_data["nw_level"] = level
    context.user_data["nw_shown"] = []

    await query.edit_message_text(
        f"Level: <b>{level}</b>\n\n✏️ Type the topic you want words for\n(e.g. <i>Travel, Cooking, Technology</i>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]]),
    )
    return NEW_WORDS_TOPIC


async def new_words_got_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    topic = update.message.text.strip()
    context.user_data["nw_topic"] = topic
    context.user_data["nw_page"] = 1

    await update.message.reply_text(
        f"Level: <b>{context.user_data['nw_level']}</b> · Topic: <b>{topic}</b>",
        parse_mode="HTML",
    )
    await _run_new_words_page(update.message, context)
    return ConversationHandler.END


async def _run_new_words_page(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    level = context.user_data.get("nw_level", "B1")
    topic = context.user_data.get("nw_topic", "")
    shown = context.user_data.get("nw_shown", [])
    page = context.user_data.get("nw_page", 1)

    wait_msg = await message.reply_text(f"Generating page {page}... ⏳")
    try:
        words = await generate_new_words(level, topic, shown)
    except Exception as e:
        logger.error("generate_new_words error: %s", e)
        await wait_msg.edit_text(
            "Could not generate words. Make sure GROQ_API_KEY is set.",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    context.user_data["nw_words"] = words
    context.user_data["nw_shown"] = shown + [w["word"] for w in words]

    words_text = "\n\n".join(
        f"{i+1}. <b>{w['word']}</b> <i>({w.get('pos', '')})</i>\n"
        f"   🇺🇦 {w['translation']}\n"
        f"   💬 {w['example']}\n"
        f"      🇺🇦 {w.get('example_uk', '')}"
        for i, w in enumerate(words)
    )
    text = (
        f"🆕 <b>New Words — {level} · {topic}</b>  <i>Page {page}</i>\n\n"
        f"{words_text}"
    )

    save_buttons = [
        InlineKeyboardButton(f"💾 {i+1}", callback_data=f"nw_save:{i}")
        for i in range(len(words))
    ]
    save_rows = [save_buttons[i:i+5] for i in range(0, len(save_buttons), 5)]
    markup = InlineKeyboardMarkup(
        save_rows + [[
            InlineKeyboardButton("➡️ Next 10 words", callback_data="nw:next"),
            InlineKeyboardButton("🏠 Menu", callback_data="menu:home"),
        ]]
    )

    await wait_msg.delete()
    await message.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def cb_nw_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    idx = int(query.data.split(":")[1])
    words = context.user_data.get("nw_words", [])
    if idx < len(words):
        w = words[idx]
        example = f"({w.get('pos', '')}) {w.get('example', '')}" if w.get("example") else None
        db.add_phrase(update.effective_user.id, w["word"], w["translation"], example)
        await query.answer(f"Saved: {w['word']}!")
    else:
        await query.answer()


async def cb_nw_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not context.user_data.get("nw_topic"):
        await query.message.reply_text(
            "Session expired. Please start a new session from the menu.",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    context.user_data["nw_page"] = context.user_data.get("nw_page", 1) + 1
    await _run_new_words_page(query.message, context)


async def new_words_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("nw_level", "nw_topic", "nw_shown", "nw_words", "nw_page"):
        context.user_data.pop(key, None)
    await update.message.reply_text("New Words cancelled.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


# ── Grammar Lesson ────────────────────────────────────────────────────────────

async def lesson_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(l, callback_data=f"lesson_level:{l}") for l in ("A1", "A2", "B1")],
        [InlineKeyboardButton(l, callback_data=f"lesson_level:{l}") for l in ("B2", "C1", "C2")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])
    await msg.reply_text(
        "🎓 <b>Grammar Lesson</b>\n\n"
        "I'll pick a grammar rule for your level and give you a full lesson — "
        "explanation, examples, common mistakes, and a quick check.\n\n"
        "Every lesson is different. Choose your level:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return LESSON_LEVEL


async def lesson_got_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    level = query.data.split(":")[1]
    wait_msg = await query.message.reply_text(
        f"Generating lesson for level <b>{level}</b>... ⏳", parse_mode="HTML"
    )

    try:
        result = await generate_grammar_lesson(level)
    except Exception as e:
        logger.error("generate_grammar_lesson error: %s", e)
        await wait_msg.edit_text(
            "Could not generate lesson. Make sure GROQ_API_KEY is set.",
            reply_markup=_back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    examples_text = "\n\n".join(
        f"• <i>{ex['en']}</i>\n  🇺🇦 {ex['uk']}\n  💡 {ex.get('note', '')}"
        for ex in result.get("examples", [])
    )

    checks = result.get("quick_check", [])
    context.user_data["lesson_checks"] = checks
    context.user_data["lesson_check_index"] = 0
    context.user_data["lesson_check_score"] = 0

    mistake = result.get("common_mistake", "")

    text = (
        f"🎓 <b>{result.get('topic', '')} [{level}]</b>\n\n"
        f"<i>{result.get('tagline', '')}</i>\n\n"
        f"📝 <b>What it is</b>\n{result.get('explanation', '')}\n\n"
        f"🔧 <b>Structure</b>\n<code>{result.get('structure', '')}</code>\n\n"
        f"⚠️ <b>Common mistake</b>\n{mistake}\n\n"
        f"💬 <b>Examples</b>\n\n{examples_text}"
    )

    await wait_msg.delete()
    await query.message.reply_text(text, parse_mode="HTML")

    if checks:
        await _show_lesson_check(query.message, context)
        return LESSON_LEVEL

    await query.message.reply_text("Lesson complete! 🎉", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


async def _show_lesson_check(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    checks = context.user_data.get("lesson_checks", [])
    index = context.user_data.get("lesson_check_index", 0)
    score = context.user_data.get("lesson_check_score", 0)

    if index >= len(checks):
        total = len(checks)
        context.user_data.pop("lesson_checks", None)
        context.user_data.pop("lesson_check_index", None)
        context.user_data.pop("lesson_check_score", None)
        await message.reply_text(
            f"🧪 <b>Quick check complete!</b>  {score}/{total} correct 🎉",
            parse_mode="HTML",
            reply_markup=_back_to_menu_keyboard(),
        )
        return

    q = checks[index]
    await message.reply_text(
        f"🧪 <b>Quick check {index + 1}/{len(checks)}</b>\n\n"
        f"Fill in the blank:\n\n"
        f"<b>{q['sentence']}</b>\n\n"
        f"Type the missing word:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]]),
    )


async def lesson_check_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    checks = context.user_data.get("lesson_checks")
    if not checks:
        return ConversationHandler.END

    user_answer = update.message.text.strip().lower()
    index = context.user_data.get("lesson_check_index", 0)

    if index >= len(checks):
        return ConversationHandler.END

    q = checks[index]
    correct = q["answer"].strip().lower()
    is_correct = user_answer == correct

    if is_correct:
        context.user_data["lesson_check_score"] = context.user_data.get("lesson_check_score", 0) + 1
        result_line = "✅ Correct!"
    else:
        result_line = f"❌ Wrong. The answer is: <b>{q['answer']}</b>"

    context.user_data["lesson_check_index"] = index + 1

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Next ➡️", callback_data="lesson:next_check"),
        InlineKeyboardButton("🏠 Menu", callback_data="menu:home"),
    ]])
    await update.message.reply_text(
        f"{result_line}\n\n💡 {q.get('explanation', '')}",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return LESSON_LEVEL


async def lesson_next_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    checks = context.user_data.get("lesson_checks", [])
    index = context.user_data.get("lesson_check_index", 0)

    if index >= len(checks):
        await _show_lesson_check(query.message, context)
        return ConversationHandler.END

    await _show_lesson_check(query.message, context)
    return LESSON_LEVEL


async def lesson_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("lesson_checks", "lesson_check_index", "lesson_check_score"):
        context.user_data.pop(key, None)
    await update.message.reply_text("Lesson cancelled.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


# ── Repeat ───────────────────────────────────────────────────────────────────

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "it", "its", "i", "you", "he", "she", "we", "they", "do", "does",
    "did", "have", "has", "had", "will", "would", "can", "could", "may",
    "might", "shall", "should", "must", "and", "or", "but", "not", "no",
    "so", "if", "that", "this", "these", "those",
}


def _make_fill_question(phrase: str, translation: str) -> tuple[str, str]:
    words = phrase.split()
    candidates = [
        i for i, w in enumerate(words)
        if re.sub(r"[^\w]", "", w).lower() not in _STOPWORDS
        and len(re.sub(r"[^\w]", "", w)) > 2
    ]
    if not candidates:
        candidates = list(range(len(words)))
    idx = random.choice(candidates)
    clean_word = re.sub(r"[^\w]", "", words[idx]).lower()
    blanked = words[:]
    blanked[idx] = "___"
    question = (
        f"🔤 <b>Fill in the blank!</b>\n\n"
        f"<b>{' '.join(blanked)}</b>\n\n"
        f"🇺🇦 <i>{translation}</i>\n\n"
        f"Type the missing word:"
    )
    return question, clean_word


def _build_repeat_tasks(phrases: list) -> list:
    tasks = []
    for p in phrases:
        phrase_id = p["id"]
        phrase = p["phrase"]
        translation = p["translation"]
        tasks.append({
            "phrase_id": phrase_id,
            "type": "write",
            "question": (
                f"✍️ <b>Write it!</b>\n\n"
                f"🇺🇦 <i>{translation}</i>\n\n"
                f"Type the English phrase:"
            ),
            "answer": phrase,
        })
        tasks.append({
            "phrase_id": phrase_id,
            "type": "speak",
            "question": (
                f"🎤 <b>Say it!</b>\n\n"
                f"🇺🇦 <i>{translation}</i>\n\n"
                f"Send a 🎙 voice message with the English phrase:"
            ),
            "answer": phrase,
        })
        fill_q, fill_answer = _make_fill_question(phrase, translation)
        tasks.append({
            "phrase_id": phrase_id,
            "type": "fill",
            "question": fill_q,
            "answer": fill_answer,
        })
    return tasks


async def repeat_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    user_id = update.effective_user.id
    phrases = db.get_all_phrases(user_id, 0, 50)
    if not phrases:
        await msg.reply_text(
            "No saved phrases yet! Add some phrases first.",
            reply_markup=_back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    sample = random.sample(list(phrases), min(5, len(phrases)))
    tasks = _build_repeat_tasks(sample)

    context.user_data["repeat_tasks"] = tasks
    context.user_data["repeat_index"] = 0
    context.user_data["repeat_phrase_errors"] = {}
    context.user_data["repeat_phrase_count"] = len(sample)

    await _show_repeat_task(msg, context)
    return REPEAT_ACTIVE


async def _show_repeat_task(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    tasks = context.user_data["repeat_tasks"]
    index = context.user_data["repeat_index"]
    total_phrases = context.user_data["repeat_phrase_count"]

    if index >= len(tasks):
        await _show_repeat_result(message, context)
        return

    task = tasks[index]
    phrase_num = index // 3 + 1
    step_num = index % 3 + 1

    await message.reply_text(
        f"<b>Phrase {phrase_num}/{total_phrases} · Step {step_num}/3</b>\n\n{task['question']}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]]),
    )


async def repeat_got_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tasks = context.user_data.get("repeat_tasks", [])
    index = context.user_data.get("repeat_index", 0)
    if index >= len(tasks):
        return ConversationHandler.END

    task = tasks[index]
    if task["type"] == "speak":
        await update.message.reply_text(
            "🎙 Please send a voice message for this step.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]]),
        )
        return REPEAT_ACTIVE

    return await _check_repeat_answer(update.message, context, update.message.text.strip())


async def repeat_got_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tasks = context.user_data.get("repeat_tasks", [])
    index = context.user_data.get("repeat_index", 0)
    if index >= len(tasks):
        return ConversationHandler.END

    task = tasks[index]
    if task["type"] != "speak":
        await update.message.reply_text(
            "✍️ Please type your answer for this step.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]]),
        )
        return REPEAT_ACTIVE

    tg_file = await update.message.voice.get_file()
    audio_bytes = bytes(await tg_file.download_as_bytearray())

    wait = await update.message.reply_text("🎧 Transcribing... ⏳")
    try:
        transcription = await transcribe_audio(audio_bytes)
    except Exception as e:
        logger.error("transcribe_audio error in repeat: %s", e)
        await wait.edit_text("Could not transcribe. Please try again.")
        return REPEAT_ACTIVE

    await wait.delete()
    await update.message.reply_text(f"🎤 I heard: <i>{transcription}</i>", parse_mode="HTML")
    return await _check_repeat_answer(update.message, context, transcription)


async def _check_repeat_answer(
    message, context: ContextTypes.DEFAULT_TYPE, user_answer: str
) -> int:
    tasks = context.user_data["repeat_tasks"]
    index = context.user_data["repeat_index"]
    phrase_errors = context.user_data["repeat_phrase_errors"]

    task = tasks[index]
    phrase_id = task["phrase_id"]
    is_correct = _normalize_answer(user_answer) == _normalize_answer(task["answer"])

    if not is_correct and phrase_id not in phrase_errors:
        phrase_errors[phrase_id] = True

    context.user_data["repeat_index"] = index + 1
    is_last = context.user_data["repeat_index"] >= len(tasks)

    result_line = "✅ Correct!" if is_correct else f"❌ Wrong! The answer: <b>{task['answer']}</b>"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Finish 🏁" if is_last else "Next ➡️", callback_data="repeat:next"),
        InlineKeyboardButton("🏠 Menu", callback_data="menu:home"),
    ]])
    await message.reply_text(result_line, parse_mode="HTML", reply_markup=keyboard)
    return REPEAT_ACTIVE


async def repeat_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    index = context.user_data.get("repeat_index", 0)
    total = len(context.user_data.get("repeat_tasks", []))

    if index >= total:
        await _show_repeat_result(query.message, context)
        return ConversationHandler.END

    await _show_repeat_task(query.message, context)
    return REPEAT_ACTIVE


async def _show_repeat_result(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    phrase_count = context.user_data.pop("repeat_phrase_count", 0)
    phrase_errors = context.user_data.pop("repeat_phrase_errors", {})
    context.user_data.pop("repeat_tasks", None)
    context.user_data.pop("repeat_index", None)

    passed = phrase_count - len(phrase_errors)

    if passed == phrase_count:
        grade = "🌟 Perfect! All phrases mastered!"
    elif passed >= phrase_count * 0.7:
        grade = "🔥 Great job!"
    elif passed >= phrase_count * 0.5:
        grade = "💪 Good effort!"
    else:
        grade = "📚 Keep practicing!"

    await message.reply_text(
        f"<b>Drill Session Complete!</b>\n\n"
        f"{grade}\n\n"
        f"✅ Phrases fully passed: {passed}/{phrase_count}\n\n"
        f"<i>A phrase passes only when all 3 steps are correct.</i>",
        parse_mode="HTML",
        reply_markup=_back_to_menu_keyboard(),
    )


async def repeat_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("repeat_tasks", "repeat_index", "repeat_phrase_errors", "repeat_phrase_count"):
        context.user_data.pop(key, None)
    await update.message.reply_text("Drill session cancelled.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


# ── Role Play ─────────────────────────────────────────────────────────────────

_ROLEPLAY_END_KB = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 End Role Play", callback_data="roleplay:end")]])


async def roleplay_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    pairs = [_ROLEPLAY_TOPICS[i:i+2] for i in range(0, len(_ROLEPLAY_TOPICS), 2)]
    rows = [
        [InlineKeyboardButton(t, callback_data=f"roleplay_topic:{t}") for t in pair]
        for pair in pairs
    ]
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:home")])
    await msg.reply_text(
        "🎭 <b>Role Play</b>\n\nChoose a scenario to practise:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return ROLEPLAY_TOPIC


async def roleplay_topic_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    scenario = query.data.split(":", 1)[1]
    context.user_data["roleplay_scenario"] = scenario
    context.user_data["roleplay_history"] = []

    wait_msg = await query.message.reply_text("🎭 Setting the scene... ⏳")
    try:
        opening = await roleplay_open(scenario)
    except Exception as e:
        logger.error("roleplay_open error: %s", e)
        await wait_msg.delete()
        await query.message.reply_text(
            f"🎭 <b>{scenario}</b>\n\nLet's begin! I'll play my role — you respond in English.\n\nTap <b>End Role Play</b> or /cancel to stop.",
            parse_mode="HTML",
            reply_markup=_ROLEPLAY_END_KB,
        )
        return ROLEPLAY_ACTIVE

    context.user_data["roleplay_history"].append({"role": "assistant", "content": opening})

    await wait_msg.delete()
    await query.message.reply_text(
        f"🎭 <b>{scenario}</b>\n\n{opening}",
        parse_mode="HTML",
        reply_markup=_ROLEPLAY_END_KB,
    )

    await update.effective_chat.send_action(ChatAction.RECORD_VOICE)
    try:
        audio = await text_to_speech(opening)
        await query.message.reply_voice(io.BytesIO(audio))
    except Exception as e:
        logger.error("TTS error in roleplay_topic_selected: %s", e)

    return ROLEPLAY_ACTIVE


async def _process_roleplay_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str
) -> int:
    message = update.message
    scenario = context.user_data.get("roleplay_scenario", "")
    history = context.user_data.get("roleplay_history", [])

    await update.effective_chat.send_action(ChatAction.TYPING)

    try:
        reply = await roleplay_reply(user_text, history, scenario)
    except Exception as e:
        logger.error("roleplay_reply error: %s", e)
        await message.reply_text("Something went wrong. Try again.", reply_markup=_ROLEPLAY_END_KB)
        return ROLEPLAY_ACTIVE

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply})
    if len(history) > 20:
        history = history[-20:]
    context.user_data["roleplay_history"] = history

    corrections, response = _split_chat_reply(reply)

    if corrections:
        await message.reply_text(corrections)

    response_text = response or reply
    await message.reply_text(response_text, reply_markup=_ROLEPLAY_END_KB)

    await update.effective_chat.send_action(ChatAction.RECORD_VOICE)
    try:
        audio = await text_to_speech(_tts_safe(response_text))
        await message.reply_voice(io.BytesIO(audio))
    except Exception as e:
        logger.error("TTS error in roleplay: %s", e)

    return ROLEPLAY_ACTIVE


async def roleplay_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _process_roleplay_message(update, context, update.message.text.strip())


async def roleplay_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tg_file = await update.message.voice.get_file()
    audio_bytes = bytes(await tg_file.download_as_bytearray())

    wait = await update.message.reply_text("🎧 Transcribing... ⏳")
    try:
        transcription = await transcribe_audio(audio_bytes)
    except Exception as e:
        logger.error("transcribe_audio error in roleplay: %s", e)
        await wait.edit_text("Could not transcribe. Please type your message instead.")
        return ROLEPLAY_ACTIVE

    await wait.delete()
    await update.message.reply_text(f"🎤 You said: <i>{transcription}</i>", parse_mode="HTML")
    return await _process_roleplay_message(update, context, transcription)


async def roleplay_end_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.pop("roleplay_history", None)
    context.user_data.pop("roleplay_scenario", None)
    await query.message.reply_text("Role play ended! Great practice. 💪", reply_markup=_main_menu_keyboard())
    return ConversationHandler.END


async def roleplay_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("roleplay_history", None)
    context.user_data.pop("roleplay_scenario", None)
    await update.message.reply_text("Role play cancelled.", reply_markup=_back_to_menu_keyboard())
    return ConversationHandler.END


# ── Irregular Verbs ───────────────────────────────────────────────────────────

_IRREGULAR_VERBS: list[tuple[str, str, str, str, str]] = [
    # (base, past simple, past participle, example EN, example UK)
    ("be",        "was / were",       "been",            "She has been a teacher for ten years.",           "Вона працює вчителькою вже десять років."),
    ("beat",      "beat",             "beaten",          "Our team beat the champions last night.",         "Наша команда перемогла чемпіонів минулого вечора."),
    ("become",    "became",           "become",          "He became a doctor after years of study.",        "Він став лікарем після багатьох років навчання."),
    ("begin",     "began",            "begun",           "She has already begun the project.",              "Вона вже розпочала проєкт."),
    ("bend",      "bent",             "bent",            "He bent the rules just this once.",               "Він порушив правила лише цього разу."),
    ("bind",      "bound",            "bound",           "They bound the agreement with a handshake.",      "Вони скріпили угоду рукостисканням."),
    ("bite",      "bit",              "bitten",          "The dog has bitten its owner before.",            "Ця собака вже кусала свого господаря."),
    ("bleed",     "bled",             "bled",            "The cut bled for several minutes.",               "Рана кровоточила кілька хвилин."),
    ("blow",      "blew",             "blown",           "The wind has blown the leaves away.",             "Вітер здув листя геть."),
    ("break",     "broke",            "broken",          "She broke her phone by accident.",                "Вона випадково розбила телефон."),
    ("breed",     "bred",             "bred",            "They bred horses on a large farm.",               "Вони розводили коней на великій фермі."),
    ("bring",     "brought",          "brought",         "He brought flowers to the meeting.",              "Він приніс квіти на зустріч."),
    ("build",     "built",            "built",           "They built a new office last year.",              "Вони збудували новий офіс минулого року."),
    ("burn",      "burned / burnt",   "burned / burnt",  "She burned the toast this morning.",              "Вона спалила тост сьогодні вранці."),
    ("buy",       "bought",           "bought",          "We bought tickets in advance.",                   "Ми купили квитки заздалегідь."),
    ("catch",     "caught",           "caught",          "He caught the ball with one hand.",               "Він спіймав м'яч однією рукою."),
    ("choose",    "chose",            "chosen",          "She chose the blue dress for the party.",         "Вона обрала синю сукню на вечірку."),
    ("come",      "came",             "come",            "They have come a long way since then.",           "З того часу вони пройшли довгий шлях."),
    ("cost",      "cost",             "cost",            "The repairs cost more than expected.",            "Ремонт коштував дорожче, ніж очікувалося."),
    ("cut",       "cut",              "cut",             "He cut his finger while cooking.",                "Він порізав палець під час готування."),
    ("deal",      "dealt",            "dealt",           "She dealt with the problem quickly.",             "Вона швидко вирішила проблему."),
    ("dig",       "dug",              "dug",             "They dug a hole in the backyard.",                "Вони викопали яму у дворі."),
    ("do",        "did",              "done",            "Have you done your homework yet?",                "Ти вже зробив домашнє завдання?"),
    ("draw",      "drew",             "drawn",           "She drew a detailed map of the city.",            "Вона намалювала детальну карту міста."),
    ("dream",     "dreamed / dreamt", "dreamed / dreamt","He dreamed about his future career.",             "Він мріяв про свою майбутню кар'єру."),
    ("drink",     "drank",            "drunk",           "She drank three cups of coffee today.",           "Вона випила три чашки кави сьогодні."),
    ("drive",     "drove",            "driven",          "He has driven over 500 km today.",                "Він проїхав понад 500 км сьогодні."),
    ("eat",       "ate",              "eaten",           "We ate lunch at a small café.",                   "Ми пообідали в невеликому кафе."),
    ("fall",      "fell",             "fallen",          "The apple fell from the tree.",                   "Яблуко впало з дерева."),
    ("feed",      "fed",              "fed",             "She fed the baby every two hours.",               "Вона годувала дитину кожні дві години."),
    ("feel",      "felt",             "felt",            "I felt nervous before the presentation.",         "Я нервував перед презентацією."),
    ("fight",     "fought",           "fought",          "They fought hard to keep their jobs.",            "Вони боролися, щоб зберегти роботу."),
    ("find",      "found",            "found",           "She found her keys under the sofa.",              "Вона знайшла ключі під диваном."),
    ("fly",       "flew",             "flown",           "He has flown to New York three times.",           "Він літав до Нью-Йорка тричі."),
    ("forget",    "forgot",           "forgotten",       "I forgot to send the email.",                     "Я забув надіслати електронного листа."),
    ("forgive",   "forgave",          "forgiven",        "She forgave him for his mistake.",                "Вона пробачила йому його помилку."),
    ("freeze",    "froze",            "frozen",          "The pipes froze during the winter.",              "Труби замерзли взимку."),
    ("get",       "got",              "got / gotten",    "She got a promotion last month.",                 "Вона отримала підвищення минулого місяця."),
    ("give",      "gave",             "given",           "He gave a speech at the conference.",             "Він виступив із промовою на конференції."),
    ("go",        "went",             "gone",            "They have gone to the wrong address.",            "Вони пішли не за тією адресою."),
    ("grow",      "grew",             "grown",           "The company has grown rapidly.",                  "Компанія швидко зросла."),
    ("hang",      "hung",             "hung",            "She hung the painting on the wall.",              "Вона повісила картину на стіну."),
    ("have",      "had",              "had",             "We had a great time at the party.",               "Ми чудово провели час на вечірці."),
    ("hear",      "heard",            "heard",           "I heard a strange noise last night.",             "Минулої ночі я почув дивний звук."),
    ("hide",      "hid",              "hidden",          "The cat hid under the bed all day.",              "Кіт ховався під ліжком цілий день."),
    ("hit",       "hit",              "hit",             "The ball hit the window and cracked it.",         "М'яч влучив у вікно і розтріснув його."),
    ("hold",      "held",             "held",            "She held the baby carefully.",                    "Вона обережно тримала дитину."),
    ("hurt",      "hurt",             "hurt",            "He hurt his back at the gym.",                    "Він травмував спину в спортзалі."),
    ("keep",      "kept",             "kept",            "She kept all the important documents.",           "Вона зберегла всі важливі документи."),
    ("know",      "knew",             "known",           "He has known about this for weeks.",              "Він знав про це тижнями."),
    ("lay",       "laid",             "laid",            "She laid the table for dinner.",                  "Вона накрила стіл до вечері."),
    ("lead",      "led",              "led",             "He led the team to victory.",                     "Він привів команду до перемоги."),
    ("leave",     "left",             "left",            "They left the office early on Friday.",           "Вони пішли з офісу рано в п'ятницю."),
    ("lend",      "lent",             "lent",            "She lent me her umbrella.",                       "Вона позичила мені свою парасольку."),
    ("let",       "let",              "let",             "He let her borrow his car.",                      "Він дозволив їй позичити його машину."),
    ("lie",       "lay",              "lain",            "She lay in bed all morning.",                     "Вона пролежала в ліжку все ранок."),
    ("lose",      "lost",             "lost",            "I lost my wallet on the train.",                  "Я загубив гаманець у поїзді."),
    ("make",      "made",             "made",            "She made a delicious cake.",                      "Вона спекла смачний торт."),
    ("mean",      "meant",            "meant",           "I meant to call you earlier.",                    "Я мав намір зателефонувати тобі раніше."),
    ("meet",      "met",              "met",             "We met at a conference last year.",               "Ми познайомилися на конференції торік."),
    ("pay",       "paid",             "paid",            "He paid for dinner with a card.",                 "Він заплатив за вечерю карткою."),
    ("put",       "put",              "put",             "She put the report on his desk.",                 "Вона поклала звіт на його стіл."),
    ("read",      "read",             "read",            "Have you read this article yet?",                 "Ти вже прочитав цю статтю?"),
    ("ride",      "rode",             "ridden",          "She rode her bicycle to work.",                   "Вона їздила на велосипеді на роботу."),
    ("ring",      "rang",             "rung",            "The phone rang during the meeting.",              "Телефон задзвонив під час наради."),
    ("rise",      "rose",             "risen",           "The sun rose at 5:30 this morning.",              "Сьогодні вранці сонце зійшло о 5:30."),
    ("run",       "ran",              "run",             "He ran a marathon last weekend.",                 "Він пробіг марафон минулих вихідних."),
    ("say",       "said",             "said",            "She said she would call back.",                   "Вона сказала, що передзвонить."),
    ("see",       "saw",              "seen",            "I've never seen such a beautiful view.",          "Я ніколи не бачив такого красивого краєвиду."),
    ("seek",      "sought",           "sought",          "They sought advice from an expert.",              "Вони звернулися по пораду до експерта."),
    ("sell",      "sold",             "sold",            "He sold his car to buy a motorcycle.",            "Він продав машину, щоб купити мотоцикл."),
    ("send",      "sent",             "sent",            "She sent the report by email.",                   "Вона надіслала звіт електронною поштою."),
    ("set",       "set",              "set",             "He set a new record for the race.",               "Він встановив новий рекорд у перегонах."),
    ("shake",     "shook",            "shaken",          "She shook hands with the interviewer.",           "Вона потисла руку інтерв'юеру."),
    ("shine",     "shone",            "shone",           "The sun shone brightly all afternoon.",           "Сонце яскраво світило весь день."),
    ("shoot",     "shot",             "shot",            "The photographer shot hundreds of photos.",       "Фотограф зробив сотні знімків."),
    ("show",      "showed",           "shown",           "She showed me around the new office.",            "Вона показала мені новий офіс."),
    ("shut",      "shut",             "shut",            "He shut the window before the rain.",             "Він зачинив вікно до дощу."),
    ("sing",      "sang",             "sung",            "She sang at the corporate event.",                "Вона співала на корпоративному заході."),
    ("sink",      "sank",             "sunk",            "The boat sank after hitting a rock.",             "Човен затонув після зіткнення зі скелею."),
    ("sit",       "sat",              "sat",             "We sat in the conference room for hours.",        "Ми годинами сиділи в залі нарад."),
    ("sleep",     "slept",            "slept",           "I slept for only five hours last night.",         "Минулої ночі я спав лише п'ять годин."),
    ("speak",     "spoke",            "spoken",          "She has spoken English since childhood.",         "Вона розмовляє англійською з дитинства."),
    ("spend",     "spent",            "spent",           "He spent the whole day on the report.",           "Він витратив цілий день на звіт."),
    ("spread",    "spread",           "spread",          "The news spread quickly on social media.",        "Новини швидко поширилися в соціальних мережах."),
    ("stand",     "stood",            "stood",           "They stood in line for two hours.",               "Вони стояли в черзі дві години."),
    ("steal",     "stole",            "stolen",          "Someone stole his laptop at the café.",           "Хтось вкрав його ноутбук у кафе."),
    ("stick",     "stuck",            "stuck",           "The lid got stuck and she couldn't open it.",     "Кришка застрягла, і вона не могла її відкрити."),
    ("sting",     "stung",            "stung",           "A bee stung him on the hand.",                   "Бджола вжалила його в руку."),
    ("strike",    "struck",           "struck",          "Lightning struck the tree in the yard.",          "Блискавка вдарила в дерево у дворі."),
    ("swear",     "swore",            "sworn",           "He swore to tell the truth.",                     "Він поклявся говорити правду."),
    ("sweep",     "swept",            "swept",           "She swept the floor before guests arrived.",      "Вона підмела підлогу до приходу гостей."),
    ("swim",      "swam",             "swum",            "He swam across the lake in the morning.",         "Він переплив озеро вранці."),
    ("swing",     "swung",            "swung",           "The child swung on the playground.",              "Дитина гойдалася на майданчику."),
    ("take",      "took",             "taken",           "She took the train to avoid traffic.",            "Вона поїхала поїздом, щоб уникнути заторів."),
    ("teach",     "taught",           "taught",          "He taught English at a local school.",            "Він викладав англійську в місцевій школі."),
    ("tear",      "tore",             "torn",            "She tore the contract in frustration.",           "Вона в розпачі розірвала контракт."),
    ("tell",      "told",             "told",            "He told us the meeting was cancelled.",           "Він сказав нам, що нараду скасовано."),
    ("think",     "thought",          "thought",         "I thought the project was already done.",         "Я думав, що проєкт вже завершено."),
    ("throw",     "threw",            "thrown",          "She threw away old files to clear space.",        "Вона викинула старі файли, щоб звільнити місце."),
    ("understand","understood",       "understood",      "I finally understood what he meant.",             "Я нарешті зрозумів, що він мав на увазі."),
    ("wake",      "woke",             "woken",           "She woke up early for the flight.",               "Вона прокинулася рано через рейс."),
    ("wear",      "wore",             "worn",            "He wore a suit to the interview.",                "Він прийшов на співбесіду в костюмі."),
    ("win",       "won",              "won",             "Our team won the championship again.",            "Наша команда знову виграла чемпіонат."),
    ("withdraw",  "withdrew",         "withdrawn",       "She withdrew cash from the ATM.",                 "Вона зняла готівку в банкоматі."),
    ("write",     "wrote",            "written",         "He has written three books so far.",              "Він написав три книги на сьогодні."),
    ("arise",     "arose",            "arisen",          "A problem arose during the deployment.",          "Під час розгортання виникла проблема."),
    ("forbid",    "forbade",          "forbidden",       "Smoking is forbidden in the building.",           "Куріння заборонено в будівлі."),
    ("forecast",  "forecast",         "forecast",        "They forecast heavy rain for the weekend.",       "Вони передбачили сильний дощ на вихідні."),
    ("overcome",  "overcame",         "overcome",        "She overcame her fear of public speaking.",       "Вона подолала страх публічних виступів."),
    ("undertake", "undertook",        "undertaken",      "He undertook a new research project.",            "Він узявся за новий дослідницький проєкт."),
    ("upset",     "upset",            "upset",           "The news upset her greatly.",                     "Ці новини дуже засмутили її."),
    ("split",     "split",            "split",           "They split the bill equally at dinner.",          "Вони порівну розділили рахунок за вечерю."),
    ("bet",       "bet",              "bet",             "He bet on the wrong team.",                       "Він поставив не на ту команду."),
    ("burst",     "burst",            "burst",           "The water pipe burst last winter.",               "Водопровідна труба лопнула минулої зими."),
    ("cast",      "cast",             "cast",            "She cast a quick glance at the clock.",           "Вона кинула швидкий погляд на годинник."),
    ("shed",      "shed",             "shed",            "The company shed 200 jobs this year.",            "Компанія скоротила 200 робочих місць цього року."),
    ("slide",     "slid",             "slid",            "He slid the document across the table.",          "Він посунув документ по столу."),
    ("speed",     "sped",             "sped",            "She sped through the presentation.",              "Вона швидко провела презентацію."),
    ("spoil",     "spoiled / spoilt", "spoiled / spoilt","The food spoiled because of the power cut.",      "Їжа зіпсувалася через відключення електрики."),
    ("swell",     "swelled",          "swollen",         "His ankle swelled up after the fall.",            "Його щиколотка набрякла після падіння."),
    ("wind",      "wound",            "wound",           "She wound up the meeting early.",                 "Вона завчасно завершила нараду."),
]

IRREG_PAGE = 10


def _build_irreg_view(offset: int) -> tuple[str, InlineKeyboardMarkup]:
    total = len(_IRREGULAR_VERBS)
    page = _IRREGULAR_VERBS[offset:offset + IRREG_PAGE]

    lines = []
    save_btns = []
    for i, (base, past, pp, example_en, example_uk) in enumerate(page):
        num = offset + i + 1
        lines.append(
            f"{num}. <b>{base}</b>  →  {past}  →  {pp}\n"
            f"   💬 <i>{example_en}</i>\n"
            f"   🇺🇦 {example_uk}"
        )
        save_btns.append(InlineKeyboardButton(f"💾 {num}", callback_data=f"irreg_save:{offset + i}"))

    page_num = offset // IRREG_PAGE + 1
    total_pages = (total + IRREG_PAGE - 1) // IRREG_PAGE
    text = (
        f"📋 <b>Irregular Verbs</b>  [{page_num}/{total_pages}]\n\n"
        + "\n\n".join(lines)
    )

    rows_kb = []
    for i in range(0, len(save_btns), 5):
        rows_kb.append(save_btns[i:i + 5])

    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton("← Prev", callback_data=f"irreg:page:{offset - IRREG_PAGE}"))
    if offset + IRREG_PAGE < total:
        nav.append(InlineKeyboardButton("Next →", callback_data=f"irreg:page:{offset + IRREG_PAGE}"))
    if nav:
        rows_kb.append(nav)
    rows_kb.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")])

    return text, InlineKeyboardMarkup(rows_kb)


async def cb_irreg_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text, markup = _build_irreg_view(0)
    await query.message.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def cb_irreg_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    offset = int(query.data.split(":")[2])
    text, markup = _build_irreg_view(offset)
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)


async def cb_irreg_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    idx = int(query.data.split(":")[1])

    if idx < len(_IRREGULAR_VERBS):
        base, past, pp, example_en, example_uk = _IRREGULAR_VERBS[idx]
        db.add_phrase(
            update.effective_user.id,
            example_en,
            example_uk,
            f"{base} → {past} → {pp}",
        )
        await query.answer(f"Saved: {base}!")
    else:
        await query.answer()


# ── Health check server (required by Render Web Service) ─────────────────────

def _start_health_server() -> None:
    port = int(os.environ.get("PORT", 8080))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    logger.info("Health server listening on port %s", port)
    server.serve_forever()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    threading.Thread(target=_start_health_server, daemon=True).start()

    db.init_db()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    app = Application.builder().token(token).build()

    _fixed_btn = filters.Regex("^(🏠 Home|🔄 Drill)$")

    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add", add_start),
            CallbackQueryHandler(add_start, pattern="^menu:add$"),
        ],
        states={
            PHRASE: [
                MessageHandler(_fixed_btn, show_home),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_phrase),
            ],
            TRANSLATION: [
                MessageHandler(_fixed_btn, show_home),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_translation),
            ],
            EXAMPLE: [
                MessageHandler(_fixed_btn, show_home),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_example),
                CallbackQueryHandler(add_skip_example, pattern="^skip_example$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", add_cancel),
            MessageHandler(_fixed_btn, show_home),
            CallbackQueryHandler(cb_show_menu, pattern="^menu:home$"),
        ],
    )

    gen_conv = ConversationHandler(
        entry_points=[
            CommandHandler("generate", gen_start),
            CallbackQueryHandler(gen_start, pattern="^menu:generate$"),
        ],
        states={
            GEN_LEVEL: [CallbackQueryHandler(gen_got_level, pattern=r"^level:[ABC][12]$")],
            GEN_TOPIC: [
                CallbackQueryHandler(gen_got_topic_cb, pattern=r"^topic:.+$"),
                MessageHandler(_fixed_btn, show_home),
                MessageHandler(filters.TEXT & ~filters.COMMAND, gen_got_topic_text),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", gen_cancel),
            MessageHandler(_fixed_btn, show_home),
            CallbackQueryHandler(cb_show_menu, pattern="^menu:home$"),
        ],
    )

    chat_conv = ConversationHandler(
        entry_points=[
            CommandHandler("chat", chat_start),
            CallbackQueryHandler(chat_start, pattern="^menu:chat$"),
        ],
        states={
            CHAT_ACTIVE: [
                MessageHandler(_fixed_btn, show_home),
                MessageHandler(filters.VOICE, chat_voice_message),
                MessageHandler(filters.TEXT & ~filters.COMMAND, chat_message),
                CallbackQueryHandler(chat_end_cb, pattern="^chat:end$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", chat_cancel),
            MessageHandler(_fixed_btn, show_home),
            CallbackQueryHandler(cb_show_menu, pattern="^menu:home$"),
        ],
    )

    gram_conv = ConversationHandler(
        entry_points=[
            CommandHandler("grammar", gram_start),
            CallbackQueryHandler(gram_start, pattern="^menu:grammar$"),
        ],
        states={
            GRAM_LEVEL: [CallbackQueryHandler(gram_got_level, pattern=r"^gram_level:[ABC][12]$")],
            GRAM_ANSWER: [
                MessageHandler(_fixed_btn, show_home),
                MessageHandler(filters.TEXT & ~filters.COMMAND, gram_got_answer),
                CallbackQueryHandler(gram_next, pattern="^gram:next$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", gram_cancel),
            MessageHandler(_fixed_btn, show_home),
            CallbackQueryHandler(cb_show_menu, pattern="^menu:home$"),
        ],
    )

    pat_conv = ConversationHandler(
        entry_points=[
            CommandHandler("patterns", pat_start),
            CallbackQueryHandler(pat_start, pattern="^menu:patterns$"),
        ],
        states={
            PAT_MENU: [
                CallbackQueryHandler(cb_pat_menu_generate, pattern="^pat_menu:generate$"),
                CallbackQueryHandler(cb_pat_menu_my,       pattern="^pat_menu:my$"),
            ],
            PAT_LEVEL: [CallbackQueryHandler(pat_got_level, pattern=r"^pat_level:[ABC][12]$")],
        },
        fallbacks=[
            CommandHandler("cancel", pat_cancel),
            MessageHandler(_fixed_btn, show_home),
            CallbackQueryHandler(cb_show_menu, pattern="^menu:home$"),
        ],
    )


    read_conv = ConversationHandler(
        entry_points=[
            CommandHandler("reading", read_start),
            CallbackQueryHandler(read_start, pattern="^menu:reading$"),
        ],
        states={
            READ_LEVEL: [CallbackQueryHandler(read_got_level, pattern=r"^read_level:[ABC][12]$")],
        },
        fallbacks=[
            CommandHandler("cancel", read_cancel),
            MessageHandler(_fixed_btn, show_home),
            CallbackQueryHandler(cb_show_menu, pattern="^menu:home$"),
        ],
    )

    speak_conv = ConversationHandler(
        entry_points=[
            CommandHandler("speak", speak_start),
            CallbackQueryHandler(speak_start, pattern="^menu:speak$"),
        ],
        states={
            SPEAK_LEVEL: [CallbackQueryHandler(speak_got_level, pattern=r"^speak_level:[ABC][12]$")],
            SPEAK_ACTIVE: [
                MessageHandler(filters.VOICE, speak_got_voice),
                CallbackQueryHandler(speak_next, pattern="^speak:next$"),
                CallbackQueryHandler(cb_speak_save, pattern=r"^speak_save:\d+$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", speak_cancel),
            MessageHandler(_fixed_btn, show_home),
            CallbackQueryHandler(cb_show_menu, pattern="^menu:home$"),
        ],
    )

    repeat_conv = ConversationHandler(
        entry_points=[
            CommandHandler("drill", repeat_start),
            CallbackQueryHandler(repeat_start, pattern="^menu:drill$"),
            MessageHandler(filters.Regex("^🔄 Drill$"), repeat_start),
        ],
        states={
            REPEAT_ACTIVE: [
                MessageHandler(_fixed_btn, show_home),
                MessageHandler(filters.VOICE, repeat_got_voice),
                MessageHandler(filters.TEXT & ~filters.COMMAND, repeat_got_text),
                CallbackQueryHandler(repeat_next, pattern="^repeat:next$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", repeat_cancel),
            MessageHandler(_fixed_btn, show_home),
            CallbackQueryHandler(cb_show_menu, pattern="^menu:home$"),
        ],
    )

    tense_conv = ConversationHandler(
        entry_points=[
            CommandHandler("tense", tense_start),
            CallbackQueryHandler(tense_start, pattern="^menu:tense$"),
        ],
        states={
            TENSE_SELECT: [CallbackQueryHandler(tense_got_tense, pattern=r"^tense:.+$")],
        },
        fallbacks=[
            CommandHandler("cancel", tense_cancel),
            MessageHandler(_fixed_btn, show_home),
            CallbackQueryHandler(cb_show_menu, pattern="^menu:home$"),
        ],
    )

    lesson_conv = ConversationHandler(
        entry_points=[
            CommandHandler("lesson", lesson_start),
            CallbackQueryHandler(lesson_start, pattern="^menu:lesson$"),
        ],
        states={
            LESSON_LEVEL: [
                CallbackQueryHandler(lesson_got_level, pattern=r"^lesson_level:[ABC][12]$"),
                MessageHandler(_fixed_btn, show_home),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lesson_check_answer),
                CallbackQueryHandler(lesson_next_check, pattern="^lesson:next_check$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", lesson_cancel),
            MessageHandler(_fixed_btn, show_home),
            CallbackQueryHandler(cb_show_menu, pattern="^menu:home$"),
        ],
    )

    roleplay_conv = ConversationHandler(
        entry_points=[
            CommandHandler("roleplay", roleplay_start),
            CallbackQueryHandler(roleplay_start, pattern="^menu:roleplay$"),
        ],
        states={
            ROLEPLAY_TOPIC: [
                CallbackQueryHandler(roleplay_topic_selected, pattern=r"^roleplay_topic:.+$"),
            ],
            ROLEPLAY_ACTIVE: [
                MessageHandler(_fixed_btn, show_home),
                MessageHandler(filters.VOICE, roleplay_voice_message),
                MessageHandler(filters.TEXT & ~filters.COMMAND, roleplay_message),
                CallbackQueryHandler(roleplay_end_cb, pattern="^roleplay:end$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", roleplay_cancel),
            MessageHandler(_fixed_btn, show_home),
            CallbackQueryHandler(cb_show_menu, pattern="^menu:home$"),
        ],
    )


    drill_words_conv = ConversationHandler(
        entry_points=[
            CommandHandler("drillwords", drill_words_start),
            CallbackQueryHandler(drill_words_start, pattern="^menu:drill_words$"),
        ],
        states={
            DRILL_WORDS_ACTIVE: [
                MessageHandler(_fixed_btn, show_home),
                MessageHandler(filters.TEXT & ~filters.COMMAND, drill_words_got_answer),
                CallbackQueryHandler(drill_words_next, pattern="^dw:next$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", drill_words_cancel),
            MessageHandler(_fixed_btn, show_home),
            CallbackQueryHandler(cb_show_menu, pattern="^menu:home$"),
        ],
    )

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("review", cmd_review))
    app.add_handler(CommandHandler("list",   cmd_list))
    app.add_handler(CommandHandler("stats",  cmd_stats))
    app.add_handler(add_conv)
    app.add_handler(gen_conv)
    app.add_handler(chat_conv)
    app.add_handler(gram_conv)
    app.add_handler(pat_conv)
    app.add_handler(read_conv)
    app.add_handler(speak_conv)
    app.add_handler(repeat_conv)
    app.add_handler(tense_conv)
    app.add_handler(lesson_conv)
    app.add_handler(roleplay_conv)
    new_words_conv = ConversationHandler(
        entry_points=[
            CommandHandler("newwords", new_words_start),
            CallbackQueryHandler(new_words_start, pattern="^menu:new_words$"),
        ],
        states={
            NEW_WORDS_LEVEL: [CallbackQueryHandler(new_words_got_level, pattern=r"^nw_level:[ABC][12]$")],
            NEW_WORDS_TOPIC: [
                MessageHandler(_fixed_btn, show_home),
                MessageHandler(filters.TEXT & ~filters.COMMAND, new_words_got_topic),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", new_words_cancel),
            MessageHandler(_fixed_btn, show_home),
            CallbackQueryHandler(cb_show_menu, pattern="^menu:home$"),
        ],
    )

    app.add_handler(CommandHandler("vocab", vocab_start))
    app.add_handler(CallbackQueryHandler(vocab_start, pattern="^menu:vocab$"))
    app.add_handler(drill_words_conv)
    app.add_handler(new_words_conv)

    app.add_handler(MessageHandler(filters.Regex("^🏠 Home$"), show_home))
    app.add_handler(CallbackQueryHandler(cb_show_menu,       pattern="^menu:home$"))
    app.add_handler(CallbackQueryHandler(cmd_review,         pattern="^menu:review$"))
    app.add_handler(CallbackQueryHandler(cmd_list,           pattern="^menu:list$"))
    app.add_handler(CallbackQueryHandler(cmd_stats,          pattern="^menu:stats$"))
    app.add_handler(CallbackQueryHandler(cb_phrases_menu,    pattern="^menu:phrases$"))
    app.add_handler(CallbackQueryHandler(cb_phrases_topic,   pattern="^phrases:topic$"))
    app.add_handler(CallbackQueryHandler(cb_phrases_patterns, pattern="^phrases:patterns$"))
    app.add_handler(CallbackQueryHandler(cb_phrases_grammar, pattern="^phrases:grammar$"))
    app.add_handler(CallbackQueryHandler(cmd_review,         pattern="^phrases:review$"))
    app.add_handler(CallbackQueryHandler(cmd_list,           pattern="^phrases:browse$"))
    app.add_handler(CallbackQueryHandler(cb_show_answer, pattern=r"^show:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_rate,        pattern=r"^rate:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_list_page,    pattern=r"^page:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_delete_phrase, pattern=r"^del_phrase:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_gen_save,    pattern=r"^gen_save:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_gen_skip,    pattern=r"^gen_skip:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_pat_save,    pattern=r"^pat_save:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_pat_skip,    pattern=r"^pat_skip:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_pat_browse,  pattern=r"^pat_browse:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_irreg_menu,  pattern="^menu:irreg$"))
    app.add_handler(CallbackQueryHandler(cb_irreg_page,  pattern=r"^irreg:page:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_irreg_save,  pattern=r"^irreg_save:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_tense_save,  pattern=r"^tense_save:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_tense_next,  pattern="^tense:next$"))
    app.add_handler(CallbackQueryHandler(cb_vocab_page,  pattern=r"^vocab_page:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_nw_save,     pattern=r"^nw_save:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_nw_next,     pattern="^nw:next$"))

    logger.info("Bot started, polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
