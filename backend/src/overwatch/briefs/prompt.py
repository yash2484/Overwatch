"""Prompt builder for LLM-generated intelligence briefs (Phase 4, Task 6; Phase 5, Task 9).

Pure string building: no LLM calls, no network, no DB. Renders a `BriefRequest`
(AOI, before/after scene pair, aggregate stats, detection rows) into the Anthropic
`messages` list. Detection rows are capped at `settings.brief_max_prompt_detections`
to bound prompt size — only the largest-by-area rows are serialized, but the
aggregate-stats block always reports totals over the FULL detection set so the
model (and a human reader) never sees an undercount. On retry, each prior
`AttemptFailure` is replayed as an assistant turn (the rejected draft's JSON)
followed by a user turn listing the violations to fix.

Phase 5 adds the SOURCES block — news articles that survived the three gates, rendered
with the ids the model must cite them by, and capped at `settings.fusion_max_prompt_articles`.
It carries the rules of the observed/reported wall (design §6), which the validator's
Gate 4 then enforces: a claim backed only by journalism is REPORTED SPEECH, framed as
such, carrying no figures. The prompt must state every rule the validator checks — the
alternative is a model steered into a rejection it was never told how to avoid.
"""

import logging

from overwatch.briefs.models import ArticleRow, AttemptFailure, BriefRequest, DetectionRow
from overwatch.config import settings

logger = logging.getLogger("overwatch.briefs.prompt")

SYSTEM_PROMPT = """You are an imagery analyst writing an intelligence brief about \
satellite-detected change in one area of interest, comparing a BEFORE scene and an AFTER \
scene.

Rules you must follow exactly:
- Every claim of type "observed" must cite the detection ids that support it in its \
evidence list, and any quantity you state must come from those detections' recorded \
values (areas in m²; dates are the two capture dates provided).
- Claims of type "context" give background only and must contain no numbers, \
percentages, areas, or dates.
- The four claim types are "observed", "context", "reported", and "mixed". The last two \
cite news articles, so they are available ONLY when a SOURCES section appears in the \
message below; with no SOURCES section, use "observed" or "context".
- Journalism is not sensing. A claim backed only by news articles is reported speech: it \
never claims to have been seen, and it never carries a measured figure. Only detections \
carry figures.
- Never invent detections, quantities, or dates. If the data does not support a \
statement, do not make it.
- Write 3-8 claims, ordered for reading: headline finding first, context last."""


def _detection_line(row: DetectionRow) -> str:
    return (
        f"id={row.id} type={row.change_type} area_m2={row.area_m2:.0f} "
        f"magnitude={row.magnitude:.3f} confidence={row.confidence:.2f}"
    )


def _stats_block(detections: list[DetectionRow]) -> str:
    total_count = len(detections)
    total_area = sum(d.area_m2 for d in detections)
    counts_by_type: dict[str, int] = {}
    for d in detections:
        counts_by_type[d.change_type] = counts_by_type.get(d.change_type, 0) + 1
    by_type = ", ".join(f"{ct}={n}" for ct, n in sorted(counts_by_type.items()))
    return (
        "AGGREGATE STATS:\n"
        f"- {total_count} detections, total area {total_area:.0f} m^2\n"
        f"- by change type: {by_type}"
    )


def _select_for_prompt(detections: list[DetectionRow]) -> list[DetectionRow]:
    """Return detections sorted largest-first, capped at the configured prompt limit."""
    ranked = sorted(detections, key=lambda d: d.area_m2, reverse=True)
    cap = settings.brief_max_prompt_detections
    if len(ranked) > cap:
        logger.warning(
            "Truncating detections for prompt: %d total, serializing largest %d (cap=%d)",
            len(ranked),
            cap,
            cap,
        )
        return ranked[:cap]
    return ranked


def _select_articles_for_prompt(articles: list[ArticleRow]) -> list[ArticleRow]:
    """Return articles capped at the configured prompt limit.

    Unlike detections — ranked largest-area-first before the cap bites — articles arrive
    from `articles_for_pair` in chronological order and `news_articles` stores no score,
    so there is nothing to rank on. The cap therefore keeps the EARLIEST N: for a
    deforestation story the coverage clusters at the clearing, which is the start of the
    interval, not the end. Truncation is logged at WARNING for the same reason the
    detection cap is — evidence is being dropped from the model's view.
    """
    cap = settings.fusion_max_prompt_articles
    if len(articles) > cap:
        logger.warning(
            "Truncating articles for prompt: %d total, serializing earliest %d (cap=%d)",
            len(articles),
            cap,
            cap,
        )
        return articles[:cap]
    return articles


def _article_line(row: ArticleRow) -> str:
    return f"  [{row.id}] {row.seendate.isoformat()} {row.domain}: {row.title}"


def _sources_block(articles: list[ArticleRow]) -> str:
    serialized = _select_articles_for_prompt(articles)
    article_lines = "\n".join(_article_line(a) for a in serialized)
    return (
        "\n"
        "\n"
        "SOURCES (news articles — REPORTED, not observed):\n"
        f"{article_lines}\n"
        "\n"
        "RULES FOR SOURCES:\n"
        '  - A claim supported ONLY by articles MUST use claim_type "reported", MUST cite '
        "the article ids that support it in `article_evidence` (never in `evidence`), and "
        'MUST be phrased as reported speech (e.g. "Regional news reports that...").\n'
        '  - Such a claim may NEVER use observational framing ("imagery confirms...", '
        '"detected", "is visible") and may NEVER carry a quantity — no areas, no '
        "percentages, no dates. An article is not a measurement.\n"
        '  - Use "mixed" only for a claim that cites BOTH a detection id and an article id. '
        "A quantity in a mixed claim is licensed by the detection it cites, never by the "
        "article.\n"
        '  - An "observed" claim may not cite article ids at all.'
    )


def _user_message_body(request: BriefRequest) -> str:
    stats = _stats_block(request.detections)
    serialized = _select_for_prompt(request.detections)
    detection_lines = "\n".join(_detection_line(d) for d in serialized)
    body = (
        f"AREA OF INTEREST: {request.aoi_name} "
        f"(slug: {request.aoi_slug}, vertical: {request.vertical})\n"
        "\n"
        "SCENE PAIR:\n"
        f"- before: scene {request.before_scene_id} captured {request.before_date.isoformat()}\n"
        f"- after: scene {request.after_scene_id} captured {request.after_date.isoformat()}\n"
        "\n"
        f"{stats}\n"
        "\n"
        "DETECTIONS (largest first):\n"
        f"{detection_lines}"
    )
    # No articles => no SOURCES section and no source rules. Rules about citing ids that
    # do not exist are an invitation to invent them.
    if request.articles:
        body += _sources_block(request.articles)
    return body


def _feedback_message(failure: AttemptFailure) -> str:
    lines = [
        f"- [{v.code}] claim #{v.claim_seq if v.claim_seq is not None else '-'}: {v.message}"
        for v in failure.violations
    ]
    return (
        "Your previous draft failed validation. Fix ALL violations and return a "
        "corrected brief:\n" + "\n".join(lines)
    )


def build_messages(request: BriefRequest, failures: list[AttemptFailure]) -> list[dict[str, str]]:
    """Build the Anthropic `messages` list for one generation attempt.

    The first message is always the full-context user turn. Each prior
    `AttemptFailure` then contributes an assistant turn (its rejected draft, as
    JSON) followed by a user turn instructing the model to fix the listed
    violations — so a caller retrying after N failures gets 1 + 2*N messages.
    """
    messages: list[dict[str, str]] = [{"role": "user", "content": _user_message_body(request)}]
    for failure in failures:
        messages.append({"role": "assistant", "content": failure.draft.model_dump_json()})
        messages.append({"role": "user", "content": _feedback_message(failure)})
    return messages
