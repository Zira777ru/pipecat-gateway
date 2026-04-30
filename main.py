"""Pipecat Voice Gateway — универсальный голосовой AI бэкенд.

Эндпоинты:
  GET  /health        — статус и настроенные провайдеры
  WS   /ws/voice      — real-time стриминг (для браузеров, WebRTC-клиентов)
  POST /api/voice     — single-turn REST (для Telegram-ботов, n8n и т.д.)
  POST /api/transcribe — только STT (аудио → текст)
  POST /api/speak     — только TTS (текст → аудио)

Провайдеры задаются через env-переменные LLM_PROVIDER / STT_PROVIDER / TTS_PROVIDER.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Config ────────────────────────────────────────────────────────────────
LLM_PROVIDER        = os.getenv("LLM_PROVIDER", "google")
STT_PROVIDER        = os.getenv("STT_PROVIDER", "deepgram")
TTS_PROVIDER        = os.getenv("TTS_PROVIDER", "elevenlabs")
SYSTEM_PROMPT       = os.getenv("SYSTEM_PROMPT", "Ты голосовой AI-ассистент. Отвечай кратко и по делу.")
LANGUAGE            = os.getenv("LANGUAGE", "ru")

GOOGLE_API_KEY       = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_MODEL         = os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")
DEEPGRAM_API_KEY     = os.getenv("DEEPGRAM_API_KEY", "")
ELEVENLABS_API_KEY   = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID  = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
OPENAI_API_KEY       = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL         = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ─── Pipecat service factories ──────────────────────────────────────────────

def _build_stt(provider: str):
    if provider == "deepgram":
        from pipecat.services.deepgram.stt import DeepgramSTTService
        return DeepgramSTTService(api_key=DEEPGRAM_API_KEY)
    if provider == "openai":
        from pipecat.services.openai.stt import OpenAISTTService
        return OpenAISTTService(api_key=OPENAI_API_KEY)
    raise ValueError(f"Unknown STT provider: {provider!r}. Supported: deepgram, openai")


def _build_llm(provider: str):
    if provider == "google":
        from pipecat.services.google.llm import GoogleLLMService
        return GoogleLLMService(api_key=GOOGLE_API_KEY, model=GOOGLE_MODEL)
    if provider == "openai":
        from pipecat.services.openai.llm import OpenAILLMService
        return OpenAILLMService(api_key=OPENAI_API_KEY, model=OPENAI_MODEL)
    if provider == "anthropic":
        from pipecat.services.anthropic.llm import AnthropicLLMService
        return AnthropicLLMService(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    raise ValueError(f"Unknown LLM provider: {provider!r}. Supported: google, openai, anthropic")


def _build_tts(provider: str):
    if provider == "elevenlabs":
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService, ElevenLabsTTSSettings
        return ElevenLabsTTSService(
            api_key=ELEVENLABS_API_KEY,
            settings=ElevenLabsTTSSettings(voice_id=ELEVENLABS_VOICE_ID),
        )
    if provider == "openai":
        from pipecat.services.openai.tts import OpenAITTSService
        return OpenAITTSService(api_key=OPENAI_API_KEY)
    if provider == "google":
        from pipecat.services.google.tts import GoogleTTSService
        return GoogleTTSService(api_key=GOOGLE_API_KEY)
    raise ValueError(f"Unknown TTS provider: {provider!r}. Supported: elevenlabs, openai, google")


# ─── REST helpers (direct API calls, без Pipecat pipeline) ─────────────────

import httpx
from fastapi import HTTPException


async def _stt_rest(audio_bytes: bytes, content_type: str) -> str:
    """Расшифровка аудио. Пробует Deepgram (если ключ есть), иначе Gemini multimodal."""
    if DEEPGRAM_API_KEY:
        ct = content_type or "audio/ogg"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&language={LANGUAGE}",
                headers={"Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": ct},
                content=audio_bytes,
            )
            resp.raise_for_status()
        alts = resp.json()["results"]["channels"][0]["alternatives"]
        return alts[0]["transcript"] if alts else ""

    # Fallback: Gemini multimodal transcription
    if not GOOGLE_API_KEY:
        raise HTTPException(503, detail="Нужен DEEPGRAM_API_KEY или GOOGLE_API_KEY для STT")
    import base64
    audio_b64 = base64.b64encode(audio_bytes).decode()
    mime = content_type or "audio/ogg"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GOOGLE_MODEL}:generateContent?key={GOOGLE_API_KEY}",
            json={
                "contents": [{
                    "parts": [
                        {"inlineData": {"mimeType": mime, "data": audio_b64}},
                        {"text": "Transcribe this audio precisely. Return only the transcribed text, no other commentary."},
                    ]
                }],
                "generationConfig": {"maxOutputTokens": 500},
            },
        )
        resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


async def _llm_rest(text: str, system_prompt: str) -> str:
    """Ответ от Gemini через REST API."""
    if not GOOGLE_API_KEY:
        raise HTTPException(503, detail="GOOGLE_API_KEY не задан")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GOOGLE_MODEL}:generateContent?key={GOOGLE_API_KEY}",
            json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": text}]}],
                "generationConfig": {"maxOutputTokens": 400},
            },
        )
        resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


async def _tts_rest(text: str) -> bytes:
    """Синтез речи. Пробует ElevenLabs (если ключ есть), иначе gTTS (бесплатный)."""
    if ELEVENLABS_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                    headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
                    json={"text": text, "model_id": "eleven_turbo_v2_5", "output_format": "mp3_22050_32"},
                )
                if resp.status_code == 200:
                    return resp.content
                logger.warning(f"ElevenLabs HTTP {resp.status_code}, falling back to gTTS")
        except Exception as e:
            logger.warning(f"ElevenLabs failed: {e}, falling back to gTTS")

    # Free fallback: Google Translate TTS via gTTS
    import io, asyncio
    from gtts import gTTS
    lang = LANGUAGE[:2] if LANGUAGE else "ru"

    def _sync():
        tts = gTTS(text=text, lang=lang)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return buf.read()

    return await asyncio.get_event_loop().run_in_executor(None, _sync)


# ─── FastAPI app ────────────────────────────────────────────────────────────

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from loguru import logger

app = FastAPI(title="Voice Gateway", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "providers": {"llm": LLM_PROVIDER, "stt": STT_PROVIDER, "tts": TTS_PROVIDER},
        "model": GOOGLE_MODEL,
    }


@app.post("/api/transcribe")
async def transcribe_only(audio: UploadFile = File(...)):
    """Только STT: аудио → текст. Поддерживает OGG, MP3, WAV, FLAC."""
    audio_bytes = await audio.read()
    text = await _stt_rest(audio_bytes, audio.content_type or "audio/ogg")
    return {"transcript": text}


@app.post("/api/speak")
async def speak_only(text: str = Form(...)):
    """Только TTS: текст → MP3 аудио."""
    audio = await _tts_rest(text)
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/api/voice")
async def voice_rest(
    audio: UploadFile = File(...),
    system_prompt: str = Form(None),
):
    """Single-turn голосовой API: аудио в → аудио out.

    Использование из Telegram-бота (pyrogram):
        import httpx
        with open("voice.ogg", "rb") as f:
            r = httpx.post("https://voice.coscore.us/api/voice", files={"audio": f})
        # r.content — MP3 с ответом
        # r.headers["x-transcript"] — что сказал пользователь
        # r.headers["x-response"] — что ответил AI
    """
    prompt = system_prompt or SYSTEM_PROMPT
    audio_bytes = await audio.read()

    transcript = await _stt_rest(audio_bytes, audio.content_type or "audio/ogg")
    if not transcript.strip():
        raise HTTPException(422, "Не удалось распознать речь")
    logger.info(f"[REST] STT: {transcript!r}")

    response_text = await _llm_rest(transcript, prompt)
    logger.info(f"[REST] LLM: {response_text!r}")

    audio_out = await _tts_rest(response_text)
    return Response(
        content=audio_out,
        media_type="audio/mpeg",
        headers={
            "X-Transcript": transcript,
            "X-Response": response_text,
        },
    )


@app.websocket("/ws/voice")
async def websocket_voice(websocket: WebSocket):
    """Real-time стриминг голосового разговора.

    Клиент (браузер, приложение) подключается по WebSocket, шлёт аудио-чанки,
    получает аудио-ответ обратно в реальном времени.
    """
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineTask, PipelineParams
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            add_wav_header=True,
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    stt = _build_stt(STT_PROVIDER)
    llm = _build_llm(LLM_PROVIDER)
    tts = _build_tts(TTS_PROVIDER)

    context = OpenAILLMContext(messages=[{"role": "system", "content": SYSTEM_PROMPT}])
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline([
        transport.input(),
        stt,
        context_aggregator.user(),
        llm,
        context_aggregator.assistant(),
        tts,
        transport.output(),
    ])

    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))
    runner = PipelineRunner()

    try:
        await runner.run(task)
    except WebSocketDisconnect:
        logger.info("WebSocket отключён")
    except Exception as e:
        logger.error(f"Ошибка пайплайна: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
