# World Engine tests

Run from the repository root:

```bash
python -m pytest world-engine/tests -q
```

The prototype uses Python's standard-library SQLite implementation and pytest. It does not yet expose MCP tools or perform canonical governance evaluation. The storage API enforces data integrity and revision consistency; it is not an authorization mechanism.
