# Notes for Karim: ai-pr-code-reviewer

## Resume bullets
- Built a multi-agent GitHub PR reviewer (4 parallel specialist Claude agents with tool use, ruff/bandit grounding, FastAPI webhook, GitHub Action, Docker); 52 automated tests.
- Designed a deterministic aggregator that validates every comment against the diff's line map, dedupes across agents and static analysis, and caps output, so hallucinated locations can never be posted.
- Created a 28-PR seeded-bug eval harness (19 labelled issues): static analysis alone scored P 0.77 / R 0.68; pipeline measured with scripted agents (a real model has not yet been evaluated). Update this bullet once you run `--modes llm`.

## Likely interview questions
1. **Why multi-agent over one prompt?** Focused prompts per category improve precision, run in parallel, and one failure doesn't sink the review (`orchestrator.py`).
2. **How do you stop hallucinated line numbers?** Annotated diff in the prompt plus `validate_locations` in `aggregator.py` against `FileDiff.visible_lines`.
3. **How do you evaluate an LLM system?** Seeded-bug set, one-to-one matching with line tolerance, precision/recall per category, FP rate on clean PRs; be upfront that the scripted rows only test the pipeline.
4. **Prompt injection from PR content?** Untrusted tags are a hint only; the defence is read-only tools, path sandbox, schema validation, deterministic filtering.
5. **Cost control?** Turn cap, token budget, truncated outputs, comment cap, annotated diff instead of whole files.

## Understand before interviews
- `diff.py`: new-file line counter advances on `+` and context lines only; this defines where GitHub accepts comments.
- `agents.py`: the loop appends the assistant blocks, executes tool calls, returns `tool_result` blocks; `submit_findings` ends it. Invalid findings are counted, not raised.
- `aggregator.dedupe`: same file and category within 2 lines merges; severity is the max, LLM wording is preferred, and `static+llm` gets a 1.5x rank boost.
- Eval caveat: combined precision is below LLM-only because static noise is posted unfiltered; the fix (LLM-verified static findings) is on the roadmap.
