import os
import sys
import asyncio
import aiohttp
from fastapi import FastAPI, WebSocket, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from pipecat.transports.services.daily import DailyTransport, DailyParams
from pipecat.transports.services.fastapi_websocket import FastAPIWebsocketTransport, FastAPIWebsocketParams
from pipecat.services.google import GoogleLLMService, GoogleTTSService
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.vad.silero import SileroVADAnalyzer

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuration ---
DAILY_API_KEY = os.getenv("DAILY_API_KEY")
DAILY_API_URL = os.getenv("DAILY_API_URL", "https://api.daily.co/v1")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# --- Daily WebRTC Logic ---

async def create_daily_room():
    headers = {
        "Authorization": f"Bearer {DAILY_API_KEY}",
        "Content-Type": "application/json"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{DAILY_API_URL}/rooms", headers=headers, json={
            "properties": {
                "exp": int(asyncio.get_event_loop().time()) + 3600, # 1 hour
                "enable_chat": True
            }
        }) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise HTTPException(status_code=resp.status, detail=f"Failed to create room: {text}")
            return await resp.json()

@app.post("/daily/room")
async def join_daily_room():
    if not DAILY_API_KEY:
        raise HTTPException(status_code=500, detail="DAILY_API_KEY not configured")
    
    room = await create_daily_room()
    # Here we would normally start a background process/task to run the bot in this room
    # For now, we just return the room info. In a real scenario, you'd trigger a bot runner.
    return room

# --- Pipecat Bot Runner ---

async def run_bot(transport, llm_service, tts_service):
    pipeline = Pipeline([
        transport.input(),
        llm_service,
        tts_service,
        transport.output(),
    ])

    task = PipelineTask(pipeline)
    
    @transport.event_handler("on_participant_joined")
    async def on_participant_joined(transport, participant):
        await task.queue_frames([llm_service.user_joined_frame(participant)])

    runner = PipelineRunner()
    await runner.run(task)

# --- WebSocket Endpoint ---

@app.websocket("/ws/bot")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            vad_analyzer=SileroVADAnalyzer()
        )
    )
    
    llm = GoogleLLMService(api_key=GOOGLE_API_KEY, model="gemini-1.5-flash")
    tts = GoogleTTSService(api_key=GOOGLE_API_KEY) # Google uses same key or ADC
    
    await run_bot(transport, llm, tts)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
