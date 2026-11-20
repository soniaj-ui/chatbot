import asyncio
import json
import logging
from datetime import datetime, timezone

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import ai
from .models import CallSession, Enquiry, Suppression

logger = logging.getLogger(__name__)
VOICES = {"en-IN": "en-IN-NeerjaNeural", "ta-IN": "ta-IN-PallaviNeural",
          "te-IN": "te-IN-ShrutiNeural", "hi-IN": "hi-IN-SwaraNeural"}

# Fixed text is used only for button actions and when the model cannot be reached; every
# conversational reply comes from the model.
FIXED = {
    "en-IN": {"retry": "Sorry, I could not respond just now. Could you please say that again?",
              "greeting": "Hello, I'm an AI course guidance assistant. May I take a few minutes to help you choose a course?",
              "closed": "Thank you. I'm ending this call.",
              "suppressed": "Understood. We will not contact you again.",
              "queued": "I have saved your callback request for a counsellor."},
    "ta-IN": {"retry": "மன்னிக்கவும், இப்போது பதில் சொல்ல முடியவில்லை. தயவுசெய்து மீண்டும் சொல்லுங்கள்.",
              "greeting": "வணக்கம், நான் பயிற்சி வழிகாட்டும் AI உதவியாளர். உங்களுக்கு ஏற்ற பயிற்சியைத் தேர்ந்தெடுக்க உதவலாமா?",
              "closed": "நன்றி. இந்த அழைப்பை முடிக்கிறேன்.",
              "suppressed": "புரிந்தது. இனி உங்களைத் தொடர்பு கொள்ள மாட்டோம்.",
              "queued": "ஆலோசகர் அழைப்புக்கான உங்கள் கோரிக்கையைச் சேமித்துவிட்டேன்."},
    "te-IN": {"retry": "క్షమించండి, ఇప్పుడు సమాధానం ఇవ్వలేకపోయాను. దయచేసి మళ్ళీ చెప్పండి.",
              "greeting": "నమస్కారం, నేను కోర్సు మార్గదర్శక AI సహాయకుడిని. మీకు సరైన కోర్సు ఎంచుకోవడంలో సహాయం చేయవచ్చా?",
              "closed": "ధన్యవాదాలు. ఈ కాల్‌ను ముగిస్తున్నాను.",
              "suppressed": "అర్థమైంది. మేము మిమ్మల్ని మళ్ళీ సంప్రదించము.",
              "queued": "సలహాదారు కాల్ కోసం మీ అభ్యర్థనను భద్రపరిచాను."},
    "hi-IN": {"retry": "माफ़ कीजिए, अभी जवाब नहीं दे पाया। कृपया फिर से कहें।",
              "greeting": "नमस्ते, मैं पाठ्यक्रम मार्गदर्शन AI सहायक हूँ। क्या मैं सही पाठ्यक्रम चुनने में आपकी मदद करूँ?",
              "closed": "धन्यवाद। मैं यह कॉल समाप्त कर रहा हूँ।",
              "suppressed": "समझ गया। हम आपसे दोबारा संपर्क नहीं करेंगे।",
              "queued": "मैंने काउंसलर कॉल के लिए आपका अनुरोध सहेज लिया है।"},
}
START_EVENT = ("[The call has just connected. Greet the student, disclose that you are an AI assistant and "
               "ask for permission to continue.{offer}]")
CONSENT_EVENT = "[The student pressed Continue to give permission. Thank them and ask the first discovery question.]"


def now():
    return datetime.now(timezone.utc).isoformat()


def body(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}


def error(status, detail):
    return JsonResponse({"detail": detail}, status=status)


def say(data, text, source):
    data["messages"].append({"role": "assistant", "text": text, "source": source})


def ai_reply(session, event):
    """Add the model's reply and apply its structured updates. Returns the new state."""
    data, state = session.data, session.state
    result = ai.respond(session, event)
    data["model_status"] = "responded" if result else "unavailable"
    if result is None:
        say(data, FIXED[session.language]["retry" if data["messages"] else "greeting"], "fallback")
        return state
    session.language = result["language"]
    say(data, result["reply"], "model")
    data["profile"].update(result["profile"])
    if state == "consent" and result["consent"] == "given":
        data["consented_at"], state = now(), "discovery"
    elif state == "consent" and result["consent"] == "declined":
        data["outcome"] = "declined"
        return "closed"
    if state == "consent":
        return state
    if result["course_id"]:
        data["course_id"], data["catalogue_version"] = result["course_id"], ai.CATALOGUE_VERSION
        data["interest_level"] = "medium"
        state = "followup"
    question = result["unanswered_question"]
    if question and question not in data["unresolved"]:
        data["unresolved"].append(question)
    if result["callback_requested"]:
        data["callback"] = {"status": "pending_review", "requested_at": now(),
                            "preference": result["callback_preference"]}
        data["outcome"], data["interest_level"] = "callback_requested", "high"
    if result["end_call"]:
        data["outcome"] = data["outcome"] or "completed"
        state = "closed"
    return state


@require_GET
def dashboard(request):
    return render(request, "guidance/dashboard.html")


@require_GET
def catalogue(request):
    return JsonResponse({"sample": True, "version": ai.CATALOGUE_VERSION, "courses": ai.CATALOGUE})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def enquiries(request):
    if request.method == "POST":
        fields = body(request)
        name = str(fields.get("name", "")).strip()[:100]
        contact = str(fields.get("contact", "")).strip().lstrip("+")[:30]
        if not name or not contact:
            return error(422, "Enter a student name and phone number")
        lead = Enquiry.objects.create(name=name, contact=contact, interest=str(fields.get("interest", "")).strip()[:150],
                                      opted_in=fields.get("opted_in") is True)
        return JsonResponse({"id": lead.id}, status=201)
    suppressed = set(Suppression.objects.values_list("contact", flat=True))
    return JsonResponse([{"id": lead.id, "name": lead.name, "interest": lead.interest,
                          "contact": "••••" + lead.contact[-4:], "opted_in": lead.opted_in,
                          "suppressed": lead.contact in suppressed}
                         for lead in Enquiry.objects.order_by("-id")], safe=False)


@require_GET
def sessions(request):
    return JsonResponse([session.as_dict() for session in CallSession.objects.select_related("enquiry")], safe=False)


@csrf_exempt
@require_POST
def start(request, enquiry_id):
    lead = get_object_or_404(Enquiry, pk=enquiry_id)
    if not lead.opted_in or Suppression.objects.filter(contact=lead.contact).exists():
        return error(409, "Call blocked by contact permission or opt-out")
    choice = body(request).get("language", "auto")
    language = choice if choice in ai.LANGUAGES else "en-IN"
    session = CallSession(enquiry=lead, language=language, state="consent", data={
        "mode": "simulation", "profile": {}, "messages": [], "course_id": None, "catalogue_version": None,
        "unresolved": [], "consented_at": None, "callback": None, "outcome": None, "interest_level": "unknown"})
    offer = " Mention that they can also talk in Tamil, Telugu or Hindi." if choice == "auto" else ""
    session.state = ai_reply(session, START_EVENT.format(offer=offer))
    session.save()
    return JsonResponse(session.as_dict(), status=201)


@csrf_exempt
@require_POST
def turn(request, session_id):
    fields = body(request)
    session = get_object_or_404(CallSession.objects.select_related("enquiry"), pk=session_id)
    if fields.get("revision") != session.revision or session.state == "closed":
        return error(409, "Session changed or closed. Reload the session.")
    action, text = fields.get("action"), str(fields.get("text", "")).strip()[:1000]
    data, lead, fixed = session.data, session.enquiry, FIXED[session.language]

    if action == "opt_out":
        Suppression.objects.get_or_create(contact=lead.contact)
        data["callback"], data["outcome"], state = None, "opt_out", "closed"
        say(data, fixed["suppressed"], "fixed")
    elif action in {"stop", "decline"} or Suppression.objects.filter(contact=lead.contact).exists():
        data["outcome"], state = ("ended" if data["consented_at"] else "declined"), "closed"
        say(data, fixed["closed"], "fixed")
    elif action == "callback" and session.state != "consent":
        data["callback"] = {"status": "pending_review", "requested_at": now(), "preference": text or None}
        data["outcome"], data["interest_level"], state = "callback_requested", "high", "closed"
        say(data, fixed["queued"], "fixed")
    elif action == "consent" and session.state == "consent":
        data["consented_at"], session.state = now(), "discovery"
        state = ai_reply(session, CONSENT_EVENT)
    elif action == "message" and text:
        data["messages"].append({"role": "student", "text": text})
        state = ai_reply(session, text)
    else:
        return error(422, "This action is unavailable in the current session state")

    # Save only if no other turn was saved meanwhile.
    changed = CallSession.objects.filter(pk=session.pk, revision=session.revision).update(
        data=data, state=state, language=session.language, revision=session.revision + 1)
    if changed != 1:
        return error(409, "Another turn was saved first")
    session.refresh_from_db()
    return JsonResponse(session.as_dict())


@require_GET
def speech(request):
    """Neural voice for languages the browser cannot speak, such as Tamil in Chrome on Windows."""
    text, language = request.GET.get("text", "").strip()[:1200], request.GET.get("language", "en-IN")
    if not text or language not in VOICES:
        return error(422, "Give text and a supported language")
    try:
        import edge_tts
    except ImportError:
        return error(503, "Install edge-tts for server voices")

    async def synthesise():
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text, VOICES[language]).stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        return bytes(audio)

    try:
        audio = asyncio.run(synthesise())
    except Exception as exc:
        logger.warning("Speech service unavailable (%s). Using browser voice.", type(exc).__name__)
        return error(503, "Speech service unavailable")
    return HttpResponse(audio, content_type="audio/mpeg")


@csrf_exempt
@require_POST
def client_log(request):
    """Browser speech events, so a missed voice turn can be diagnosed from client.log."""
    fields = body(request)
    with open(settings.BASE_DIR / "client.log", "a", encoding="utf-8") as log:
        log.write(f"{now()} {str(fields.get('event', ''))[:40]} {str(fields.get('detail', ''))[:500]}\n")
    return HttpResponse(status=204)
