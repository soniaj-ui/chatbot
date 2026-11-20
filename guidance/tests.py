import time
from unittest import mock
from urllib.error import HTTPError

from django.test import TestCase, override_settings

from .models import Suppression

LLM = {"name": "Main", "url": "https://example.test/v1/chat/completions", "model": "test-model", "key": "test-key"}
BACKUP = {**LLM, "name": "Backup", "model": "backup-model"}


def reply(text, **fields):
    return {"reply": text, "language": fields.pop("language", "en-IN"), "consent": None, "profile": {},
            "recommended_course_id": None, "unanswered_question": None, "callback_requested": False,
            "callback_preference": None, "end_call": False, **fields}


@override_settings(GUIDANCE_LLMS=[LLM])
class CallFlowTests(TestCase):
    def setUp(self):
        response = self.client.post("/api/enquiries", {"name": "Kavya", "contact": "9000000042", "interest": "PLC",
                                                       "opted_in": True}, content_type="application/json")
        self.lead = response.json()["id"]

    def start(self, *replies):
        with mock.patch("guidance.ai.call_model", side_effect=list(replies)):
            return self.client.post(f"/api/enquiries/{self.lead}/sessions", {"language": "auto"},
                                    content_type="application/json").json()

    def say(self, session, text, *replies, action="message"):
        with mock.patch("guidance.ai.call_model", side_effect=list(replies)) as model:
            response = self.client.post(f"/api/sessions/{session['id']}/turns",
                                        {"action": action, "text": text, "revision": session["revision"]},
                                        content_type="application/json")
        self.last_prompt = model.call_args.args[0] if model.call_args else None
        self.last_model = model.call_args.args[1] if model.call_args else None
        return response

    def test_full_call_is_ai_generated_and_saves_recommendation(self):
        session = self.start(reply("Hello, I'm an AI assistant. May I continue?"))
        self.assertEqual(session["messages"][0]["source"], "model")
        session = self.say(session, "vanakkam", reply("வணக்கம்! தொடரலாமா?", language="ta-IN", consent="given")).json()
        self.assertEqual((session["language"], session["state"]), ("ta-IN", "discovery"))
        session = self.say(session, "நான் MCA படித்தேன்", reply("MCA, நல்லது. PLC அனுபவம் உள்ளதா?", language="ta-IN",
                                                               profile={"qualification": "MCA"})).json()
        self.assertEqual(session["profile"], {"qualification": "MCA"})
        session = self.say(session, "இல்லை, PLC கற்க வேண்டும்", reply(
            "PLC Foundations உங்களுக்குப் பொருந்தும். கட்டணம் ₹12,000.", language="ta-IN",
            recommended_course_id="DEMO-PLC-01")).json()
        self.assertEqual((session["state"], session["course_id"]), ("followup", "DEMO-PLC-01"))
        self.assertTrue(all(m["source"] == "model" for m in session["messages"] if m["role"] == "assistant"))

    def test_prompt_contains_catalogue_and_conversation(self):
        session = self.start(reply("Hello, may I continue?"))
        self.say(session, "yes", reply("Great. What did you study?", consent="given"))
        system = self.last_prompt[0]["content"]
        self.assertIn("PLC Foundations", system)
        self.assertIn("Fee: Rs 12,000", system)
        self.assertIn('"reply"', system)
        self.assertTrue(self.last_prompt[-1]["content"].startswith("yes\n\n[Next step:"))

    def test_invented_fee_is_corrected_by_the_model(self):
        session = self.say(self.start(reply("Hello, may I continue?")), "yes", reply("Hi", consent="given")).json()
        response = self.say(session, "fee?", reply("The fee is ₹15,000."), reply("The fee is ₹12,000."))
        self.assertEqual(response.json()["messages"][-1]["text"], "The fee is ₹12,000.")
        self.assertIn("not in the catalogue", self.last_prompt[-1]["content"])

    def test_unknown_course_id_is_ignored(self):
        session = self.say(self.start(reply("Hello, may I continue?")), "yes", reply("Hi", consent="given")).json()
        session = self.say(session, "plc", reply("Try this course.", recommended_course_id="MADE-UP")).json()
        self.assertIsNone(session["course_id"])

    def test_unanswered_question_and_callback_are_recorded(self):
        session = self.say(self.start(reply("Hello, may I continue?")), "yes", reply("Hi", consent="given")).json()
        session = self.say(session, "weekend batch?", reply("I can't confirm that. Shall a counsellor call you?",
                                                            unanswered_question="weekend batch?")).json()
        self.assertEqual(session["unresolved"], ["weekend batch?"])
        session = self.say(session, "yes tomorrow 11", reply("Saved. Thank you!", callback_requested=True,
                                                             callback_preference="tomorrow 11", end_call=True)).json()
        self.assertEqual((session["state"], session["outcome"]), ("closed", "callback_requested"))
        self.assertEqual(session["callback"]["preference"], "tomorrow 11")

    def test_model_failure_gives_a_retry_message(self):
        session = self.start(reply("Hello, may I continue?"))
        session = self.say(session, "yes", OSError("offline"), OSError("offline")).json()
        self.assertEqual((session["messages"][-1]["source"], session["model_status"]), ("fallback", "unavailable"))
        self.assertEqual(session["state"], "consent")

    def test_decline_closes_and_opt_out_blocks_future_calls(self):
        session = self.say(self.start(reply("Hello, may I continue?")), "no", reply("Okay, goodbye.",
                                                                                   consent="declined")).json()
        self.assertEqual((session["state"], session["outcome"]), ("closed", "declined"))
        session = self.start(reply("Hello, may I continue?"))
        self.say(session, "", action="opt_out")
        self.assertTrue(Suppression.objects.filter(contact="9000000042").exists())
        blocked = self.client.post(f"/api/enquiries/{self.lead}/sessions", {}, content_type="application/json")
        self.assertEqual(blocked.status_code, 409)

    def test_stale_revision_is_rejected(self):
        session = self.start(reply("Hello, may I continue?"))
        self.say(session, "yes", reply("Hi", consent="given"))
        self.assertEqual(self.say(session, "again", reply("Hi")).status_code, 409)

    @override_settings(GUIDANCE_LLMS=[LLM, BACKUP])
    def test_backup_model_answers_when_main_is_rate_limited(self):
        session = self.start(reply("Hello, may I continue?"))
        limited = HTTPError(LLM["url"], 429, "Too Many Requests", {}, None)
        session = self.say(session, "yes", limited, reply("Thanks. What did you study?", consent="given")).json()
        self.assertEqual((session["messages"][-1]["source"], session["state"]), ("model", "discovery"))
        self.assertEqual(self.last_model, BACKUP)

    @override_settings(GUIDANCE_LLMS=[LLM, BACKUP])
    def test_backup_model_answers_when_main_is_slow(self):
        def slow_main(messages, llm):
            if llm is LLM:
                time.sleep(0.5)
            return reply("Thanks. What did you study?", consent="given")
        session = self.start(reply("Hello, may I continue?"))
        with mock.patch("guidance.ai.MAIN_WAIT", 0.1), mock.patch("guidance.ai.call_model", side_effect=slow_main) as model:
            session = self.client.post(f"/api/sessions/{session['id']}/turns",
                                       {"action": "message", "text": "yes", "revision": session["revision"]},
                                       content_type="application/json").json()
        self.assertEqual(session["messages"][-1]["text"], "Thanks. What did you study?")
        self.assertEqual(model.call_args.args[1], BACKUP)
