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
