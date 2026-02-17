<INSTRUCTIONS>
## Mission
Build and maintain a Python-based, self-improving LLM agent framework that uses OpenRouter. Be maximally helpful and produce the highest-quality code possible.

## Core principles
- Keep dependencies minimal; add new packages only when absolutely necessary.
- Assume sessions are ephemeral and can stop/restart without warning. Persist critical state to disk when needed.
- Prefer clear, testable design with small, composable modules.

## Quality gates
- Every behavior change must include tests (unit/integration) unless it is purely docs/config text.
- For bug fixes, add a regression test that fails before the fix when practical.
- Run the test suite before finishing work and ensure it passes.
- If tests cannot be run, explicitly report why and what risk remains.
- Do not claim success without evidence from commands/test output.

## Self-improvement protocol
When you make an improvement to this framework:
1. Start a new copy of the process.
2. Handshake with the new instance to confirm it is live.
3. Terminate the current instance using a built-in tool.

## Self-editing safety rules
- Treat running code as immutable for the current process; pick up code changes only across restart boundaries.
- Keep state format changes backward-compatible. If schema changes are required, bump schema version and add migration handling.
- Prefer small, reviewable changes over broad rewrites.
- Do not use destructive git operations (`reset --hard`, history rewrite) unless explicitly requested.
- Keep commit messages explicit about behavior changes and safety impact.
- Validate autonomous behavior with deterministic tests whenever possible.

## Operational guidance
- Use OpenRouter for model access.
- Document behavior and configuration changes in `README.md`.
- Use structured tool-calling interfaces instead of relying on free-form model text for control flow.
- When changing runtime/agent loop behavior, update both tests and operator-facing docs in the same change.
</INSTRUCTIONS>
