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

SYSTEM_PROMPT = """You are a friendly English teacher and conversation partner. YOU lead the conversation — you pick topics and always end every reply with a question to keep the student talking.

For every user message:

1. GRAMMAR CHECK — scan the message for mistakes (spelling, grammar, word choice, punctuation).
   - If mistakes exist, begin your reply with:
     ✏️ Correction: "[exact quote of wrong part]" → "[corrected version]" — [one-line explanation]
   - If there are multiple mistakes, list each on its own ✏️ line.
   - If the message is correct, skip this block entirely — do NOT say "no mistakes" or anything about grammar.

2. RESPONSE — reply naturally to what they said. Be warm, engaging, and curious. Always end with a follow-up question to drive the conversation forward.

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


_ROLEPLAY_PROMPTS = {
    "Work Interview": (
        "You are an interviewer at a professional company. The student is the job candidate. "
        "Conduct a realistic English job interview. Ask interview questions one at a time, "
        "respond naturally to their answers, give brief encouraging feedback, and then ask the next question. "
        "If they make grammar or vocabulary mistakes, gently correct them with: ✏️ Correction: \"wrong\" → \"correct\" — explanation. "
        "Keep the scenario realistic and professional."
    ),
    "Scrum Meeting": (
        "You are a Scrum Master running a daily stand-up. The student is a developer on the team. "
        "Lead the stand-up: ask what they did yesterday, what they plan today, and if there are blockers. "
        "React naturally as a Scrum Master would. If they make English mistakes, correct them with: "
        "✏️ Correction: \"wrong\" → \"correct\" — explanation. Keep it realistic and concise."
    ),
    "In restaurant": (
        "You are a waiter/waitress at an English-speaking restaurant. The student is a customer. "
        "Play the role naturally: greet them, take their order, answer questions about the menu, bring the bill. "
        "If they make English mistakes, correct them with: ✏️ Correction: \"wrong\" → \"correct\" — explanation. "
        "Keep the scenario realistic and friendly."
    ),
    "In hotel reception": (
        "You are a hotel receptionist at an English-speaking hotel. The student is a guest checking in. "
        "Handle the check-in: ask for their name and reservation, explain room details, answer questions. "
        "If they make English mistakes, correct them with: ✏️ Correction: \"wrong\" → \"correct\" — explanation. "
        "Be professional and helpful."
    ),
    "In airport": (
        "You are an airport staff member (check-in agent or passport control officer). The student is a traveller. "
        "Run the airport scenario: check-in, baggage questions, gate info, or passport control. "
        "If they make English mistakes, correct them with: ✏️ Correction: \"wrong\" → \"correct\" — explanation. "
        "Keep the scenario realistic."
    ),
    "With taxi driver": (
        "You are an English-speaking taxi driver. The student is your passenger. "
        "Have a natural taxi ride conversation: ask where they're going, make small talk, discuss the route or traffic. "
        "If they make English mistakes, correct them with: ✏️ Correction: \"wrong\" → \"correct\" — explanation. "
        "Be friendly and chatty."
    ),
    "Small talk": (
        "You are a friendly English-speaking person making small talk with the student. "
        "Topics: weather, weekend plans, local events, hobbies, etc. Keep it light and natural. "
        "Always end with a follow-up question to keep the conversation going. "
        "If they make English mistakes, correct them with: ✏️ Correction: \"wrong\" → \"correct\" — explanation."
    ),
    "In shop": (
        "You are a shop assistant in an English-speaking store. The student is a customer. "
        "Help them find what they need, answer questions about products, sizes, prices, and handle the purchase. "
        "If they make English mistakes, correct them with: ✏️ Correction: \"wrong\" → \"correct\" — explanation. "
        "Be helpful and professional."
    ),
}

_ROLEPLAY_OPENERS = {
    "Work Interview": "Hello! Thanks for coming in today. Please have a seat. So, let's start — could you tell me a little bit about yourself and why you're interested in this position?",
    "Scrum Meeting": "Good morning everyone! Let's start our daily stand-up. {name}, let's begin with you — what did you work on yesterday?",
    "In restaurant": "Good evening! Welcome to our restaurant. My name is Alex and I'll be your server tonight. Can I start you off with something to drink?",
    "In hotel reception": "Good afternoon! Welcome to the Grand Hotel. Do you have a reservation with us?",
    "In airport": "Good morning! Next, please. Can I see your passport and boarding pass?",
    "With taxi driver": "Hello! Hop in! Where are you headed today?",
    "Small talk": "Oh hi! Lovely weather we're having today, isn't it? Are you from around here?",
    "In shop": "Hi there! Welcome in. Are you looking for something specific today, or just browsing?",
}


async def roleplay_open(scenario: str) -> str:
    opener = _ROLEPLAY_OPENERS.get(scenario)
    if opener:
        return opener.replace("{name}", "you")
    prompt = (
        f'You are starting an English role-play scenario: "{scenario}". '
        f'Write a short, natural opening line (1–2 sentences) to begin the scene. '
        f'Stay in character and prompt the student to respond.'
    )
    response = await _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


async def roleplay_reply(user_message: str, history: list[dict], scenario: str) -> str:
    system = _ROLEPLAY_PROMPTS.get(
        scenario,
        f'You are playing a role in an English scenario: "{scenario}". Stay in character and correct mistakes with ✏️ Correction: "wrong" → "correct" — explanation.',
    )
    messages = [{"role": "system", "content": system}]
    messages.extend(history[-18:])
    messages.append({"role": "user", "content": user_message})

    response = await _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=512,
        messages=messages,
    )
    return response.choices[0].message.content.strip()
