import os
import shutil
import subprocess
import threading
import uuid
import webbrowser
from pathlib import Path
from typing import Dict

import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

load_dotenv()

ROOT = Path(__file__).resolve().parent
JOBS_DIR = ROOT / "jobs"
JOBS_DIR.mkdir(exist_ok=True)
PORT = 7860

AZURE_SPEECH_KEY = os.environ.get("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.environ.get("AZURE_SPEECH_REGION")

LANG_MAP = {
    "en": "en-US", "zh": "zh-CN", "de": "de-DE", "fr": "fr-FR",
    "es": "es-ES", "it": "it-IT", "ja": "ja-JP", "ko": "ko-KR",
    "pt": "pt-BR", "ru": "ru-RU", "nl": "nl-NL",
}
AUTO_DETECT_LANGS = ["en-US", "zh-CN", "de-DE", "fr-FR"]

app = FastAPI()
jobs: Dict[str, dict] = {}


def probe_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def seconds_to_srt_time(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec_int = int(s % 60)
    ms = int((s - int(s)) * 1000)
    return f"{h:02d}:{m:02d}:{sec_int:02d},{ms:03d}"


def write_outputs(segments, txt_path: Path, srt_path: Path):
    txt_path.write_text("\n".join(text for _, _, text in segments) + "\n")
    with open(srt_path, "w") as f:
        for i, (start, end, text) in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}\n")
            f.write(f"{text}\n\n")


def transcribe_azure(wav_path: Path, language: str, job: dict, duration: float | None):
    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION,
    )
    audio_config = speechsdk.audio.AudioConfig(filename=str(wav_path))

    if language == "auto":
        auto_detect = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=AUTO_DETECT_LANGS,
        )
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            auto_detect_source_language_config=auto_detect,
            audio_config=audio_config,
        )
    else:
        speech_config.speech_recognition_language = LANG_MAP.get(language, "en-US")
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, audio_config=audio_config,
        )

    segments = []
    done = threading.Event()
    error_msg = {"text": None}

    def on_recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
            start = evt.result.offset / 10_000_000.0
            dur = evt.result.duration / 10_000_000.0
            end = start + dur
            segments.append((start, end, evt.result.text))
            job["progress_seconds"] = end
            if duration:
                job["progress_pct"] = min(99, int(100 * end / duration))

    def on_canceled(evt):
        if evt.reason == speechsdk.CancellationReason.Error:
            error_msg["text"] = f"Azure Speech error: {evt.error_details}"
        done.set()

    def on_stopped(_evt):
        done.set()

    recognizer.recognized.connect(on_recognized)
    recognizer.session_stopped.connect(on_stopped)
    recognizer.canceled.connect(on_canceled)

    recognizer.start_continuous_recognition()
    done.wait()
    recognizer.stop_continuous_recognition()

    if error_msg["text"]:
        raise RuntimeError(error_msg["text"])
    return segments


def run_job(job_id: str, audio_path: Path, language: str):
    job = jobs[job_id]
    work = JOBS_DIR / job_id
    try:
        duration = probe_duration(audio_path)
        job["duration"] = duration

        job["status"] = "converting"
        wav_path = work / "audio.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(audio_path),
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav_path)],
            check=True,
        )

        job["status"] = "transcribing"
        segments = transcribe_azure(wav_path, language, job, duration)

        out_base = work / "transcript"
        txt_path = Path(str(out_base) + ".txt")
        srt_path = Path(str(out_base) + ".srt")
        write_outputs(segments, txt_path, srt_path)

        job["txt_path"] = str(txt_path)
        job["srt_path"] = str(srt_path)
        job["text"] = txt_path.read_text()
        job["status"] = "done"
        job["progress_pct"] = 100
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
    finally:
        wav = work / "audio.wav"
        if wav.exists():
            try:
                wav.unlink()
            except Exception:
                pass


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


@app.post("/api/transcribe")
async def api_transcribe(
    audio: UploadFile = File(...),
    language: str = Form("auto"),
):
    if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
        raise HTTPException(500, "AZURE_SPEECH_KEY and AZURE_SPEECH_REGION must be set in environment or .env")

    job_id = uuid.uuid4().hex[:12]
    work = JOBS_DIR / job_id
    work.mkdir()
    suffix = Path(audio.filename or "audio").suffix or ".bin"
    audio_path = work / f"input{suffix}"
    with open(audio_path, "wb") as f:
        shutil.copyfileobj(audio.file, f)

    jobs[job_id] = {
        "status": "queued",
        "filename": audio.filename,
        "language": language,
        "progress_pct": 0,
        "progress_seconds": 0,
        "duration": None,
    }
    threading.Thread(target=run_job, args=(job_id, audio_path, language), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
def api_status(job_id: str):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "unknown job")
    return {k: v for k, v in j.items() if k not in ("text", "txt_path", "srt_path")}


@app.get("/api/result/{job_id}")
def api_result(job_id: str):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "unknown job")
    if j.get("status") != "done":
        raise HTTPException(409, "not ready")
    return {"text": j["text"]}


@app.get("/api/download/{job_id}/{kind}")
def api_download(job_id: str, kind: str):
    j = jobs.get(job_id)
    if not j or j.get("status") != "done":
        raise HTTPException(404, "not ready")
    base = (j.get("filename") or "transcript")
    base = Path(base).stem
    if kind == "txt":
        return FileResponse(j["txt_path"], media_type="text/plain",
                            filename=f"{base}.txt")
    if kind == "srt":
        return FileResponse(j["srt_path"], media_type="application/x-subrip",
                            filename=f"{base}.srt")
    raise HTTPException(404, "bad kind")


if __name__ == "__main__":
    import uvicorn

    def open_browser():
        import time
        time.sleep(1.2)
        webbrowser.open(f"http://localhost:{PORT}")

    threading.Thread(target=open_browser, daemon=True).start()
    print(f"\n  Transcriber running at http://localhost:{PORT}")
    print(f"  (Press Ctrl+C to stop)\n")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
