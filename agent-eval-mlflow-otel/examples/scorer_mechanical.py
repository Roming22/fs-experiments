"""Mechanical scorers — pure Python, no LLM cost.

These scorers receive MLflow Trace objects and return Feedback with a numeric
value and rationale string. They check structural properties of agent traces.

Usage:
    from scorer_mechanical import MECHANICAL_SCORERS
    import mlflow
    mlflow.genai.evaluate(data=traces_df, scorers=MECHANICAL_SCORERS)
"""
import json

from mlflow.genai.scorers import scorer
from mlflow.entities import Feedback


@scorer
def validation_passed(*, trace) -> Feedback:
    """Did the agent output pass schema validation?"""
    spans = trace.search_spans(name="fullsend:results")
    passed = bool(spans and spans[0].get_attribute("result.validation") == "passed")
    return Feedback(
        value=1.0 if passed else 0.0,
        rationale="passed" if passed else "failed or no results span",
    )


@scorer
def tool_efficiency(*, trace) -> Feedback:
    """Ratio of reasoning turns to total actions.

    Ideal range: 0.15-0.40 reasoning-to-total ratio.
    Too high = overthinking. Too low = acting without reasoning.
    """
    agent_span = _find_agent_span(trace)
    if not agent_span:
        return Feedback(value=0.5, rationale="No agent span found")

    tools = int(agent_span.get_attribute("tool_call_count") or 0)
    reasoning = int(agent_span.get_attribute("reasoning_turn_count") or 0)
    total = tools + reasoning
    if total == 0:
        return Feedback(value=0.0, rationale="No tool calls or reasoning turns")

    ratio = reasoning / total
    score = 1.0 if 0.15 <= ratio <= 0.40 else max(0.0, 1.0 - abs(ratio - 0.275) * 3)
    return Feedback(
        value=round(score, 2),
        rationale=f"{reasoning} reasoning / {tools} tools (ratio={ratio:.2f})",
    )


@scorer
def cost_within_budget(*, trace) -> Feedback:
    """Is the run cost within acceptable bounds?

    Budget thresholds per agent type. Reads from harness YAML gates.max_cost
    or falls back to defaults below.
    """
    tags = trace.info.tags or {}
    agent = tags.get("fullsend.agent", "")
    budgets = {"explore": 2.0, "refine": 3.0, "critique": 1.5, "triage": 2.0, "code": 5.0}
    budget = budgets.get(agent, 3.0)

    cost = trace.info.cost or {}
    total = float(cost.get("total_cost", 0))

    within = total <= budget
    return Feedback(
        value=1.0 if within else 0.0,
        rationale=f"${total:.2f} vs ${budget:.2f} budget ({agent})",
    )


@scorer
def confidence_coherence(*, trace) -> Feedback:
    """Are confidence dimensions internally coherent?

    Checks: values in 0-100, not all identical, spread not extreme (>60),
    and overall score roughly matches the mean of dimensions.
    """
    agent_span = _find_agent_span(trace)
    if not agent_span:
        return Feedback(value=1.0, rationale="No agent span (non-confidence agent)")

    dims = {}
    for k, v in agent_span.attributes.items():
        if k.startswith("confidence.") and k != "confidence.overall":
            try:
                dims[k.replace("confidence.", "")] = int(v)
            except (ValueError, TypeError):
                pass

    overall = agent_span.get_attribute("confidence.overall")
    if not dims:
        return Feedback(value=1.0, rationale="No confidence dimensions found")

    issues = []
    values = list(dims.values())

    for name, val in dims.items():
        if val < 0 or val > 100:
            issues.append(f"{name}={val} out of range")

    if len(set(values)) == 1 and len(values) > 2:
        issues.append(f"All dimensions identical ({values[0]})")

    spread = max(values) - min(values)
    if spread > 60:
        issues.append(f"Extreme spread: {spread}")

    if overall is not None:
        mean_dims = sum(values) / len(values)
        try:
            overall_int = int(overall)
            if abs(overall_int - mean_dims) > 15:
                issues.append(f"Overall ({overall_int}) deviates from mean ({mean_dims:.0f})")
        except (ValueError, TypeError):
            pass

    if issues:
        return Feedback(value=0.0, rationale="; ".join(issues))
    return Feedback(
        value=1.0,
        rationale=f"All {len(dims)} dims valid, range {min(values)}-{max(values)}, overall={overall}",
    )


@scorer
def iteration_count(*, trace) -> Feedback:
    """How many agent execution iterations were needed?

    Most tasks should complete in 1 iteration. Multiple iterations
    may indicate the agent is struggling or the task is too complex.
    """
    iteration_spans = [
        s for s in trace.data.spans
        if s.name.startswith("agent-execution.iteration-")
    ]
    return Feedback(
        value=len(iteration_spans),
        rationale=f"{len(iteration_spans)} iteration(s)",
    )


MECHANICAL_SCORERS = [
    validation_passed,
    tool_efficiency,
    cost_within_budget,
    confidence_coherence,
    iteration_count,
]


def _find_agent_span(trace):
    """Find the main agent span (e.g., 'explore-agent', 'triage-agent')."""
    tags = trace.info.tags or {}
    agent = tags.get("fullsend.agent", "")
    if not agent:
        return None
    spans = trace.search_spans(name=f"{agent}-agent")
    return spans[0] if spans else None
