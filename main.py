import json
from connectors.google_workspace import GeminiSensoryLayer
from core.dag_engine import LatticeOrchestrator
from core.sandbox import SandboxExecutor
from webhooks.pulse_listener import app

#  Lattice Runtime Bootstrap 

def boot() -> dict:
      """
          Initialises all three runtime layers and returns a shared context
              object that pulse_listener.py and the DAG engine can reference.
                  """
      sensory_layer = GeminiSensoryLayer()
      orchestrator  = LatticeOrchestrator()
      sandbox       = SandboxExecutor()

    # Declare connector capabilities at boot  fail fast on misconfiguration
      caps = sensory_layer.declare_capabilities()
      print(f"[BOOT] Sensory layer ready: {caps['watched_services']}")
      print(f"[BOOT] Sandbox stateless: {sandbox.is_stateless}")

return {
              "sensory":      sensory_layer,
              "orchestrator": orchestrator,
              "sandbox":      sandbox,
       }


def ingest_intent(raw_event: dict, ctx: dict) -> None:
      """
          Core entry path: sense  normalise  emit DAG  route to skills.

              P-A-D-S cycle:
                    Pulse      raw event arrives from Google Workspace
                          Activate   GeminiSensoryLayer normalises it into a Lattice pulse
                                Decay      unrecognised events are silenced here (returns None)
                                      Silence    orchestrator routes remaining tasks; sandbox verifies output
                                          """
      pulse = ctx["sensory"].sense(raw_event)

    if pulse is None:
              print("[DECAY] Event did not match any known trigger. Silenced.")
              return

    print(f"[ACTIVATE] Pulse: {pulse['trigger']} | event_id: {pulse['event_id']}")

    # Emit the DAG from the intent payload
    dag = ctx["orchestrator"].emit_dag(pulse["payload"])
    print(f"[DAG] Emitted workflow v{dag['version']} with {len(dag['tasks'])} tasks")

    # Route each task through the sandbox
    for task in dag["tasks"]:
              ctx["sandbox"].execute(task)
              ctx["orchestrator"].route_to_skill(task)

    print("[SILENCE] All tasks dispatched. Awaiting verifier handoff.")


if __name__ == "__main__":
      ctx = boot()

    # Attach the shared context to the Flask app so pulse_listener
      # can call ingest_intent() on every incoming webhook
      app.config["LATTICE_CTX"]    = ctx
      app.config["INGEST_HANDLER"] = ingest_intent

    print("[LATTICE] Runtime online  listening on port 5000")
    app.run(port=5000, debug=False)
