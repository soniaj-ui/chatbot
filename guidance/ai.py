"""Every conversational reply is written by the language model.

The model receives the approved catalogue, the call stage, the profile collected so far and the
conversation, and returns its spoken reply together with structured updates. The server only
validates that output: course facts must come from the catalogue, the course must exist and the
language must be supported. If the model is unreachable the caller gets a short retry message.
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as ModelTimeout
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)
CATALOGUE = json.loads((Path(settings.BASE_DIR) / "catalogue.json").read_text(encoding="utf-8"))
CATALOGUE_VERSION = "demo-v1"
LANGUAGES = {"en-IN": "English", "ta-IN": "Tamil", "te-IN": "Telugu", "hi-IN": "Hindi"}
PROFILE_FIELDS = ("qualification", "experience", "interests", "goal")
# Total time a turn may wait for the model, including one retry.
DEADLINE = 15
# With a backup configured, a slow main model is abandoned after this long so the backup has time to answer.
MAIN_WAIT = 9
pool = ThreadPoolExecutor(max_workers=4)

INSTRUCTIONS = """You are an AI voice telecaller for a technical training institute. You are on a live
phone call with a student who enquired about automation courses. Everything you write is spoken
aloud by a text-to-speech voice.

Speaking style
- Reply in one to three short spoken sentences (under 60 words). No lists, markdown or emoji.
- Ask one question at a time and briefly acknowledge what the student just said.
- Sound warm and natural, like a helpful counsellor, never pushy.
- Greet only in your first reply in a language; do not start later replies with "Hello" or "வணக்கம்".
- Repeat numbers, years and names exactly as the student said them (1.5 years stays 1.5 years).
- Refer to the institute only as "our training institute"; never make up its name.

Language
- Supported languages: English (en-IN), Tamil (ta-IN), Telugu (te-IN), Hindi (hi-IN).
- Reply in the language the student is using. If they ask for another supported language or
  speak in it (including Romanized words such as "vanakkam", "Tamil la pesunga", "namaste",
  "Hindi mein bolo"), switch to it and set "language" to its code.
- Write Tamil, Telugu and Hindi in their own script. Technical terms such as PLC, SCADA or HMI may
  stay in English.

Call flow (the current stage is given to you)
1. consent: introduce yourself as an AI assistant from the institute, say you can help them choose
   a course and save notes for a counsellor, and ask permission to continue. Do not ask profile
   questions before permission. Set "consent" to "given" when they agree, "declined" when they
   clearly refuse. If unclear, ask again politely.
2. discovery: learn their qualification, prior experience, the skills they want to learn and
   their career goal, one at a time. If they are unsure, offer two or three simple options.
   The context lists "missing_profile_fields"; ask about those before recommending, unless the
   student asks for a recommendation or course details directly.
3. When you know enough, recommend the single best course from the catalogue and set
   "recommended_course_id". Only recommend "experienced" courses to students with relevant
   experience. Then answer their questions.

Facts (most important rule)
- The institute offers only the courses listed under "Courses". Never mention any other course or
  subject area.
- State course titles, fees, durations and modules only from that list, and say the fee whenever
  you recommend a course or are asked about cost.
- You know nothing else about the institute. If the student asks about anything not in the list
  (weekend or online batches, timings, placements, jobs, salaries, discounts, certificates, start
  dates, eligibility), never say yes or no: say you cannot confirm it on this call, offer a
  counsellor callback, and copy the student's question into "unanswered_question". Otherwise
  "unanswered_question" is null.
- Never ask for phone numbers, addresses or payment details.

Callback and ending
- If the student agrees to a counsellor callback, set "callback_requested" to true and put any
  preferred day or time in "callback_preference".
- If the student wants to stop, says goodbye, or has no more questions after the recommendation,
  thank them, close politely and set "end_call" to true."""

FORMAT = """Return only a JSON object with exactly these keys:
{"reply": string, "language": "en-IN"|"ta-IN"|"te-IN"|"hi-IN", "consent": "given"|"declined"|null,
 "profile": {"qualification": string|null, "experience": string|null, "interests": string|null,
             "goal": string|null},
 "recommended_course_id": string|null, "unanswered_question": string|null,
 "callback_requested": boolean, "callback_preference": string|null, "end_call": boolean}
In "profile" include only details the student has stated, in short English notes.
The spoken text must be in "reply"."""


def models():
    return [llm for llm in settings.GUIDANCE_LLMS if all((llm["url"], llm["model"], llm["key"]))]


def course_facts():
    return [{key: course[key] for key in ("id", "title", "level", "modules", "duration_weeks", "fee_inr")}
            for course in CATALOGUE]


def course_list():
    audience = {"beginner": "for beginners", "experienced": "only for students with prior automation experience; "
                "suggest a beginner course first to anyone without it"}
    return "\n".join(f"- {c['id']}: {c['title']} ({audience.get(c['level'], c['level'])}). Modules: {c['modules']}. "
                     f"Duration: {c['duration_weeks']} weeks. Fee: Rs {c['fee_inr']:,}." for c in CATALOGUE)


def next_step(session):
    """What the call needs next; the model decides how to say it."""
    profile = session.data.get("profile", {})
    missing = [field for field in PROFILE_FIELDS if field not in profile]
    if session.state == "consent":
        return "Get the student's permission to continue."
    if session.data.get("course_id"):
        return ("Answer the student's question using only the course list, or offer a counsellor "
                "callback. Close politely if they have nothing more to ask.")
    if missing:
        return (f"Ask about the student's {missing[0].replace('_', ' ')}, unless they asked a question; "
                "then answer it first.")
    return "Recommend the single best course now, stating its title, duration and fee."


def build_messages(session, event, correction=None):
    data = session.data
    context = {
        "next_step": next_step(session),
        "stage": session.state,
        "language": session.language,
        "enquiry_interest": session.enquiry.interest,
        "profile_so_far": data.get("profile", {}),
        "missing_profile_fields": [field for field in PROFILE_FIELDS if field not in data.get("profile", {})],
        "recommended_course_id": data.get("course_id"),
        "catalogue": course_facts(),
    }
    # One system message: Gemini's OpenAI-compatible API does not reliably use several.
    system = "\n\n".join([INSTRUCTIONS, "Courses\n" + course_list(),
                          "Call context: " + json.dumps(context, ensure_ascii=False), FORMAT])
    messages = [{"role": "system", "content": system}]
    # Recent turns only, so the request stays small and fast; fixed fallback text is left out.
    for message in [m for m in data.get("messages", []) if m.get("source") != "fallback"][-16:]:
        messages.append({"role": "assistant" if message["role"] == "assistant" else "user",
                         "content": message["text"]})
    # The next step is repeated beside the student's words, where small models follow it best.
    note = f"\n\n[Next step: {context['next_step']}" + (f" {correction}" if correction else "") + "]"
    messages.append({"role": "user", "content": event + note})
    return messages


def call_model(messages, llm):
    payload = {"model": llm["model"], "response_format": {"type": "json_object"},
               "temperature": 0.4, "messages": messages}
    request = Request(llm["url"], json.dumps(payload).encode("utf-8"),
                      # Groq's firewall rejects Python's default user agent.
                      {"Authorization": f"Bearer {llm['key']}", "Content-Type": "application/json",
                       "User-Agent": "ai-telecaller/1.0"})
    with urlopen(request, timeout=DEADLINE) as response:
        content = json.load(response)["choices"][0]["message"]["content"]
    # Models sometimes wrap the object in code fences or add a word before it.
    start, end = content.find("{"), content.rfind("}")
    result = json.loads(content[start:end + 1] if start != -1 and end > start else content)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result


def ungrounded_amounts(reply):
    """Rupee amounts in the reply that are not catalogue fees."""
    fees = {course["fee_inr"] for course in CATALOGUE}
    amounts = {int(value.replace(",", "")) for value in re.findall(r"\d{1,3}(?:,\d{2,3})+|\d{4,}", reply)}
    return amounts - fees


# Unicode blocks of the Indian scripts the call can use.
SCRIPTS = {"hi-IN": "ऀ-ॿ", "ta-IN": "஀-௿", "te-IN": "ఀ-౿"}
INDIC = re.compile(r"[ऀ-෿]")


def wrong_script(reply, language):
    """True if the reply has letters of another Indian script, such as a Bengali word in Tamil."""
    own = re.compile(f"[{SCRIPTS[language]}]") if language in SCRIPTS else None
    return any(not (own and own.match(char)) for char in INDIC.findall(reply))


def clean(result, session):
    """Keep only valid fields from the model's output."""
    # Some models name the spoken text differently despite the instructions.
    reply = next((result[key] for key in ("reply", "response", "message", "text", "answer")
                  if isinstance(result.get(key), str) and result[key].strip()), None)
    if not reply:
        raise ValueError("Empty reply")
    profile = result.get("profile") if isinstance(result.get("profile"), dict) else {}
    course_ids = {course["id"] for course in CATALOGUE}
    text = lambda value: value.strip()[:300] if isinstance(value, str) and value.strip() else None
    return {
        "reply": reply.strip()[:600],
        "language": result.get("language") if result.get("language") in LANGUAGES else session.language,
        "consent": result.get("consent") if result.get("consent") in {"given", "declined"} else None,
        "profile": {field: text(profile.get(field)) for field in PROFILE_FIELDS if text(profile.get(field))},
        "course_id": result.get("recommended_course_id") if result.get("recommended_course_id") in course_ids else None,
        "unanswered_question": text(result.get("unanswered_question")),
        "callback_requested": result.get("callback_requested") is True,
        "callback_preference": text(result.get("callback_preference")),
        "end_call": result.get("end_call") is True,
    }


def respond(session, event):
    """Ask the model for the next turn. Returns cleaned output, or None if every model failed.

    If the main model fails, is rate-limited or is too slow, the backup model answers the same turn.
    """
    llms = models()
    if not llms:
        logger.warning("No model configured. Add GEMINI_API_KEY to .env.")
        return None
    started = time.monotonic()
    correction = None
    current = 0
    for attempt in range(2):
        remaining = DEADLINE - (time.monotonic() - started)
        if remaining < 2:
            break
        llm = llms[current]
        has_backup = current + 1 < len(llms)
        wait = min(remaining, MAIN_WAIT) if has_backup else remaining
        try:
            result = clean(pool.submit(call_model, build_messages(session, event, correction), llm).result(timeout=wait),
                           session)
        except ModelTimeout:
            logger.warning("%s took longer than %s s.", llm["name"], round(wait))
            if not has_backup:
                return None
            current += 1
            continue
        except HTTPError as exc:
            logger.warning("%s request failed (HTTP %s), attempt %s.", llm["name"], exc.code, attempt + 1)
            if has_backup:
                current += 1
            # A rate limit is not fixed by retrying at once; it only uses up more of the quota.
            elif exc.code == 429:
                return None
            continue
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            logger.warning("%s response unusable (%s), attempt %s.", llm["name"], type(exc).__name__, attempt + 1)
            if has_backup:
                current += 1
            continue
        if current:
            logger.warning("Backup model %s answered.", llm["name"])
        # A fee that is not in the catalogue is a hallucination: ask the model to correct itself once.
        if ungrounded_amounts(result["reply"]) and attempt == 0:
            correction = ("Your previous reply mentioned an amount that is not in the catalogue. Use only "
                          "catalogue fees, or say you cannot confirm it.")
            continue
        if ungrounded_amounts(result["reply"]):
            return None
        # Small models sometimes slip a word in another script; a stray word is better than no reply.
        if wrong_script(result["reply"], result["language"]) and attempt == 0:
            correction = (f"Your previous reply mixed in letters from another script. Write it again using only "
                          f"{LANGUAGES[result['language']]} script, with technical terms in English.")
            continue
        return result
    return None
