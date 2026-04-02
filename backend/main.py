import os
import asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import opengradient as og
import httpx

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

PRIVATE_KEY = os.environ.get("PRIVATE_KEY")
MEMSYNC_BASE = "https://api.memchat.io/v1"

llm = og.LLM(
    private_key=PRIVATE_KEY,
    rpc_url="https://ogevmdevnet.opengradient.ai",
    tee_registry_address="0x4e72238852f3c918f4E4e57AeC9280dDB0c80248"
)

opg_approved = False


async def ensure_approval():
    global opg_approved
    if not opg_approved:
        try:
            llm.ensure_opg_approval(min_allowance=0.1, approve_amount=0.1)
            opg_approved = True
        except ValueError as e:
            raise HTTPException(status_code=402, detail=str(e))


def memsync_headers(api_key: str):
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


async def search_memories(query: str, wallet_address: str, api_key: str, app_name: str):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{MEMSYNC_BASE}/memories/search",
                headers=memsync_headers(api_key),
                json={
                    "query": query,
                    "app_name_id": app_name,
                    "user_id": wallet_address.lower(),
                    "limit": 8,
                    "rerank": True,
                },
                timeout=10,
            )
            res.raise_for_status()
            return res.json()
    except Exception as e:
        print(f"MemSync search error: {e}")
        return {"user_bio": "", "memories": []}


async def store_memory(user_msg: str, ai_response: str, wallet_address: str, api_key: str, app_name: str):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{MEMSYNC_BASE}/memories",
                headers=memsync_headers(api_key),
                json={
                    "messages": [
                        {"role": "user", "content": user_msg},
                        {"role": "assistant", "content": ai_response},
                    ],
                    "agent_id": app_name,
                    "user_id": wallet_address.lower(),
                    "thread_id": f"{wallet_address.lower()}-{int(asyncio.get_event_loop().time() * 1000)}",
                    "source": "chat",
                },
                timeout=10,
            )
    except Exception as e:
        print(f"MemSync store error: {e}")


class ChatRequest(BaseModel):
    message: str
    walletAddress: Optional[str] = None
    conversationHistory: Optional[List[dict]] = []
    memsyncApiKey: Optional[str] = None
    memsyncAppName: Optional[str] = None


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.message:
        raise HTTPException(status_code=400, detail="Message is required")

    await ensure_approval()

    app_name = req.memsyncAppName or "sage-web3-assistant"

    # 1. Search MemSync for relevant memories
    memories_context = ""
    user_bio = ""
    if req.walletAddress and req.memsyncApiKey:
        mem_data = await search_memories(req.message, req.walletAddress, req.memsyncApiKey, app_name)
        user_bio = mem_data.get("user_bio", "")
        memories = mem_data.get("memories", [])
        if memories:
            memories_context = "\n".join(f"- [{m['type']}] {m['memory']}" for m in memories)

    # 2. Build system prompt
    who_line = f"WHO THIS USER IS: {user_bio}" if user_bio else "This is a new user — learn about them naturally through conversation."
    memories_line = f"WHAT YOU REMEMBER ABOUT THIS USER:\n{memories_context}" if memories_context else ""
    system_prompt = f"""You are Sage, a personal Web3 AI assistant that remembers everything about the user across sessions. You are deeply knowledgeable about DeFi, blockchain technology, smart contracts, crypto markets, NFTs, DAOs, and Web3 development.

{who_line}

{memories_line}

YOUR PERSONALITY:
- Warm, knowledgeable, and genuinely helpful — like a brilliant friend who happens to know everything about Web3
- You use memories naturally without saying "based on your memories" — just incorporate them seamlessly
- For Web3 topics: give specific, actionable, honest advice
- For DeFi questions: give real analysis tailored to what you know about the user's experience and risk tolerance
- For transaction requests: explain clearly what will happen, mention the user will confirm in MetaMask
- Always be honest about uncertainty — never fabricate token prices or on-chain data
- Reference past conversations naturally: "You mentioned earlier..." or "Given your experience with..."

WALLET: {req.walletAddress or "Not connected"}

You are the AI that never forgets. Every conversation makes you more helpful to this user."""

    # 3. Build messages list
    messages = [{"role": "system", "content": system_prompt}]
    if req.conversationHistory:
        for msg in req.conversationHistory[-8:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": req.message})

    # 4. Call OpenGradient via x402
    result = await llm.chat(
        model=og.TEE_LLM.CLAUDE_HAIKU_4_5,
        messages=messages,
        max_tokens=1000,
        temperature=0.7,
    )
    ai_response = result.chat_output["content"]

    # 5. Store in MemSync async (fire and forget)
    if req.walletAddress and req.memsyncApiKey:
        asyncio.create_task(store_memory(req.message, ai_response, req.walletAddress, req.memsyncApiKey, app_name))

    return {
        "response": ai_response,
        "memoriesUsed": len(memories_context) > 0,
        "memoryCount": len(memories_context.split("\n")) if memories_context else 0,
    }


@app.get("/api/memories")
async def get_memories(walletAddress: str, memsyncApiKey: str, memsyncAppName: str = "sage-web3-assistant"):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"{MEMSYNC_BASE}/memories",
                headers=memsync_headers(memsyncApiKey),
                params={"app_name_id": memsyncAppName, "user_id": walletAddress.lower(), "limit": 50},
                timeout=10,
            )
            return res.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/profile")
async def get_profile(walletAddress: str, memsyncApiKey: str, memsyncAppName: str = "sage-web3-assistant"):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"{MEMSYNC_BASE}/users/profile",
                headers=memsync_headers(memsyncApiKey),
                params={"app_name_id": memsyncAppName, "user_id": walletAddress.lower()},
                timeout=10,
            )
            return res.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: str, memsyncApiKey: str):
    try:
        async with httpx.AsyncClient() as client:
            await client.delete(
                f"{MEMSYNC_BASE}/memories/{memory_id}",
                headers=memsync_headers(memsyncApiKey),
                timeout=10,
            )
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "app": "Sage Python Backend"}


# Serve frontend — must be last
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")
