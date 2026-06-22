import os

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

_client: AsyncGroq | None = None

SYSTEM_PROMPT = """You are a friendly English teacher and conversation partner. For every user message:

1. GRAMMAR CHECK — scan the message for mistakes (spelling, grammar, word choice, punctuation).
   - If mistakes exist, begin your reply with:
     ✏️ Correction: "[exact quote of wrong part]" → "[corrected version]" — [one-line explanation]
   - If there are multiple mistakes, list each on its own ✏️ line.
   - If the message is correct, skip this block entirely — do NOT say "no mistakes" or anything about grammar.

2. RESPONSE — reply naturally to what they said. Be warm, engaging, and curious. Ask a follow-up question to keep the conversation going.

Keep responses concise: corrections (if any) + 2–3 sentences of reply + one question.
Write in clear, friendly English. Never make the user feel bad about mistakes."""


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set in .env")
        _client = AsyncGroq(api_key=key)
    return _client


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
