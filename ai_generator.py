import asyncio
import io
import json
import os

from groq import AsyncGroq
from gtts import gTTS
from dotenv import load_dotenv

load_dotenv()

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set in .env")
        _client = AsyncGroq(api_key=key, timeout=20.0)
    return _client


LEVEL_DESCRIPTIONS = {
    "A1": "absolute beginner — very simple, basic everyday phrases only",
    "A2": "elementary — simple phrases for common everyday situations",
    "B1": "intermediate — everyday phrases, can handle familiar topics naturally",
    "B2": "upper-intermediate — complex expressions, natural flow",
    "C1": "advanced — sophisticated expressions native speakers use freely",
    "C2": "mastery — highly colloquial, nuanced, natural native-speaker expressions",
}


async def generate_phrases(level: str, topic: str | None = None, count: int = 5) -> list[dict]:
    level_desc = LEVEL_DESCRIPTIONS.get(level, "intermediate")
    topic_ctx = (
        f'on the topic "{topic}"'
        if topic and topic.strip().lower() not in ("any", "будь-яка", "")
        else "for everyday casual conversation"
    )

    prompt = f"""Generate {count} authentic English phrases, idioms, or expressions that native English speakers actually use in real conversations {topic_ctx}.

Language level: {level} — {level_desc}

Rules:
- Real colloquial language: slang, phrasal verbs, idioms, natural everyday expressions
- NOT textbook or overly formal English — things people genuinely say day-to-day
- Adjust complexity strictly to {level}: simpler vocabulary and grammar for A1/A2, progressively more idiomatic for B2/C1/C2
- Include variety: mix idioms, phrasal verbs, filler phrases, and natural expressions

Return a JSON array with exactly {count} objects, each with these keys:
- "phrase": the English expression (concise, as it would actually be said)
- "translation": natural Ukrainian translation
- "example": short realistic sentence (10–20 words) showing it in context
- "context": brief usage note, e.g. "informal, with friends" / "expressing frustration" / "workplace"

Return ONLY the JSON array. No markdown, no code fences, no explanation outside the JSON."""

    response = await _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.choices[0].message.content.strip()

    if text.startswith("```"):
        text = text.lstrip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        text = text.rstrip("`").strip()

    return json.loads(text)


async def generate_patterns(level: str, count: int = 5) -> list[dict]:
    level_desc = LEVEL_DESCRIPTIONS.get(level, "intermediate")

    prompt = f"""Generate {count} English grammar patterns for level {level} ({level_desc}).

A grammar pattern is a sentence structure that native speakers repeat naturally across many situations.
Instead of memorizing rules, learners internalize the pattern by seeing it used in real sentences.

Rules:
- Each pattern should be a common, reusable sentence structure (e.g. "I've already ___", "It's worth ___ing", "I can't help ___ing")
- Choose patterns appropriate for {level}: very simple structures for A1/A2, more complex for B1/B2/C1/C2
- Provide 3 short realistic example sentences per pattern
- Each example must have a natural Ukrainian translation

Return a JSON array with exactly {count} objects, each with these keys:
- "name": short pattern label (e.g. "Present Perfect experience", "used to + verb")
- "structure": the template showing the pattern (e.g. "I've + past participle", "used to + base verb")
- "note": one-sentence tip on when/why this pattern is used
- "examples": array of 3 objects, each with:
    - "en": the English example sentence (short, 5–15 words)
    - "uk": natural Ukrainian translation

Return ONLY the JSON array. No markdown, no code fences, no explanation outside the JSON."""

    response = await _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.choices[0].message.content.strip()

    if text.startswith("```"):
        text = text.lstrip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        text = text.rstrip("`").strip()

    return json.loads(text)


def _tts_sync(text: str) -> bytes:
    buf = io.BytesIO()
    gTTS(text=text, lang="en", slow=False).write_to_fp(buf)
    buf.seek(0)
    return buf.read()


async def text_to_speech(text: str) -> bytes:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _tts_sync, text)


async def transcribe_audio(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    client = _get_client()
    transcription = await client.audio.transcriptions.create(
        file=(filename, audio_bytes),
        model="whisper-large-v3-turbo",
        language="en",
    )
    return transcription.text.strip()


async def generate_reading_text(level: str) -> dict:
    level_desc = LEVEL_DESCRIPTIONS.get(level, "intermediate")

    prompt = f"""Write a short English reading passage for level {level} ({level_desc}).

Rules:
- Length: 80–120 words for A1/A2, 120–180 words for B1/B2, 180–250 words for C1/C2
- Natural, engaging content — a story snippet, opinion piece, or interesting fact
- Vocabulary and grammar strictly appropriate for {level}
- Pick 5 words or phrases from the text that are useful to learn at this level

Return a JSON object with these keys:
- "title": short title for the passage (5 words or fewer)
- "text": the reading passage
- "vocabulary": array of exactly 5 objects, each with:
    - "word": the word or short phrase from the text
    - "meaning": brief Ukrainian translation or explanation
- "translation": full natural Ukrainian translation of the passage

Return ONLY the JSON object. No markdown, no code fences, no explanation outside the JSON."""

    response = await _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.choices[0].message.content.strip()

    if text.startswith("```"):
        text = text.lstrip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        text = text.rstrip("`").strip()

    return json.loads(text)


async def generate_speak_sentences(level: str, count: int = 7) -> list[dict]:
    level_desc = LEVEL_DESCRIPTIONS.get(level, "intermediate")

    prompt = f"""Generate {count} Ukrainian sentences for an English learner at level {level} ({level_desc}) to translate aloud.

Rules:
- Each Ukrainian sentence must have a clear, natural English translation
- Difficulty must match {level}: very short simple sentences for A1/A2, more complex for B1/B2/C1/C2
- Sentences should be practical and conversational (not artificial textbook examples)
- The English translation must sound natural, not word-for-word

Return a JSON array with exactly {count} objects, each with:
- "uk": the Ukrainian sentence to show the user
- "en": the natural English translation (what a native speaker would say)

Return ONLY the JSON array. No markdown, no code fences, no explanation outside the JSON."""

    response = await _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.choices[0].message.content.strip()

    if text.startswith("```"):
        text = text.lstrip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        text = text.rstrip("`").strip()

    return json.loads(text)


async def score_speak_answer(expected: str, user_said: str) -> dict:
    prompt = f"""You are an English language coach. A learner was shown a Ukrainian sentence and asked to say the English translation aloud.

Expected English: "{expected}"
What the learner said: "{user_said}"

Evaluate how well the learner conveyed the meaning. Consider: meaning accuracy (most important), grammar, and natural phrasing.

Score 0–10: 10 = perfect or naturally equivalent; 7–9 = good with minor issues; 4–6 = meaning understood but notable errors; 1–3 = partially correct; 0 = wrong or unrelated.

Return a JSON object with:
- "score": integer 0–10
- "feedback": 1–2 sentences of specific constructive feedback in English
- "corrected": the ideal English sentence

Return ONLY the JSON object. No markdown, no code fences, no explanation outside the JSON."""

    response = await _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.choices[0].message.content.strip()

    if text.startswith("```"):
        text = text.lstrip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        text = text.rstrip("`").strip()

    return json.loads(text)


async def generate_tense_lesson(tense: str) -> dict:
    prompt = f"""You are an expert English teacher. Create a clear, practical lesson on the English tense: "{tense}".

Return a JSON object with these keys:
- "tense": the tense name
- "formation": 1-2 sentences showing how to form this tense (subject + verb structure) with a short example
- "when_to_use": 2-3 sentences explaining when native speakers actually use this tense in real life
- "signal_words": array of 4-5 common signal words or time expressions used with this tense (e.g. "already", "since", "for")
- "phrases": array of exactly 6 objects, each with:
    - "en": a natural everyday English sentence using this tense (avoid textbook clichés)
    - "uk": natural Ukrainian translation
    - "note": one short note about why this tense is used here (max 10 words)

Return ONLY the JSON object. No markdown, no code fences, no explanation outside the JSON."""

    response = await _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.choices[0].message.content.strip()

    if text.startswith("```"):
        text = text.lstrip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        text = text.rstrip("`").strip()

    return json.loads(text)


async def generate_grammar_lesson(level: str) -> dict:
    level_desc = LEVEL_DESCRIPTIONS.get(level, "intermediate")

    prompt = f"""You are an expert English teacher creating a grammar lesson for a Ukrainian learner at level {level} ({level_desc}).

Pick ONE grammar topic that is most useful and appropriate for {level}. Examples of topics (choose freely, pick the most helpful one for this level, vary it each call):
Articles (a/an/the), Prepositions of time, Prepositions of place, Modal verbs, Passive voice, Gerunds vs Infinitives, Relative clauses, Reported speech, Conditionals, Phrasal verbs (common), Comparatives & Superlatives, Question tags, Quantifiers (some/any/much/many), Word order in questions, Verb patterns (verb + ing / verb + to), Subject-verb agreement.

Generate a complete, expanded lesson on your chosen topic for level {level}.

Return a JSON object with these keys:
- "topic": the grammar rule name (e.g. "Passive Voice", "Articles")
- "tagline": one sentence saying what this rule helps you do in English
- "explanation": 3–4 sentences explaining what the rule is and WHY it exists (simple, clear, practical)
- "structure": how to form it — 1-3 lines showing the pattern, e.g. "Subject + is/are + past participle"
- "common_mistake": the single most common error Ukrainian speakers make with this rule (1-2 sentences), with a wrong example and the correct version
- "examples": array of exactly 6 objects, each with:
    - "en": a natural, everyday English sentence using this rule (avoid clichés)
    - "uk": natural Ukrainian translation
    - "note": one short note (max 10 words) on WHY this rule applies here
- "quick_check": array of exactly 3 fill-in-the-blank objects, each with:
    - "sentence": sentence with ___ for the missing word/phrase
    - "answer": the correct answer (lowercase, as a learner would type it)
    - "explanation": one sentence saying why that answer is correct

Return ONLY the JSON object. No markdown, no code fences, no explanation outside the JSON."""

    response = await _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=3500,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.choices[0].message.content.strip()

    if text.startswith("```"):
        text = text.lstrip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        text = text.rstrip("`").strip()

    return json.loads(text)


async def generate_grammar_exercises(level: str, count: int = 5) -> list[dict]:
    level_desc = LEVEL_DESCRIPTIONS.get(level, "intermediate")

    prompt = f"""Create {count} English fill-in-the-blank grammar exercises for level {level} ({level_desc}).

Rules:
- Replace exactly ONE word in each sentence with ___ (three underscores)
- The missing word must test a grammar point appropriate for {level}: verb forms, tenses, articles, prepositions, modal verbs, etc.
- Sentences must be realistic, natural everyday English — not textbook-boring
- Adjust difficulty strictly to {level}: very simple for A1/A2, more complex grammar for B1/B2/C1/C2

Return a JSON array with exactly {count} objects, each with these keys:
- "sentence": the sentence with ___ replacing the missing word
- "answer": the single correct word that fills the blank (lowercase)
- "full_sentence": the complete sentence with the answer filled in
- "hint": short grammar tip explaining why this answer is correct (1 sentence)

Return ONLY the JSON array. No markdown, no code fences, no explanation outside the JSON."""

    response = await _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.choices[0].message.content.strip()

    if text.startswith("```"):
        text = text.lstrip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        text = text.rstrip("`").strip()

    return json.loads(text)
