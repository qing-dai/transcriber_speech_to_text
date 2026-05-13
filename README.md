# Transcriber (What it does)

A simple web app that turns audio files (m4a, mp3, wav, mp4, etc.) into text.

- Drop a file in the browser, get the transcript back. 
- **Speakers:** Up to 6 different speakers will be recognized. 
- **Latency:** 1h audio file takes about 2min to transcribe. 
- **Deployment:** The app is deployed on Azure Container Apps, using Azure AI Speech for transcription. 
- **Authentication:** You need a Github account to sign in, and I will need to add your Github username to the allowlist for access. 

## The Tech behind it

- Upload any common audio or video file through the browser UI.
- The app converts it to WAV with `ffmpeg`, then sends it to Azure AI Speech.
- Returns the full transcript with:
  - Speaker labels (up to 6 distinct speakers, automatic diarization).
  - Timestamps (for `.srt` subtitle export).
  - Multilingual auto-detection (English, Chinese, German, French) or a fixed language.
- Download the result as `.txt` or `.srt`, or copy it to clipboard.

## Model behind it

The transcription is done by **Azure AI Speech — Fast Transcription API** (`api-version=2025-10-15`).

- Synchronous: one HTTP `POST` returns the entire transcript.
- About 5–10× faster than real-time. A 1-hour audio file takes 2-3 minutes.
- File limits: 1 GB, 2 hours, multipart upload.
- Native speaker diarization and language identification.

Azure AI Speech was chosen over OpenAI Whisper because Whisper is not available in the regions allowed by the Azure-for-Students subscription used for this project, and AI Speech supports longer files without the 25 MB Whisper REST limit.

## Useful for

- Voice memos, interviews, meetings, lectures.
- Pre-processing audio for downstream AI models (summarization, search, Q&A).
- Multi-speaker conversations where speaker separation matters.
- Mixed-language audio without picking a locale upfront.

## Architecture

```
Browser (incognito ok)
    |
    | HTTPS + GitHub OAuth sign-in
    v
Azure Container Apps (FastAPI + ffmpeg)
    |
    +-- ffmpeg: convert input to 16kHz mono WAV
    +-- Azure AI Speech: Fast Transcription API
    +-- write .txt and .srt
    |
    v
Result returned to browser
```

**Tech stack**
- Python 3.11, FastAPI, uvicorn
- Vanilla HTML + JS frontend (no framework)
- `ffmpeg` for audio conversion
- Azure AI Speech (transcription)
- Docker (container)
- Azure Container Registry (private image store)
- Azure Container Apps (serverless container host)
- GitHub Actions (CI/CD with staging + manual-approval production)
- GitHub OAuth + per-user allowlist (authentication)

## Authentication model

The cloud deployment is **invite-only**:

1. Anyone hitting the URL is redirected to GitHub sign-in.
2. After sign-in, a small middleware in [app.py](app.py) checks the GitHub username against the `ALLOWED_USERS` environment variable.
3. Listed users get in. Everyone else gets `403`.

To invite someone, add their GitHub username to `ALLOWED_USERS` (comma-separated) on the Container App, then redeploy.

Locally, `ALLOWED_USERS` is empty, so auth is skipped.

## Run locally

Prerequisites: Python 3.11+, `ffmpeg` (`brew install ffmpeg` on macOS), an Azure AI Speech key.

```bash
git clone https://github.com/qing-dai/transcriber_speech_to_text.git
cd transcriber_speech_to_text

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: fill in AZURE_SPEECH_KEY and AZURE_SPEECH_REGION
# Leave ALLOWED_USERS empty for local dev.

python app.py
# Browser opens at http://localhost:7860
```

macOS shortcut: double-click `Start Transcriber.command` after the first manual setup.

## Deploy to Azure

Pushes to `main` trigger the CI/CD pipeline in `.github/workflows/deploy.yml`:

```
push to main
    |
    v
+--------------------+
| build: Docker image|  (linux/amd64, tagged with commit SHA)
| push to ACR        |
+----------+---------+
           |
           v
+----------+---------+
| deploy-staging     |  auto
| (transcriber-      |
|   staging)         |
+----------+---------+
           |
           v
+----------+---------+
| deploy-production  |  requires manual approval
| (transcriber-prod) |  in GitHub Environments
+--------------------+
```

**One-time Azure setup (currently manual via `az` CLI):**

- Resource group: `rg-whisper`
- Azure AI Speech service (tier S0)
- Azure Container Registry with admin user
- Container Apps environment + two Container Apps (staging + prod)
- User-Assigned Managed Identity for GitHub Actions, with federated credentials for `environment:staging`, `environment:production`, and `ref:refs/heads/main`
- Role assignment: `Container Registry Repository Contributor` on the registry (ABAC mode), `Contributor` on the resource group
- GitHub OAuth app per Container App, configured via `az containerapp auth github update`

**GitHub setup:**

- Repository secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
- Environments: `staging` (no protection rules), `production` (required reviewers)

Future improvement: rewrite the one-time setup as Terraform for reproducibility.

## Project layout

```
.
├── app.py                       # FastAPI app, audio pipeline, auth middleware
├── index.html                   # Frontend UI
├── requirements.txt             # Python dependencies
├── Dockerfile                   # linux/amd64 image build
├── .dockerignore
├── .env.example                 # Template for local env vars
├── .gitignore
├── Start Transcriber.command    # macOS double-click launcher
└── .github/
    └── workflows/
        └── deploy.yml           # CI/CD pipeline
```

## Limitations

- Audio limits: 1 GB / 2 hours per file (Azure AI Speech Fast Transcription).
- Auto-detect language considers only 4 candidate locales (configurable in `app.py`).
- Up to 6 speakers in diarization.
- Job state is in-memory; restarting the container loses in-progress jobs.
- The Azure setup is not yet codified in IaC (Terraform / Bicep) — see the future improvement note above.

## License

MIT
