import os
import sys
import asyncio
import aiohttp
from fastapi import FastAPI, WebSocket, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
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
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# --- Pipecat Bot Runner ---

async def run_bot(transport, llm_service, tts_service):
    pipeline = Pipeline([
        transport.input(),
        llm_service,
        tts_service,
        transport.output(),
    ])

    task = PipelineTask(pipeline)
    
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
    tts = GoogleTTSService(api_key=GOOGLE_API_KEY)
    
    await run_bot(transport, llm, tts)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
