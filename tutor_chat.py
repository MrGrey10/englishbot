import os
import random

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

_client: AsyncGroq | None = None

_OPEN_TOPICS = [
    "daily routines",
    "travel experiences",
    "food and cooking",
    "movies and TV shows",
    "technology and gadgets",
    "hobbies and free time",
    "work and career goals",
    "learning English",
    "sports and fitness",
    "favourite places",
    "weekend plans",
    "childhood memories",
    "music and concerts",
    "books and reading",
    "dreams and future plans",
]

SYSTEM_PROMPT = """You are a friendly English conversation partner. YOU lead the conversation — you pick topics and always end every reply with a question to keep the student talking.

Reply naturally to what they said. Be warm, engaging, and curious. Always end with a follow-up question to drive the conversation forward.

Keep responses concise: 2–3 sentences of reply + one question. Write in clear, friendly English."""


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set in .env")
        _client = AsyncGroq(api_key=key)
    return _client


async def tutor_open(topic: str | None = None) -> tuple[str, str]:
    if topic is None:
        topic = random.choice(_OPEN_TOPICS)

    prompt = (
        f'You are starting an English conversation practice session. '
        f'The topic is "{topic}". Write a short, warm opener: 1–2 sentences introducing the topic, '
        f'then ask the student one simple, open-ended question about it. '
        f'Keep it natural and encouraging. Write in clear, friendly English.'
    )
    response = await _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    return topic, response.choices[0].message.content.strip()


async def tutor_reply(user_message: str, history: list[dict]) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-18:])
    messages.append({"role": "user", "content": user_message})

    response = await _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=512,
        messages=messages,
    )
    return response.choices[0].message.content.strip()
