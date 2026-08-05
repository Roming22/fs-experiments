#!/usr/bin/env python3
"""PreToolUse hook: intercepts Agent() calls, spawns isolated claude process,
feeds the result back through the subagent as a pass-through echo."""

import json
import os
import signal
import shutil
import subprocess
import sys
import time


def _save_spawned_cost(pid, result_json, start_ns, end_ns):
    """Write spawned process cost data to FULLSEND_OUTPUT_DIR for post_script."""
    output_dir = os.environ.get("FULLSEND_OUTPUT_DIR")
    if not output_dir:
        print(f"[intercept] pid={pid} WARNING: FULLSEND_OUTPUT_DIR not set, skipping cost save", file=sys.stderr)
        return

    usage = result_json.get("usage", {})
    model_usage = result_json.get("modelUsage", {})
    model = next(iter(model_usage), "") if model_usage else ""

    cost_data = {
        "total_cost_usd": result_json.get("total_cost_usd", 0),
        "session_id": result_json.get("session_id", ""),
        "num_turns": result_json.get("num_turns", 0),
        "duration_ms": result_json.get("duration_ms", 0),
        "model": model,
        "start_time_unix_nano": str(start_ns),
        "end_time_unix_nano": str(end_ns),
        "usage": {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        },
    }

    cost_path = os.path.join(output_dir, ".spawned-cost.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(cost_path, "w") as f:
        json.dump(cost_data, f, indent=2)
    print(f"[intercept] pid={pid} saved cost data to {cost_path}: ${cost_data['total_cost_usd']:.4f}", file=sys.stderr)


def main():
    if not os.path.isdir("/sandbox/workspace"):
        print("[intercept] refusing to run outside sandbox", file=sys.stderr)
        return

    if os.environ.get("FULLSEND_HOOK_SPAWNED"):
        print("[intercept] skipping: spawned subprocess", file=sys.stderr)
        return

    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        print("[intercept] skipping: malformed or empty stdin", file=sys.stderr)
        return
    tool_name = hook_input.get("tool_name", "")

    if tool_name != "Agent":
        print(f"[intercept] skipping: tool={tool_name}", file=sys.stderr)
        return

    tool_input = hook_input.get("tool_input", {})
    original_prompt = tool_input.get("prompt", "")

    if not original_prompt:
        print("[intercept] skipping: empty prompt", file=sys.stderr)
        return

    claude_bin = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"
    pid = os.getpid()

    print(f"[intercept] pid={pid} Intercepting Agent call, spawning isolated process...", file=sys.stderr)
    print(f"[intercept] pid={pid} claude_bin={claude_bin}", file=sys.stderr)
    print(f"[intercept] pid={pid} original_prompt={original_prompt[:120]}", file=sys.stderr)

    env = os.environ.copy()
    env["FULLSEND_HOOK_SPAWNED"] = "1"

    start_ns = int(time.time() * 1e9)

    try:
        proc = subprocess.Popen(
            [claude_bin, "-p", "--output-format", "json", "--dangerously-skip-permissions"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(input=original_prompt, timeout=270)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            proc.wait()
            agent_output = "ERROR: claude process timed out after 270s"
            print(f"[intercept] pid={pid} TIMEOUT — killed process group {proc.pid}", file=sys.stderr)
        else:
            end_ns = int(time.time() * 1e9)
            print(f"[intercept] pid={pid} spawned_process_returncode={proc.returncode}", file=sys.stderr)

            try:
                result_json = json.loads(stdout)
                agent_output = result_json.get("result", "").strip()
                _save_spawned_cost(pid, result_json, start_ns, end_ns)
            except (json.JSONDecodeError, ValueError):
                agent_output = stdout.strip()
                print(f"[intercept] pid={pid} WARNING: could not parse JSON output, using raw text", file=sys.stderr)

            print(f"[intercept] pid={pid} result_length={len(agent_output)} chars", file=sys.stderr)

            if proc.returncode != 0 and not agent_output:
                agent_output = f"Process exited {proc.returncode}. stderr: {stderr[:500]}"
    except OSError as e:
        agent_output = f"ERROR: could not start claude CLI at {claude_bin}: {e}"
        print(f"[intercept] pid={pid} SUBPROCESS_ERROR at {claude_bin}: {e}", file=sys.stderr)

    updated_input = dict(tool_input)
    updated_input["prompt"] = (
        "An external process has already completed this task. "
        "Return the following result exactly as-is, with no additions, "
        "modifications, or commentary:\n\n"
        f"{agent_output}"
    )

    response = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": updated_input,
        },
    }
    json.dump(response, sys.stdout)


if __name__ == "__main__":
    main()
