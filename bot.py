import http.server
import json
import logging
import os
import threading

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
from ai_generator import generate_grammar_exercises, generate_patterns, generate_phrases
from tutor_chat import tutor_reply

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
PAT_LEVEL = 0

MENU_TEXT = "English Phrases Bot — learn with spaced repetition (SM-2)\n\nWhat would you like to do?"

_GEN_TOPICS = ["Small talk", "Work", "IT Interview", "Travel", "Food & drink", "Relationships", "Sports", "Slang", "Any"]


# ── Utility ──────────────────────────────────────────────────────────────────

def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 Add Phrase", callback_data="menu:add"),
            InlineKeyboardButton("🤖 Generate AI", callback_data="menu:generate"),
        ],
        [
            InlineKeyboardButton("🔁 Review", callback_data="menu:review"),
            InlineKeyboardButton("📋 List", callback_data="menu:list"),
        ],
        [
            InlineKeyboardButton("📊 Stats", callback_data="menu:stats"),
            InlineKeyboardButton("💬 Tutor Chat", callback_data="menu:chat"),
        ],
        [
            InlineKeyboardButton("✍️ Grammar", callback_data="menu:grammar"),
            InlineKeyboardButton("🎯 Patterns", callback_data="menu:patterns"),
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
    ])


# ── Generic commands ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(MENU_TEXT, reply_markup=_main_menu_keyboard())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(MENU_TEXT, reply_markup=_main_menu_keyboard())


async def cb_show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(MENU_TEXT, reply_markup=_main_menu_keyboard())


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
        [InlineKeyboardButton("Show Answer", callback_data=f"show:{item['id']}")]
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
    for i, r in enumerate(rows, offset + 1):
        lines.append(f"{i}. <b>{r['phrase']}</b> — {r['translation']}")
    text = "\n".join(lines) + f"\n\n<i>{total} phrase(s) total</i>"

    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton("← Prev", callback_data=f"page:{offset - PAGE}"))
    if offset + PAGE < total:
        nav.append(InlineKeyboardButton("Next →", callback_data=f"page:{offset + PAGE}"))

    rows_kb = [nav] if nav else []
    rows_kb.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")])
    markup = InlineKeyboardMarkup(rows_kb)
    return text, markup


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
    ])
    await msg.reply_text("Choose your English level:", reply_markup=keyboard)
    return GEN_LEVEL


async def gen_got_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    level = query.data.split(":")[1]
    context.user_data["gen_level"] = level

    rows = [
        [InlineKeyboardButton(t, callback_data=f"topic:{t}") for t in _GEN_TOPICS[:4]],
        [InlineKeyboardButton(t, callback_data=f"topic:{t}") for t in _GEN_TOPICS[4:]],
    ]
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
    text = (
        f"<b>Phrase {index + 1}/{len(phrases)}</b>  [{level}]\n\n"
        f"🔤 <b>{p['phrase']}</b>\n\n"
        f"📖 {p['translation']}\n\n"
        f"💬 <i>{p['example']}</i>\n\n"
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
        db.add_phrase(update.effective_user.id, p["phrase"], p["translation"], p.get("example"))
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


async def chat_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    context.user_data["chat_history"] = []
    await msg.reply_text(
        "👋 Hey! I'm your English tutor.\n\n"
        "Just chat with me in English — I'll correct any grammar mistakes and keep the conversation going.\n\n"
        "Tap <b>End Chat</b> or send /cancel to go back.",
        parse_mode="HTML",
        reply_markup=_CHAT_END_KB,
    )
    return CHAT_ACTIVE


async def chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_text = update.message.text.strip()
    history = context.user_data.get("chat_history", [])

    await update.effective_chat.send_action(ChatAction.TYPING)

    try:
        reply = await tutor_reply(user_text, history)
    except Exception as e:
        logger.error("tutor_reply error: %s", e)
        await update.message.reply_text(
            "Something went wrong. Try again.", reply_markup=_CHAT_END_KB
        )
        return CHAT_ACTIVE

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply})
    if len(history) > 20:
        history = history[-20:]
    context.user_data["chat_history"] = history

    await update.message.reply_text(reply, reply_markup=_CHAT_END_KB)
    return CHAT_ACTIVE


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

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(l, callback_data=f"pat_level:{l}") for l in ("A1", "A2", "B1")],
        [InlineKeyboardButton(l, callback_data=f"pat_level:{l}") for l in ("B2", "C1", "C2")],
    ])
    await msg.reply_text("Choose your English level for grammar patterns:", reply_markup=keyboard)
    return PAT_LEVEL


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

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("💾 Save", callback_data=f"pat_save:{index}"),
        InlineKeyboardButton("⏭ Skip", callback_data=f"pat_skip:{index}"),
    ]])
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


async def pat_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("pat_patterns", "pat_saved", "pat_level"):
        context.user_data.pop(key, None)
    await update.message.reply_text("Patterns cancelled.", reply_markup=_back_to_menu_keyboard())
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

    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add", add_start),
            CallbackQueryHandler(add_start, pattern="^menu:add$"),
        ],
        states={
            PHRASE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_phrase)],
            TRANSLATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_translation)],
            EXAMPLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_example),
                CallbackQueryHandler(add_skip_example, pattern="^skip_example$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
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
                MessageHandler(filters.TEXT & ~filters.COMMAND, gen_got_topic_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", gen_cancel)],
    )

    chat_conv = ConversationHandler(
        entry_points=[
            CommandHandler("chat", chat_start),
            CallbackQueryHandler(chat_start, pattern="^menu:chat$"),
        ],
        states={
            CHAT_ACTIVE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, chat_message),
                CallbackQueryHandler(chat_end_cb, pattern="^chat:end$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", chat_cancel)],
    )

    gram_conv = ConversationHandler(
        entry_points=[
            CommandHandler("grammar", gram_start),
            CallbackQueryHandler(gram_start, pattern="^menu:grammar$"),
        ],
        states={
            GRAM_LEVEL: [CallbackQueryHandler(gram_got_level, pattern=r"^gram_level:[ABC][12]$")],
            GRAM_ANSWER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, gram_got_answer),
                CallbackQueryHandler(gram_next, pattern="^gram:next$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", gram_cancel)],
    )

    pat_conv = ConversationHandler(
        entry_points=[
            CommandHandler("patterns", pat_start),
            CallbackQueryHandler(pat_start, pattern="^menu:patterns$"),
        ],
        states={
            PAT_LEVEL: [CallbackQueryHandler(pat_got_level, pattern=r"^pat_level:[ABC][12]$")],
        },
        fallbacks=[CommandHandler("cancel", pat_cancel)],
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

    app.add_handler(CallbackQueryHandler(cb_show_menu,  pattern="^menu:home$"))
    app.add_handler(CallbackQueryHandler(cmd_review,    pattern="^menu:review$"))
    app.add_handler(CallbackQueryHandler(cmd_list,      pattern="^menu:list$"))
    app.add_handler(CallbackQueryHandler(cmd_stats,     pattern="^menu:stats$"))
    app.add_handler(CallbackQueryHandler(cb_show_answer, pattern=r"^show:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_rate,        pattern=r"^rate:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_list_page,   pattern=r"^page:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_gen_save,    pattern=r"^gen_save:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_gen_skip,    pattern=r"^gen_skip:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_pat_save,    pattern=r"^pat_save:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_pat_skip,    pattern=r"^pat_skip:\d+$"))

    logger.info("Bot started, polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
