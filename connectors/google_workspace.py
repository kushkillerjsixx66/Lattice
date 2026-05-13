import os
from dotenv import load_dotenv
from connectors.mcp_bridges import MCPConnector

load_dotenv()

class GeminiSensoryLayer(MCPConnector):
    """
    Sensory interface for Google Workspace (Gmail, Docs, Drive).
    Converts raw API events into structured Lattice pulses that
    feed directly into the P-A-D-S cycle via pulse_listener.py.
    """
    def __init__(self):
        super().__init__(service_name="google_workspace", auth_type="oauth2")
        self.watched_services = ["gmail", "docs", "drive"]
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        
        print(f"[SENSORY] Gemini API initialized: {self.gemini_api_key[:10]}...")

    def sense(self, event: dict) -> dict | None:
        """
        Receives a raw Google Workspace push notification and
        normalises it into a Lattice pulse payload.
        Returns None if the event should be silenced (Decay).
        """
        source = event.get("source")
        if source == "gmail":
            return self._parse_gmail(event)
        elif source == "docs":
            return self._parse_docs(event)
        return None  # Unknown source - Decay

    def _parse_gmail(self, event: dict) -> dict:
        """Maps a Gmail push notification to a GMAIL_UPDATE pulse."""
        return {
            "trigger": "GMAIL_UPDATE",
            "event_id": event.get("historyId"),
            "payload": {
                "thread_id": event.get("threadId"),
                "label_ids": event.get("labelIds", []),
                "snippet": event.get("snippet", ""),
            }
        }

    def _parse_docs(self, event: dict) -> dict:
        """Maps a Docs activity event to a DOCS_CHANGE pulse."""
        return {
            "trigger": "DOCS_CHANGE",
            "event_id": event.get("revisionId"),
            "payload": {
                "document_id": event.get("documentId"),
                "actor": event.get("actor", "unknown"),
                "change_type": event.get("changeType", "edit"),
            }
        }

    def declare_capabilities(self) -> dict:
        """Extends MCPConnector capabilities with Workspace-specific actions."""
        base = super().declare_capabilities()
        base["actions"] += ["watch_gmail", "watch_docs", "emit_pulse"]
        base["watched_services"] = self.watched_services
        return base

    def call_gemini(self, prompt: str) -> str:
        """
        Makes a request to Gemini API for AI-powered intent understanding.
        """
        import google.generativeai as genai
        
        genai.configure(api_key=self.gemini_api_key)
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content(prompt)
        return response.text
