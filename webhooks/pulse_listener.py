import os
from flask import Flask, request, jsonify
from core.dag_engine import LatticeOrchestrator

app = Flask(__name__)
orchestrator = LatticeOrchestrator()

@app.route('/gemini-pulse', methods=['POST'])
def handle_pulse():
      """
          Listens for Gemini API Webhooks (e.g., Gmail updates, Doc changes).
              Triggers the P-A-D-S (Pulse-Activation-Decay-Silence) cycle.
                  """
      pulse_data = request.json
      # Environmental sensing via Gemini 2026 Personal Intelligence
      if pulse_data.get("trigger") == "GMAIL_UPDATE":
                print(f"Pulse detected: {pulse_data['event_id']}")
                # Activate the workflow DAG based on sensed intent
                orchestrator.activate_flow(pulse_data["payload"])
                return jsonify({"status": "Activated"}), 200

      return jsonify({"status": "Decay"}), 204

if __name__ == "__main__":
      app.run(port=5000)
