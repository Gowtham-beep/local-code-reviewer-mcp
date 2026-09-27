# Design Decisions and Trade-offs

This document outlines the architectural decisions made during the 3-day build of the Local Code Reviewer, including the alternatives considered, rationale, and observed limitations.

---

### 1. Language: Python over TypeScript
- **Decision:** Build the project in Python.
- **Alternatives Considered:** TypeScript / npm-workspaces.
- **Why Chosen:** The project was originally scaffolded in TypeScript/npm-workspaces. It was restarted in Python 3 days before an interview because the target team's stack is Python/FastAPI/FastMCP, and demonstrating fit with that stack mattered more than reusing existing scaffolding.

---

### 2. Hand-written Agent Loop vs LangChain/LangGraph
- **Decision:** Implement a hand-written agent loop from scratch without an agent framework.
- **Alternatives Considered:** LangChain or LangGraph.
- **Why Chosen:** Hand-writing the loop ensured that every underlying mechanism—message history accumulation, tool-call detection, JSON schema mapping, and iteration limits—is fully understood and explainable without relying on framework abstractions.
- **Trade-off:** Required writing more boilerplate and error-handling code from scratch, without the built-in retries or persistent memory primitives provided by established frameworks.

---

### 3. In-process MCP Calls vs Real Subprocess/stdio Transport
- **Decision:** Call FastMCP tool functions directly in-process from Python.
- **Alternatives Considered:** Running the MCP server in a separate subprocess communicating via standard input/output (stdio transport) with a client.
- **Why Chosen:** The tools (`get_diff`, `read_file`, `list_files`) are defined using FastMCP's `@mcp.tool()` decorator, but called directly as regular Python functions by the agent loop. This was a deliberate simplification to reduce moving parts and eliminate transport debugging surface under time pressure. The tools remain structured as standard MCP tools (decorated, schema-generating, docstring-driven) and can be wired to a real MCP client with minimal changes.
- **Known Limitation:** The actual MCP protocol layer (transport handling and serialization over stdio) was never exercised end-to-end.

---

### 4. Sandboxing Approach
- **Decision:** Enforce repository boundaries using a required `ALLOWED_REPO_ROOT` environment variable, `pathlib.Path.resolve()`, and `.parents` validation, running all git commands via argument lists.
- **Alternatives Considered:** Defaulting silently to the current directory; naive string-prefix path checks (`str.startswith`); running git commands via shell strings (`shell=True`).
- **Why Chosen:**
  - `ALLOWED_REPO_ROOT` is strictly required; the server refuses to initialize if it is not set, failing loudly rather than defaulting silently to an insecure fallback.
  - Path validation resolves all paths to their canonical form using `pathlib.Path.resolve()` and checks that `allowed_root in resolved.parents` or `resolved == allowed_root`. A naive string-prefix check would incorrectly allow access to sibling directories with matching prefixes (for instance, `/home/user/code-evil` passing against `/home/user/code`) and would fail to properly neutralize `..` path traversals.
  - Git commands are executed via `subprocess.run(["git", *args])` with argument lists (never `shell=True` or formatted shell strings), preventing shell injection through ref names or file paths passed as tool inputs.

---

### 5. Two-call Split: Investigation vs Extraction
- **Decision:** Separate the review into two distinct Ollama calls: an open-ended investigation call followed by a structured extraction call.
- **Alternatives Considered:** A single model call where the model both investigated the diff (using tools) and formatted the final findings into a strict text template.
- **Why Chosen:** When instructed in a single pass to investigate and output a structured per-finding template, the model (`qwen2.5-coder:7b`) consistently produced a plain-English narrative summary of the diff rather than an evaluative critique, regardless of how directive the system prompt was made. Splitting into two calls resolved this:
  1. **Call 1 (Investigation):** Investigates the diff using tools and generates an unconstrained, free-form code review.
  2. **Call 2 (Extraction):** Takes the free-form review text and extracts concrete findings into strict JSON using Ollama's `format="json"` constrained decoding. Constrained decoding enforces schema compliance at the decoding level, which is far more reliable than expecting a small model to follow text formatting rules from prompt instructions alone.

---

### 6. Malformed Tool-call Handling
- **Decision:** Implement hybrid tool-call extraction (`try_parse_tool_call`) with fallback content parsing and a single repair attempt.
- **Alternatives Considered:** Strictly expecting the standard `tool_calls` response field and failing if absent.
- **Why Chosen:** Direct testing showed that the model (`qwen2.5-coder:7b`) occasionally emits valid tool-call JSON directly inside the text `content` field rather than populating Ollama's formal `tool_calls` structure. The agent loop checks the formal `tool_calls` field first, but falls back to parsing `content` for JSON objects with `"name"` and `"arguments"` keys. If a response contains neither a valid tool call nor usable review content, the loop issues a single repair prompt reminding the model of the expected format; if that also fails, it terminates with an explicit error rather than looping indefinitely.

---

### 7. Iteration Limits
- **Decision:** Cap the main agent loop at `max_iterations = 8`.
- **Alternatives Considered:** Dynamic token-budget caps or unbounded execution.
- **Why Chosen:** A fixed iteration cap prevents infinite tool-calling loops while providing sufficient turns for inspecting diffs and reading related files.
- **Known Limitation:** No token-count cap was implemented (cut for time). While the model's 32K context window was never close to being exhausted during testing given the small number of tool calls needed, token exhaustion remains an unaddressed risk for large diffs.

---

### 8. Eval Harness Matching Rule
- **Decision:** Match findings to ground truth using normalized repo-relative file paths and line proximity within ±3 lines.
- **Alternatives Considered:** Automated semantic category matching (e.g., verifying whether the model labeled a bug "off-by-one" vs "missing null check").
- **Why Chosen:** Extracted findings from the model often returned absolute paths (e.g., `/home/.../src/x.ts`), requiring normalization against the repo root before comparison. Category matching was deliberately not automated to keep the matching logic deterministic and minimize moving parts under time constraints; category correctness was verified manually instead.

---

### 9. Known Limitation of the Matching Rule, Demonstrated Concretely
- **Case Study:** During manual testing before building the automated harness, one injected bug (a flipped comparison operator in `src/services/otpService.ts`, where `===` was changed to `!==`) was located accurately by file and line by the model. However, the model's reasoning was internally contradictory, and its suggested fix was to change the comparison operator to `!==`—which was the buggy code that was already present (a no-op that does not fix the bug).
- **Limitation:** The automated matching rule (file equality + line proximity within ±3) cannot detect this issue: it marks the finding as a true positive despite the diagnosis and suggested fix being incorrect. This is an inherent limitation of location-based evaluation heuristics.

---

### 10. Eval Sample Size
- **Decision:** Evaluate against 3 manually-injected bugs across 3 distinct bug categories in a real production codebase.
- **Alternatives Considered:** A synthetic sample repository with 15–20 seeded bugs.
- **Why Chosen:** Building a 15–20 bug seeded testbed was cut due to the 3-day deadline. Testing against 3 surgical bugs in an actual production repository (`P-T_backend_ts`) still exercised the complete evaluation pipeline (precision, recall, false positive tracking, run-to-run variance measurement, markdown reporting) and delivered a verified result: 100% recall, 75% precision, 1 false positive, consistent across 3 runs.

---

### 11. Observed Run-to-Run Consistency, and Its Likely Cause
- **Finding:** All 3 evaluation runs produced identical recall (1.00) and precision (0.75).
- **Analysis:** This consistency likely stems from Ollama's default sampling configuration (which defaults to low or zero temperature when no explicit options are passed) rather than inherent model determinism. No explicit `"options": {"temperature": ...}` override was passed in the chat payload. Measuring true run-to-run variance requires testing with temperature explicitly set to a realistic non-zero value (e.g., 0.7); omitting this is a documented gap.

---

### 12. 7B Model Limitations Observed Directly
These behaviors were directly observed during testing, rather than assumed:
1. **Summarization Bias:** Without the two-call split, the model consistently summarized code changes rather than evaluating them for bugs, even when given strict negative prompt instructions across multiple rewrites.
2. **Schema Inconsistency:** The model occasionally serialized tool calls as raw JSON in `content` rather than using the native `tool_calls` message field.
3. **Superficial Reasoning:** The model can accurately locate a bug by file and line yet produce contradictory reasoning and suggest a no-op fix (as observed in `otpService.ts`).
4. **Fixture False Positives:** The model reviewed a non-application test fixture (`eval/ground_truth_manual_test.json`, which was committed in the test branch) as if it were production application code, generating a false positive. This highlights the need for path-filtering rules to exclude non-source files from review.

---

### 13. With More Time
Follow-up features and improvements identified for future iterations:
- **Codebase RAG:** Implement vector search over the codebase (using Qdrant and embeddings) to supply relevant dependency and caller context beyond the immediate git diff.
- **Real MCP Transport:** Transition from in-process function calls to a true MCP client communicating over stdio with an external MCP server subprocess.
- **Expanded Evaluation Benchmark:** Expand the evaluation suite to a 15–20 seeded-bug repository with automated semantic and category verification.
- **Configurable Sampling & Variance Testing:** Expose temperature and top-p parameters to systematically measure variance across non-deterministic runs.
- **CLI Interface:** Add a proper CLI using `typer` with flags for repository path, base ref, head ref, and output format.
- **Service Layer & Containerization:** Package the agent behind a FastAPI service endpoint and containerize with Docker/Podman.
- **Observability:** Integrate Langfuse for LLM call tracing, latency monitoring, and token tracking.
- **Framework Comparison:** Build an equivalent workflow in LangGraph to benchmark latency, token overhead, and code ergonomics against the hand-written loop.
