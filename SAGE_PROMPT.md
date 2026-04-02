# Sage — The Web3 AI That Remembers You
## Complete Build Blueprint for Claude Code

---

## Project Overview

Sage is a personal Web3 AI assistant powered by OpenGradient's MemSync memory infrastructure. Unlike any existing AI assistant, Sage remembers everything meaningful about the user across every session — their wallet activity, DeFi positions, risk preferences, projects, and goals — and gets smarter over time. Every AI response is backed by TEE-verified OpenGradient infrastructure.

Users connect their MetaMask wallet to identify themselves, chat with the AI, and Sage automatically stores memories from every conversation. Next session, Sage already knows who you are, what you're working on, and what you care about.

This is a grant submission for the OpenGradient Developer RTG program, showcasing MemSync — the most underutilized and most powerful feature of the OpenGradient ecosystem.

---

## Tagline

> *"Sage — The Web3 AI That Remembers You"*

---

## Architecture

```
User Browser (index.html - port 3000)
    │
    ├── MetaMask → wallet identity (wallet address = user_id for MemSync)
    ├── Chat UI → sends messages to backend
    └── Memory Panel → shows MemSync memories and profile

Backend (backend/server.js - port 3001)
    │
    ├── POST /api/chat → search memories + call Gemini + store conversation
    ├── GET /api/memories → fetch user's memories from MemSync
    ├── GET /api/profile → fetch user profile from MemSync
    └── DELETE /api/memories/:id → delete a specific memory
```

---

## File Structure

```
sage/
├── index.html              ← Complete frontend (single file)
├── backend/
│   └── server.js           ← Node.js Express backend
├── railway.toml            ← Railway deployment config
├── package.json
├── .env                    ← GEMINI_API_KEY + MEMSYNC_API_KEY + MEMSYNC_APP_NAME
└── PROMPT.md               ← This file
```

---

## MemSync API — CRITICAL: Correct API Design

### IMPORTANT — Read This First
From the official MemSync REST API docs:
- All endpoints require both `app_name_id` AND `user_id` parameters
- For API key authentication: `app_name_id` MUST match the API key's application name
- User context is automatically extracted from valid tokens
- API keys must be provided in the `X-API-Key` header

### Base URL
```
https://api.memchat.io/v1
```

### Authentication Headers
```javascript
headers: {
  "X-API-Key": process.env.MEMSYNC_API_KEY,
  "Content-Type": "application/json"
}
```

### Environment Variables Required
```
MEMSYNC_API_KEY=your_memsync_api_key
MEMSYNC_APP_NAME=sage-web3-assistant  // must match the app name registered with API key
```

### Store Memories — Correct Format
```javascript
POST https://api.memchat.io/v1/memories
{
  "messages": [
    { "role": "user", "content": "user message here" },
    { "role": "assistant", "content": "sage response here" }
  ],
  "agent_id": process.env.MEMSYNC_APP_NAME,  // must match API key's app name
  "user_id": walletAddress.toLowerCase(),     // wallet address as user identifier
  "thread_id": `${walletAddress.toLowerCase()}-${Date.now()}`,
  "source": "chat"
}
```

### Search Memories — Correct Format
```javascript
POST https://api.memchat.io/v1/memories/search
{
  "query": userMessage,
  "app_name_id": process.env.MEMSYNC_APP_NAME,  // required
  "user_id": walletAddress.toLowerCase(),         // required
  "limit": 8,
  "rerank": true
}
// Returns: { user_bio, memories: [{ id, memory, categories, type, vector_distance, rerank_score }] }
```

### Get User Profile — Correct Format
```javascript
GET https://api.memchat.io/v1/users/profile?app_name_id=${MEMSYNC_APP_NAME}&user_id=${walletAddress}
// Returns: { user_bio, profiles: { career, interests, ... }, insights }
```

### Get All Memories — Correct Format
```javascript
GET https://api.memchat.io/v1/memories?app_name_id=${MEMSYNC_APP_NAME}&user_id=${walletAddress}&limit=50
```

### Delete a Memory
```javascript
DELETE https://api.memchat.io/v1/memories/:memoryId
Headers: { "X-API-Key": MEMSYNC_API_KEY }
```

### Error Handling for MemSync
- 401 Unauthorized → API key invalid or app_name_id mismatch
- 403 Forbidden → Rate limit exceeded
- 429 Too Many Requests → implement exponential backoff
- Always wrap MemSync calls in try/catch — if they fail, continue without memories

---

## Backend: backend/server.js

### Dependencies
```
npm install express cors dotenv node-fetch
```

### Full Implementation

```javascript
import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import fetch from "node-fetch";

dotenv.config();

const app = express();
app.use(cors({ origin: "*", methods: ["GET", "POST", "DELETE"], allowedHeaders: ["Content-Type"] }));
app.use(express.json({ limit: "2mb" }));

const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const MEMSYNC_API_KEY = process.env.MEMSYNC_API_KEY;
const MEMSYNC_APP_NAME = process.env.MEMSYNC_APP_NAME || "sage-web3-assistant";
const MEMSYNC_BASE = "https://api.memchat.io/v1";
const GEMINI_URL = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${GEMINI_API_KEY}`;

const memsyncHeaders = {
  "X-API-Key": MEMSYNC_API_KEY,
  "Content-Type": "application/json"
};

// Helper: search memories for a user
async function searchMemories(query, walletAddress) {
  try {
    const res = await fetch(`${MEMSYNC_BASE}/memories/search`, {
      method: "POST",
      headers: memsyncHeaders,
      body: JSON.stringify({
        query,
        app_name_id: MEMSYNC_APP_NAME,
        user_id: walletAddress.toLowerCase(),
        limit: 8,
        rerank: true
      })
    });
    if (!res.ok) throw new Error(`MemSync search failed: ${res.status}`);
    return await res.json();
  } catch (e) {
    console.log("MemSync search error:", e.message);
    return { user_bio: "", memories: [] };
  }
}

// Helper: store conversation in MemSync
async function storeMemory(userMsg, aiResponse, walletAddress) {
  try {
    await fetch(`${MEMSYNC_BASE}/memories`, {
      method: "POST",
      headers: memsyncHeaders,
      body: JSON.stringify({
        messages: [
          { role: "user", content: userMsg },
          { role: "assistant", content: aiResponse }
        ],
        agent_id: MEMSYNC_APP_NAME,
        user_id: walletAddress.toLowerCase(),
        thread_id: `${walletAddress.toLowerCase()}-${Date.now()}`,
        source: "chat"
      })
    });
  } catch (e) {
    console.log("MemSync store error:", e.message);
  }
}

// ─── CHAT ENDPOINT ───
app.post("/api/chat", async (req, res) => {
  try {
    const { message, walletAddress, conversationHistory } = req.body;
    if (!message) return res.status(400).json({ error: "Message is required" });

    // 1. Search MemSync for relevant memories
    let memoriesContext = "";
    let userBio = "";
    if (walletAddress) {
      const memData = await searchMemories(message, walletAddress);
      userBio = memData.user_bio || "";
      const memories = memData.memories || [];
      if (memories.length > 0) {
        memoriesContext = memories.map(m => `- [${m.type}] ${m.memory}`).join("\n");
      }
    }

    // 2. Build system prompt
    const systemPrompt = `You are Sage, a personal Web3 AI assistant that remembers everything about the user across sessions. You are deeply knowledgeable about DeFi, blockchain technology, smart contracts, crypto markets, NFTs, DAOs, and Web3 development.

${userBio ? `WHO THIS USER IS: ${userBio}` : "This is a new user — learn about them naturally through conversation."}

${memoriesContext ? `WHAT YOU REMEMBER ABOUT THIS USER:\n${memoriesContext}` : ""}

YOUR PERSONALITY:
- Warm, knowledgeable, and genuinely helpful — like a brilliant friend who happens to know everything about Web3
- You use memories naturally without saying "based on your memories" — just incorporate them seamlessly
- For Web3 topics: give specific, actionable, honest advice
- For DeFi questions: give real analysis tailored to what you know about the user's experience and risk tolerance
- For transaction requests: explain clearly what will happen, mention the user will confirm in MetaMask
- Always be honest about uncertainty — never fabricate token prices or on-chain data
- Reference past conversations naturally: "You mentioned earlier..." or "Given your experience with..."

WALLET: ${walletAddress || "Not connected"}

You are the AI that never forgets. Every conversation makes you more helpful to this user.`;

    // 3. Build Gemini messages
    const contents = [];
    if (conversationHistory && conversationHistory.length > 0) {
      for (const msg of conversationHistory.slice(-8)) {
        contents.push({
          role: msg.role === "assistant" ? "model" : "user",
          parts: [{ text: msg.content }]
        });
      }
    }
    contents.push({ role: "user", parts: [{ text: message }] });

    // 4. Call Gemini
    const geminiRes = await fetch(GEMINI_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        system_instruction: { parts: [{ text: systemPrompt }] },
        contents,
        generationConfig: { temperature: 0.7, maxOutputTokens: 1000 }
      })
    });

    if (!geminiRes.ok) {
      const err = await geminiRes.text();
      throw new Error(`Gemini error: ${err}`);
    }

    const geminiData = await geminiRes.json();
    const aiResponse = geminiData.candidates[0].content.parts[0].text;

    // 5. Store in MemSync async
    if (walletAddress) {
      storeMemory(message, aiResponse, walletAddress);
    }

    res.json({
      response: aiResponse,
      memoriesUsed: memoriesContext.length > 0,
      memoryCount: memoriesContext ? memoriesContext.split("\n").length : 0
    });

  } catch (error) {
    console.error("Chat error:", error);
    res.status(500).json({ error: "Chat failed", details: error.message });
  }
});

// ─── GET MEMORIES ───
app.get("/api/memories", async (req, res) => {
  const { walletAddress } = req.query;
  if (!walletAddress) return res.status(400).json({ error: "walletAddress required" });
  try {
    const response = await fetch(
      `${MEMSYNC_BASE}/memories?app_name_id=${MEMSYNC_APP_NAME}&user_id=${walletAddress.toLowerCase()}&limit=50`,
      { headers: memsyncHeaders }
    );
    const data = await response.json();
    res.json(data);
  } catch (error) {
    res.status(500).json({ error: "Failed to fetch memories", details: error.message });
  }
});

// ─── GET PROFILE ───
app.get("/api/profile", async (req, res) => {
  const { walletAddress } = req.query;
  if (!walletAddress) return res.status(400).json({ error: "walletAddress required" });
  try {
    const response = await fetch(
      `${MEMSYNC_BASE}/users/profile?app_name_id=${MEMSYNC_APP_NAME}&user_id=${walletAddress.toLowerCase()}`,
      { headers: memsyncHeaders }
    );
    const data = await response.json();
    res.json(data);
  } catch (error) {
    res.status(500).json({ error: "Failed to fetch profile", details: error.message });
  }
});

// ─── DELETE MEMORY ───
app.delete("/api/memories/:id", async (req, res) => {
  try {
    await fetch(`${MEMSYNC_BASE}/memories/${req.params.id}`, {
      method: "DELETE",
      headers: memsyncHeaders
    });
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: "Failed to delete memory" });
  }
});

// ─── HEALTH ───
app.get("/health", (req, res) => res.json({ status: "ok", app: "Sage Backend" }));

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => console.log(`Sage backend running on port ${PORT}`));
```

---

## Frontend: index.html

### Design Aesthetic
- **Backgrounds**: Deep forest (#0D1F0F) left panel, dark charcoal (#121212) center chat, slightly lighter (#1A1A1A) right panel
- **Text**: Warm cream (#F5F0E8) primary, muted cream (#A89880) secondary
- **Accent**: Sage green (#7FB069) for Sage messages and active states, warm gold (#C4963A) for highlights and memory badges
- **Typography**: Cormorant Garamond or Playfair Display for "Sage" logo and headings (elegant serif), DM Sans or Inter for chat messages (clean readable), JetBrains Mono for wallet addresses
- **Feel**: Sophisticated, calm, wise — like a private advisor. Not flashy, not cyberpunk. Premium and trustworthy.
- **No** rounded corners on panels — clean straight edges with subtle borders

### Layout (Desktop — Three Column)
```
┌──────────────────────────────────────────────────────────────┐
│  HEADER: 🌿 Sage  |  "The Web3 AI That Remembers You"  | [Connect Wallet] │
├───────────────┬────────────────────────────┬─────────────────┤
│               │                            │                 │
│  MEMORIES     │      CHAT AREA             │  PROFILE &      │
│  PANEL        │                            │  SUGGESTIONS    │
│  (left 20%)   │  [message bubbles]         │  (right 25%)    │
│               │                            │                 │
│  • mem 1      │  User: ...                 │  [user bio]     │
│  • mem 2      │  Sage: ...                 │                 │
│  • mem 3      │                            │  Quick prompts: │
│               │  [input + send button]     │  • What do you  │
│  [semantic]   │                            │    remember?    │
│  [episodic]   │                            │  • My positions │
│               │                            │  • Analyze this │
└───────────────┴────────────────────────────┴─────────────────┘
```

Mobile: Single column with bottom tab bar (Chat | Memories | Profile)

### Header
- Left: Sage leaf icon (🌿 or SVG) + "Sage" in elegant serif font
- Center: "The Web3 AI That Remembers You" subtitle in small caps
- Right: Wallet connect button — shows "Connect Wallet" or truncated address when connected

### Chat Area (Center Panel)

User message bubble:
- Right-aligned
- Cream/tan background (#2A2218)
- Cream text
- Rounded right side

Sage message bubble:
- Left-aligned
- Forest green background (#142A16)
- Cream text
- Small "🌿 Sage" label above
- If memories were used: small "● Memory active" badge in sage green
- Typewriter animation for new responses

Typing indicator:
- Three animated dots: "Sage is thinking..."

Input area:
- Dark input box with cream placeholder text
- Send button in sage green
- Subtle "Powered by OpenGradient MemSync" text below

### Memory Panel (Left)

Header: "MEMORIES" in small caps with a count badge

Each memory card:
```
┌──────────────────────────────┐
│ [SEMANTIC] [career]          │
│ "User is building Web3       │
│  projects in Nigeria"        │
│                        [✕]  │
└──────────────────────────────┘
```
- Semantic memories: gold left border
- Episodic memories: sage green left border
- Hover: shows delete button
- Categories shown as small badges

Empty state:
- "Start chatting and Sage will begin learning about you"
- Small leaf icon

### Profile Panel (Right)

Top section — User Bio:
- Auto-generated bio from MemSync
- Updates as memories accumulate
- "Building your profile..." if no bio yet

Middle section — Quick Prompts (clickable chips):
- "What do you remember about me?"
- "What are my current DeFi positions?"
- "Help me analyze a token"
- "What should I focus on today?"
- "Explain reentrancy attacks"
- "What DeFi protocols are safe?"

Bottom section — Wallet Info:
- Address (truncated, monospace)
- Network badge
- ETH balance (fetched from provider)

### JavaScript Architecture

```javascript
// State
let walletAddress = null;
let conversationHistory = [];
let isTyping = false;

// Key functions:

async function connectWallet() {
  // Request MetaMask
  // Get address
  // Update UI
  // Load memories and profile for this address
  await loadMemories();
  await loadProfile();
}

async function sendMessage() {
  const message = input.value.trim();
  if (!message || isTyping) return;
  
  // Add user message to UI
  addMessageToUI("user", message);
  conversationHistory.push({ role: "user", content: message });
  
  // Show typing indicator
  showTypingIndicator();
  
  // Call backend
  const res = await fetch(`${BACKEND_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, walletAddress, conversationHistory })
  });
  const data = await res.json();
  
  // Hide typing, show response
  hideTypingIndicator();
  addMessageToUI("assistant", data.response, data.memoriesUsed);
  conversationHistory.push({ role: "assistant", content: data.response });
  
  // Refresh memories after delay (MemSync needs time to process)
  setTimeout(() => loadMemories(), 3000);
}

async function loadMemories() {
  if (!walletAddress) return;
  const res = await fetch(`${BACKEND_URL}/api/memories?walletAddress=${walletAddress}`);
  const data = await res.json();
  renderMemories(data.memories || data || []);
}

async function loadProfile() {
  if (!walletAddress) return;
  const res = await fetch(`${BACKEND_URL}/api/profile?walletAddress=${walletAddress}`);
  const data = await res.json();
  renderProfile(data);
}

async function deleteMemory(memoryId) {
  await fetch(`${BACKEND_URL}/api/memories/${memoryId}`, { method: "DELETE" });
  await loadMemories(); // Refresh
  showToast("Memory deleted");
}
```

### Key Constants
```javascript
const BACKEND_URL = "http://localhost:3001"; // Update to Railway URL for production
```

---

## .env File

```
GEMINI_API_KEY=get_from_aistudio.google.com_apikey
MEMSYNC_API_KEY=get_from_opengradient.ai_memsync_dashboard
MEMSYNC_APP_NAME=sage-web3-assistant
```

---

## Package.json

```json
{
  "type": "module",
  "scripts": {
    "start": "concurrently \"npm run backend\" \"npm run frontend\"",
    "backend": "node backend/server.js",
    "frontend": "npx serve . -p 3000"
  }
}
```

---

## Railway Config (railway.toml)

```toml
[deploy]
startCommand = "node backend/server.js"
```

---

## Build Order

1. `npm init -y`
2. `npm install express cors dotenv node-fetch concurrently`
3. Create `backend/server.js` with exact code above
4. Create `railway.toml`
5. Create `.env` — ask user for GEMINI_API_KEY and MEMSYNC_API_KEY
6. Build complete `index.html` with all three panels
7. `npm start`
8. Test at http://localhost:3000

---

## Test Conversations

**Test 1 — First session, memory formation:**
Say: "I'm a medical student in Nigeria and I build Web3 projects for grant programs"
Expected: Sage responds warmly → MemSync stores semantic memories about identity

**Test 2 — Memory search (wait 5 seconds, then ask):**
Say: "What do you know about me so far?"
Expected: Sage recalls and references the medical student / Web3 builder context

**Test 3 — DeFi help with personalization:**
Say: "I'm thinking about using Aave to earn yield on my USDC, what do you think?"
Expected: Sage gives advice that feels tailored to the user's experience level it has learned

**Test 4 — Memory panel:**
After a few messages, click Memory Panel → should show extracted memories as cards

---

## Getting API Keys

### Gemini API Key
1. Go to https://aistudio.google.com/apikey
2. Create new API key (free tier sufficient)

### MemSync API Key
1. Go to https://www.opengradient.ai/memsync
2. Sign up for a MemSync account
3. Go to the Developers page in the dashboard
4. Generate an API key
5. Note the application name — this must match MEMSYNC_APP_NAME in .env

---

## What Makes This Grant-Worthy

1. **First MemSync dApp** — No one in the OpenGradient ecosystem has shipped a MemSync app yet — wide open territory
2. **Genuinely novel** — Wallet address as persistent memory identity is a new approach
3. **Showcases OpenGradient uniquely** — MemSync + TEE-verified infrastructure, completely different from AuditShield
4. **Actually useful** — People would use a Web3 AI that genuinely remembers them
5. **Premium UI** — Three-panel layout with sage green editorial design
6. **Real personalization** — Not simulated memory, actual MemSync-powered persistent context
7. **Extensible** — Future versions could add Twitter/LinkedIn import via MemSync integrations API
