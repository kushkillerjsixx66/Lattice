# Lattice - Constraint Navigation Framework

AI-powered automation framework integrating Google Workspace with Gemini API for intelligent task orchestration.

## Features

- **P-A-D-S Cycle**: Pulse → Activate → Decay → Silence workflow
- **Gemini AI Integration**: Real-time event understanding and intent parsing
- **DAG Orchestration**: Task dependency management with constraint navigation
- **Sandbox Execution**: Isolated, stateless task execution
- **Google Workspace Connectors**: Gmail, Docs, Drive event streaming

## Quick Start

### 1. Clone & Install
```bash
git clone https://github.com/kushkillerjsixx66/Lattice.git
cd Lattice
pip install -r requirements.txt
```

### 2. Configure Environment
Create a `.env` file in the project root:
```bash
cp .env.example .env
```

Add your Gemini API Key:
```
GEMINI_API_KEY=your_gemini_api_key_here
```

**Get your API Key**: [Google AI Studio](https://aistudio.google.com)

### 3. Run the Application
```bash
python main.py
```

Expected output:
```
[BOOT] Sensory layer ready: {'watched_services': ['gmail', 'docs', 'drive']}
[BOOT] Sandbox stateless: True
[LATTICE] Runtime online - listening on port 5000
```

## Testing

Send a test pulse to the webhook:
```bash
curl -X POST http://localhost:5000/gemini-pulse \
  -H "Content-Type: application/json" \
  -d '{
    "trigger": "GMAIL_UPDATE",
    "event_id": "123456",
    "source": "gmail",
    "payload": {
      "threadId": "abc123",
      "labelIds": ["INBOX"],
      "snippet": "summarize this report"
    }
  }'
```

## Architecture

```
┌─────────────────┐
│  Google Events  │
└────────┬────────┘
         │
    ┌────▼────────────────────┐
    │  Sensory Layer (Gemini) │  ← Normalizes events into pulses
    └────┬────────────────────┘
         │
    ┌────▼──────────────────┐
    │  P-A-D-S Cycle        │
    │  ├─ Pulse: Sense      │
    │  ├─ Activate: Parse   │
    │  ├─ Decay: Filter     │
    │  └─ Silence: Route    │
    └────┬──────────────────┘
         │
    ┌────▼──────────���──────┐
    │  DAG Orchestrator    │  ← Task dependency graph
    └────┬─────────────────┘
         │
    ┌────▼──────────────────┐
    │  Sandbox Executor    │  ← Isolated execution
    └──────────────────────┘
```

## Project Structure

```
Lattice/
├── connectors/           # External service integrations
│   ├── google_workspace.py
│   └── mcp_bridges.py
├── core/                 # Core runtime components
│   ├── dag_engine.py
│   └── sandbox.py
├── skills/              # Task executors (AI models)
├── webhooks/            # Event ingestion
│   └── pulse_listener.py
├── workflows/           # DAG definitions
├── main.py              # Application bootstrap
├── requirements.txt     # Dependencies
└── .env.example         # Configuration template
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | ✅ Yes | Google Gemini API key |
| `GOOGLE_CLIENT_ID` | ❌ No | Google OAuth2 client ID |
| `GOOGLE_CLIENT_SECRET` | ❌ No | Google OAuth2 secret |
| `FLASK_ENV` | ❌ No | Flask environment (development/production) |
| `PORT` | ❌ No | Server port (default: 5000) |

## Dependencies

- **Flask** (3.0.0+) - Web framework
- **google-generativeai** (0.3.0+) - Gemini API
- **google-auth** (2.29.0+) - Google authentication
- **pydantic** (2.7.0+) - Data validation
- **python-dotenv** (1.0.1+) - Environment management

## Workflow Example

1. Gmail event → `/gemini-pulse` webhook
2. Sensory layer normalizes → Lattice pulse
3. DAG engine emits 3-task workflow
4. Sandbox executes each task in isolation
5. Results verified before output

## Future Enhancements

- [ ] Full Google Workspace OAuth2 setup
- [ ] Skill plugin system
- [ ] Real-time constraint satisfaction
- [ ] Multi-model orchestration (Claude, Copilot)
- [ ] Persistent workflow state
- [ ] Monitoring & observability

## License

MIT

## Author

Jeremy Sebastian (@kushkillerjsixx66)
