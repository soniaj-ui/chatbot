# AI Multilingual Course Guidance Caller

This local prototype simulates an outbound course guidance call in the browser. It demonstrates the AI disclosure, consent, adaptive discovery, catalogue-backed recommendations, counsellor handoff and contact opt-out described in [the project submission](PROJECT_SUBMISSION.md).

## Run locally

From PowerShell in the project folder:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe run.py
```

If Python ships without virtual environment support, use `python -m pip install --target .venv-deps -r requirements.txt` followed by `python run.py`.

Open **http://127.0.0.1:8000** for the dashboard or **http://127.0.0.1:8000/docs** for the API. The default database is a local SQLite file. Set the `DATABASE_URL` environment variable to a provisioned `mysql+pymysql://user:password@host/database?charset=utf8mb4` DSN to use MySQL.

## Try a session

1. Add a fictional enquiry with PLC as the interest and check the demo contact permission box.
2. Select English, Tamil, Telugu or Hindi and start the session. Continue after the AI disclosure.
3. Enter an electrical engineering diploma, explain that you have never programmed a PLC, then describe your interest in hands-on PLC programming and factory maintenance.
4. The assistant recommends PLC Foundations from the fictional catalogue. Enter `fee` to check the approved fee or ask about weekend classes to see a counsellor referral.
5. Authorise a callback and optionally enter a preferred time. Open **Counsellor reports** to inspect the saved profile, catalogue reference and unanswered question.

### Hands-free voice call in the student's language

Use Google Chrome, because it has the best speech support for Tamil, Telugu and Hindi.

1. Keep **Auto-detect from the student's reply** selected and tick **Hands-free voice call**.
2. Start a session. The assistant greets in English and offers the four languages, then listens.
3. Say a language name such as "Tamil", or answer in that language, for example "ஆம்" or "हाँ". The assistant switches and continues by voice in that language.
4. Speak each answer when **Listening…** is shown. Questions such as "கட்டணம் எவ்வளவு?" are answered from the catalogue in the same language.

The student can switch language at any time by saying, for example, "speak in Hindi".

The dashboard can dictate and read replies aloud when supported by the browser and installed voices. Typed replies work independently of speech features. Use fictional details in the demo, especially when a browser speech service or remote model is enabled.

## Optional model integration

### Gemma 4 31B via Hugging Face

Create a [Hugging Face token](https://huggingface.co/settings/tokens) with Inference Providers permission. Enter it in PowerShell without displaying it or saving it in the project:

```powershell
$env:HF_TOKEN = [System.Net.NetworkCredential]::new('', (Read-Host 'Hugging Face token' -AsSecureString)).Password
python run.py --gemma --port 8001
```

Open **http://127.0.0.1:8001** and test with a fictional enquiry. This mode sends student replies and relevant conversation context to hosted `google/gemma-4-31B-it`. Hugging Face inference can incur charges. After consent, discovery questions drafted by Gemma are labelled **Model-generated question**. Provider failures are logged and the app falls back to local guidance.

### Other providers

Set `GUIDANCE_LLM_URL` to a trusted chat-completions endpoint that supports JSON object responses, and set `GUIDANCE_LLM_MODEL` and `GUIDANCE_LLM_KEY`. The model extracts explicitly stated profile information, classifies replies and drafts a discovery question using the previous turn. FastAPI checks that the question targets the expected topic and renders course facts from [catalogue.json](catalogue.json). With no model configured, local rules handle the conversation.

All course data are fictional samples. The optional model does not receive the enquiry name or phone field, but it receives the student’s replies and previously collected profile.

## Deployment scope

The prototype runs on localhost with fictional data. Browser speech simulates the voice channel, and callback requests enter a local review queue. Live outbound dialling, provider DND and calling-hours checks, dashboard authentication, and production privacy controls require provider configuration and deployment work. See the submission for the proposed production architecture.
