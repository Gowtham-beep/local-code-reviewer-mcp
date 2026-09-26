import json
import httpx

from code_reviewer.mcp_server import get_diff, list_files, read_file

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "qwen2.5-coder:7b"

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_diff",
            "description": "Get the diff between two git refs in a repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Absolute path to the git repository.",
                    },
                    "base": {
                        "type": "string",
                        "description": "The git ref to diff from, e.g. 'main'.",
                    },
                    "head": {
                        "type": "string",
                        "description": "The git ref to diff to, e.g. 'feature/xyz'.",
                    },
                },
                "required": ["repo_path", "base", "head"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file content from a repository, optionally sliced by line range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Absolute path to the git repository.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file relative to repo_path (e.g. 'src/app.ts').",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Optional 1-indexed starting line number (inclusive).",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Optional 1-indexed ending line number (inclusive).",
                    },
                },
                "required": ["repo_path", "file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List tracked files in a git repository respecting .gitignore, optionally matching a glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Absolute path to the git repository.",
                    },
                    "glob": {
                        "type": "string",
                        "description": "Optional glob/pathspec pattern to filter files (e.g. '*.py', 'src/**').",
                    },
                },
                "required": ["repo_path"],
            },
        },
    },
]


def ollama_chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """Send a chat request to Ollama and return the assistant's response message.

    Returns the raw "message" dict from Ollama's response, which is either:
      - {"role": "assistant", "content": "..."}                (final answer)
      - {"role": "assistant", "content": "", "tool_calls": [...]} (wants a tool)
    """
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools

    response = httpx.post(OLLAMA_URL, json=payload, timeout=120.0)
    response.raise_for_status()
    data = response.json()
    return data["message"]


def try_parse_tool_call(message: dict) -> dict | None:
    """Detect a tool call, whether Ollama used the proper tool_calls field
    or the model wrote it as raw JSON text in content (a known failure mode).

    Returns a normalized dict {"name": str, "arguments": dict} or None.
    """
    if message.get("tool_calls"):
        call = message["tool_calls"][0]["function"]
        return {"name": call["name"], "arguments": call["arguments"]}

    content = message.get("content", "").strip()
    if content.startswith("{"):
        try:
            parsed = json.loads(content)
            if "name" in parsed and "arguments" in parsed:
                return {"name": parsed["name"], "arguments": parsed["arguments"]}
        except json.JSONDecodeError:
            pass

    return None


def execute_tool(name: str, arguments: dict) -> dict:
    """Execute a tool by name with arguments, returning the result or an error dict."""
    tools_map = {
        "get_diff": get_diff,
        "read_file": read_file,
        "list_files": list_files,
    }
    if name not in tools_map:
        return {"error": f"Unknown tool: {name}"}

    try:
        return tools_map[name](**arguments)
    except Exception as exc:
        return {"error": str(exc)}


def run_review(repo_path: str, base: str, head: str, max_iterations: int = 8) -> str:
    """Run the agent loop to review a diff. Returns the final review text."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert code reviewer looking for actual problems in a code change: bugs, security vulnerabilities, error-handling gaps, race conditions, and code quality issues that could cause real harm in production.\n\n"
                "Use the available tools (get_diff, read_file, list_files) to inspect the diff and read surrounding code context before giving your final review. Reading the files that call or depend on changed code is often necessary to catch real bugs.\n\n"
                "You MUST report every concrete issue you find. Do not summarize what the code does — evaluate it. If you find no genuine issues after careful review, say so explicitly rather than describing the changes.\n\n"
                "For EACH issue found, output it in exactly this format:\n"
                "FILE: <path>\n"
                "LINE: <line number or range>\n"
                "SEVERITY: <error|warn|info>\n"
                "ISSUE: <what is wrong, specifically>\n"
                "SUGGESTION: <concrete fix>\n"
                "---\n\n"
                "Do not call tools once you are ready to present your final review; output your final review as plain text in the format above."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Please review the changes in the repository at '{repo_path}' between base ref '{base}' and head ref '{head}'.\n"
                f"The tool 'get_diff' is available to fetch the diff between these refs."
            ),
        },
    ]

    has_repaired = False

    for iteration in range(1, max_iterations + 1):
        print(f"Iteration {iteration}: sending request to model...")
        assistant_message = ollama_chat(messages, tools=TOOL_SCHEMAS)
        messages.append(assistant_message)

        tool_call = try_parse_tool_call(assistant_message)
        if tool_call is not None:
            name = tool_call["name"]
            arguments = tool_call["arguments"]
            print(f"Iteration {iteration}: model called tool '{name}' with arguments {arguments}")
            result = execute_tool(name, arguments)
            messages.append({"role": "tool", "content": json.dumps(result)})
            continue

        # No tool call detected
        content = assistant_message.get("content", "").strip()
        if content:
            print(f"Iteration {iteration}: final review received")
            return content

        # Genuinely empty / malformed response
        print(f"Iteration {iteration}: received empty/malformed response from model")
        if not has_repaired:
            has_repaired = True
            messages.append({
                "role": "user",
                "content": "Your last response was invalid or empty. Please retry using the correct tool-calling format or provide your final review.",
            })
            continue

        return "Error: Model failed to produce a usable response after repair attempt."

    return f"Review did not complete within the limit of {max_iterations} iterations."


if __name__ == "__main__":
    review = run_review(
        repo_path="/home/gpuserver1/P-T_backend_ts",
        base="e833a34",
        head="04d72ec",
    )
    print("\n=== FINAL REVIEW ===\n")
    print(review)