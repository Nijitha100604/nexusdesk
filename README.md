# NexusDesk

**Autonomous Multi-Agent IT Helpdesk with ServiceNow Integration**

NexusDesk triages, resolves and escalates IT tickets using cooperating AI agents
(LangGraph), retrieval-augmented generation over a knowledge base, and a ServiceNow
instance as the system of record. Risky actions require human approval.

> Status: Phase 2 complete (project skeleton). Work in progress.

## Architecture
Diagrams and design decisions: see `docs/`.

## Tech stack
Python, FastAPI, LangGraph, ChromaDB, MongoDB, React, Tailwind CSS, ServiceNow REST API,
Groq / Gemini / Ollama.

## Prerequisites
Git, Python 3.11 or 3.12, Node.js LTS.

## Setup
```bash
git clone https://github.com/Nijitha100604/nexusdesk.git && cd nexusdesk
cp .env.example .env            # then add your own API keys

# Backend
cd backend
python -m venv .venv && source .venv/Scripts/activate   # macOS/Linux: .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload   # http://localhost:8000/docs

# Frontend (new terminal)
cd frontend && npm install && npm run dev   # http://localhost:5173

# Hooks and tests
pre-commit install
cd backend && pytest
```

## Project structure
`backend/` API, agents, RAG, ServiceNow integration | `frontend/` React app |
`data/` synthetic and evaluation data | `evaluation/` metrics scripts | `docs/` design docs

## Disclaimer
Educational portfolio project using synthetic data only. Sensitive actions are mocked.

## License
MIT
