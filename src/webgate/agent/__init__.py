"""Read-only diagnostic agent.

Answers "why is this host unhappy?" by running an allowlisted set of harmless
commands over the operator's own SSH access and summarising what it finds.

Three properties make it safe to expose:

* **Read-only.** Commands come from a fixed allowlist (`tools.READ_ONLY_COMMANDS`);
  the model chooses *which* to run and with what arguments, never *what* to run.
* **Runs as the user.** Every server lookup goes through the same group ACL the UI
  uses, so the agent can never reach a host its caller cannot.
* **Audited.** Each command lands in the audit log attributed to the caller.

The model itself is reached over an OpenAI-compatible API, so it can be a local
Ollama (nothing leaves the network) or OpenRouter (managed, needs an API key).
"""
