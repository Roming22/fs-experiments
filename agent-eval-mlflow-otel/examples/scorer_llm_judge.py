"""LLM-as-judge scorers — semantic quality evaluation via Anthropic Vertex AI.

Each scorer calls Claude Opus to evaluate a specific quality dimension of
an agent trace. Scores are returned as Feedback objects (value + rationale)
that MLflow logs to the Quality Dashboard.

Usage:
    from scorer_llm_judge import EXPLORE_SCORERS
    import mlflow
    mlflow.genai.evaluate(data=traces_df, scorers=EXPLORE_SCORERS)

Env:
    FULLSEND_JUDGE_MODEL   — Model name (default: claude-opus-4-6)
    VERTEXAI_PROJECT       — GCP project with Vertex AI API enabled
    VERTEXAI_LOCATION      — Region (default: us-east5)
"""
import json
import os

from anthropic import AnthropicVertex
from mlflow.genai.scorers import scorer
from mlflow.entities import Feedback

JUDGE_MODEL = os.environ.get("FULLSEND_JUDGE_MODEL", "claude-opus-4-6")
VERTEX_PROJECT = os.environ.get("VERTEXAI_PROJECT", "")
VERTEX_REGION = os.environ.get("VERTEXAI_LOCATION", "us-east5")

_vertex_client = None


def _get_vertex_client() -> AnthropicVertex:
    global _vertex_client
    if _vertex_client is None:
        _vertex_client = AnthropicVertex(
            project_id=VERTEX_PROJECT,
            region=VERTEX_REGION,
        )
    return _vertex_client


def _llm_judge(prompt: str) -> dict:
    """Call the judge LLM and parse a JSON response."""
    client = _get_vertex_client()
    response = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    content = response.content[0].text.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    return json.loads(content)


def _get_trace_summary(trace, max_reasoning_chars: int = 1500) -> str:
    """Build a text summary of a trace for LLM judge context."""
    tags = trace.info.tags or {}
    agent = tags.get("fullsend.agent", "unknown")
    work_item = tags.get("fullsend.work_item_id", "unknown")
    cost = trace.info.cost or {}

    reasoning_texts = []
    for s in trace.data.spans:
        if s.name.startswith("reasoning-"):
            text = s.get_attribute("output.value")
            if text:
                reasoning_texts.append(text)

    agent_span = None
    target = f"{agent}-agent"
    spans = trace.search_spans(name=target)
    if spans:
        agent_span = spans[0]

    confidence = agent_span.get_attribute("confidence.overall") if agent_span else "N/A"
    tools_count = agent_span.get_attribute("tool_call_count") if agent_span else "N/A"

    return (
        f"Agent: {agent}\n"
        f"Work item: {work_item}\n"
        f"Confidence: {confidence}/100\n"
        f"Tool calls: {tools_count}\n"
        f"Cost: ${cost.get('total_cost', 0):.2f}\n"
        f"Reasoning: {' | '.join(reasoning_texts)[:max_reasoning_chars]}"
    )


@scorer
def explore_context_quality(*, trace) -> Feedback:
    """Is the gathered context relevant, specific, and complete?"""
    summary = _get_trace_summary(trace, max_reasoning_chars=2000)
    result = _llm_judge(
        f"Evaluate this exploration agent's context gathering (1-5).\n\n"
        f"{summary}\n\n"
        f"Criteria: Looked in the right places? Context specific enough "
        f"for refinement? Identified constraints/risks? Obvious gaps?\n"
        f'Respond in JSON: {{"score": <1-5>, "rationale": "<1-2 sentences>"}}'
    )
    return Feedback(value=result["score"] / 5.0, rationale=result.get("rationale", ""))


@scorer
def reasoning_coherence(*, trace) -> Feedback:
    """Is the agent's reasoning logically coherent and evidence-based?"""
    summary = _get_trace_summary(trace)
    result = _llm_judge(
        f"Evaluate the logical coherence of this AI agent's reasoning (1-5).\n\n"
        f"{summary}\n\n"
        f"1=Contradictory/incoherent, 2=Major gaps, 3=Mostly coherent, "
        f"4=Good with minor issues, 5=Excellent logical flow.\n"
        f'Respond in JSON: {{"score": <1-5>, "rationale": "<1-2 sentences>"}}'
    )
    return Feedback(value=result["score"] / 5.0, rationale=result.get("rationale", ""))


@scorer
def refine_decomposition_quality(*, trace) -> Feedback:
    """Is the feature decomposition complete, well-scoped, and actionable?"""
    summary = _get_trace_summary(trace, max_reasoning_chars=2000)
    result = _llm_judge(
        f"Evaluate this feature refinement agent's decomposition (1-5).\n\n"
        f"{summary}\n\n"
        f"Criteria: (1) Children cover all parent requirements, "
        f"(2) Each child is independently implementable, "
        f"(3) Acceptance criteria are specific/testable, "
        f"(4) Dependencies identified, (5) Right granularity.\n"
        f'Respond in JSON: {{"score": <1-5>, "rationale": "<1-2 sentences>"}}'
    )
    return Feedback(value=result["score"] / 5.0, rationale=result.get("rationale", ""))


@scorer
def critique_verdict_accuracy(*, trace) -> Feedback:
    """Does the critique verdict match the actual quality of the plan?"""
    summary = _get_trace_summary(trace)
    post_critique = trace.search_spans(name="post-critique")
    verdict = "unknown"
    score_val = "?"
    if post_critique:
        verdict = post_critique[0].get_attribute("phase.verdict") or "unknown"
        score_val = post_critique[0].get_attribute("phase.score") or "?"
    result = _llm_judge(
        f"Evaluate this critique agent's verdict accuracy (1-5).\n\n"
        f"{summary}\n"
        f"Verdict: {verdict} (score: {score_val})\n\n"
        f"Does the verdict match the plan quality? Is the critique specific "
        f"and actionable? Does it identify real issues?\n"
        f'Respond in JSON: {{"score": <1-5>, "rationale": "<1-2 sentences>"}}'
    )
    return Feedback(value=result["score"] / 5.0, rationale=result.get("rationale", ""))


EXPLORE_SCORERS = [explore_context_quality, reasoning_coherence]
REFINE_SCORERS = [refine_decomposition_quality, reasoning_coherence]
CRITIQUE_SCORERS = [critique_verdict_accuracy, reasoning_coherence]
