import json
import os

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set in .env")
        _client = AsyncGroq(api_key=key)
    return _client


LEVEL_DESCRIPTIONS = {
    "A1": "absolute beginner — very simple, basic everyday phrases only",
    "A2": "elementary — simple phrases for common everyday situations",
    "B1": "intermediate — everyday phrases, can handle familiar topics naturally",
    "B2": "upper-intermediate — complex expressions, common idioms, natural flow",
    "C1": "advanced — idiomatic, sophisticated expressions native speakers use freely",
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
