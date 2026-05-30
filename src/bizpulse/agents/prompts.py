"""PromptBuilder — assemble system + user prompts for every agent role.

The plan's "industry-pack" mechanism lives here. Each role has a base system
prompt with a role description, the citation contract ("every claim cites a
chunk_id"), and the output schema name. If an `IndustryPack` is supplied, the
pack's `prompt_addendum` is injected verbatim, and the ontology entities,
regulations, content pillars, and competitor seeds are listed for the model
to ground its analysis in.

Context chunks are presented with stable IDs that the model is expected to
reference back in its output (`evidence_chunk_ids`). The Critic agent then
verifies every cited ID actually appears in the context window.

This module is pure-Python (no LLM calls). It's imported by Phase-6 LangGraph
nodes and by the MCP server's `query_business_knowledge` tool.
"""

from __future__ import annotations

from textwrap import dedent

from bizpulse.models.agents import AgentName
from bizpulse.models.industry import IndustryPack
from bizpulse.models.retrieval import RetrievedChunk

# --- per-agent system prompts -----------------------------------------------
# Each prompt is intentionally terse. The plan rewards prompts that read like
# specs, not pep talks: state the role, the output contract, the rules. The
# model knows how to write English; we don't need to remind it.

_BASE_RULES = dedent("""
    Output rules (non-negotiable):
    - Reply ONLY with valid JSON matching the schema specified in the user
      message. No prose preamble, no trailing commentary.
    - Every analytical statement (positioning, finding, recommendation, etc.)
      MUST cite the chunk_id(s) it is grounded in via `citations` or
      `evidence_chunk_ids`. Statements without citations will be rejected by
      the Critic agent.
    - If the supplied context does not let you answer a field, set it to an
      empty list / null and lower your `confidence` score — DO NOT fabricate.
    - Never invent companies, URLs, regulations, or numbers that aren't in the
      context. The Competitor Scout verifies competitors via web search; if
      you can't, omit the entry.
    """).strip()

_AGENT_ROLES: dict[AgentName, str] = {
    "orchestrator": "You orchestrate a multi-agent marketing-strategy pipeline. Your job is to plan which sub-agents to call and in what order, given the input and currently available context.",
    "industry_classifier": "You classify a business into one of the supported industry verticals based on its website content.",
    "brand_analyst": "You extract brand positioning, tone, and value propositions from a company's website content.",
    "audience_analyst": "You infer the ideal customer profile (ICP) — demographics, motivations, pain points — from website copy, testimonials, and case studies.",
    "competitor_scout": "You identify 3-5 competitors. For each, return name, url, positioning, and verified=true ONLY if the competitor was confirmed via independent search. Do not fabricate competitors.",
    "content_auditor": "You audit a business's marketing content. Identify which content pillars are strong, which are weak, and surface specific findings backed by evidence.",
    "strategist": "You synthesize prior agent outputs into a final marketing strategy with prioritized, channel-specific recommendations. Each recommendation MUST cite the chunk_ids that support it.",
    "critic": "You re-read the Strategist's output and verify every analytical claim is supported by a real chunk in the context. Flag ungrounded claims, fabricated competitors, or schema violations. Return either a clean output or a list of issues for retry.",
    "compliance_checker": "You score a MarketingStrategy against jurisdiction-specific regulations (RBI, SEBI, IRDAI, RERA, DPDP, ASCI, GDPR, etc.). For each Recommendation, raise a ComplianceFlag when it triggers a policy's prohibition or misses a required disclosure. Compute the 4 L's metric: Latest (recent regulations honored), Least (least penalty exposure), Lost (lost-revenue avoided), Lowest (lowest cost of compliance).",
    "audience_simulator": "You simulate an audience's reaction to a proposed marketing campaign. Spawn N personas matching the ICP and report aggregate sentiment, common objections, and red flags.",
    "project_tracker": "You track domain-specific entities and metric movements/trends based on website context.",
    "policy_tracker": "You track industry-specific policy, interest rate, and regulatory updates affecting the domain.",
    "research_synthesizer": "You synthesize gathered market news and regulatory changes into a short, plain-language, non-technical daily summary.",
    "academic_tracker": "You track the latest academic research, technical breakthroughs, or scientific innovations applicable to the industry.",
    "policy_analyst": "You monitor and identify regulatory updates, policy shifts, tax reforms, budget allocations, subsidies, geo-political/trade updates, or interest-rate changes.",
    "market_scout": "You identify and track strategic corporate developments, including mergers and acquisitions (M&A), funding rounds, major partnerships, investments, joint ventures, or market expansions.",
    "environmental_monitor": "You identify environment, climate, weather, or sustainability threats and opportunities affecting this sector.",
    "competitive_intelligence": "You identify competitor moves, pricing shifts, new product launches, and client sentiment.",
    "radar": "You identify top miscellaneous but critical anomalies, adjacent trends, or local events.",
}



# --- builder ---------------------------------------------------------------


class PromptBuilder:
    """Build (system, user) prompt pairs for any agent role.

    Stateless except for the optional industry pack. Cheap to construct;
    construct one per request to keep things explicit.
    """

    def __init__(self, industry_pack: IndustryPack | None = None) -> None:
        self.industry_pack = industry_pack

    def system_prompt(self, agent: AgentName) -> str:
        if agent not in _AGENT_ROLES:
            raise ValueError(f"unknown agent: {agent}")
        parts = [_AGENT_ROLES[agent], "", _BASE_RULES]
        if self.industry_pack is not None:
            parts.append("")
            parts.append(self._industry_block())
        return "\n".join(parts).strip()

    def user_prompt(
        self,
        task: str,
        context_chunks: list[RetrievedChunk],
        output_schema_name: str,
        output_schema_json: str | None = None,
        few_shot_examples: list[dict] | None = None,
    ) -> str:
        """User-side prompt. Presents the task, context, and schema.

        If `output_schema_json` is supplied, it is included verbatim as a
        fenced JSON-Schema block — drastically reduces field-name drift on
        models that haven't been fine-tuned to BizPulse types.
        """
        parts: list[str] = [f"Task: {task}", ""]
        if output_schema_json:
            parts.append(
                f"Reply with ONLY a JSON object matching this exact schema "
                f"({output_schema_name}). No prose, no code fences, no extra "
                f"fields:\n```json\n{output_schema_json}\n```"
            )
        else:
            parts.append(
                f"Output schema: `{output_schema_name}`. Reply with a JSON object matching it."
            )
        if few_shot_examples:
            import json as json_lib

            parts.append("")
            parts.append("Below are examples of approved, high-quality outputs for similar tasks:")
            for idx, ex in enumerate(few_shot_examples):
                parts.append(f"Example {idx + 1}:\n```json\n{json_lib.dumps(ex, indent=2)}\n```")
        parts.append("")
        parts.append("Retrieved context (cite chunk_ids in your output):")
        if not context_chunks:
            parts.append("(no context retrieved — answer with empty fields and confidence=0.0)")
        else:
            for rc in context_chunks:
                meta = rc.chunk.metadata
                section = f", section={meta.section}" if meta.section else ""
                parts.append("")
                parts.append(
                    f"[chunk:{rc.chunk.id}] (source={meta.source_url}, type={meta.source_type}{section}, score={rc.score:.3f})"
                )
                parts.append(rc.chunk.text.strip())
        return "\n".join(parts)

    def build(
        self,
        agent: AgentName,
        task: str,
        context_chunks: list[RetrievedChunk],
        output_schema_name: str,
        output_schema_json: str | None = None,
        few_shot_examples: list[dict] | None = None,
    ) -> tuple[str, str]:
        return (
            self.system_prompt(agent),
            self.user_prompt(
                task, context_chunks, output_schema_name, output_schema_json, few_shot_examples
            ),
        )

    # ---------- internals -------------------------------------------------

    def _industry_block(self) -> str:
        p = self.industry_pack
        assert p is not None  # guarded by caller
        lines = [
            f"Industry vertical: **{p.name}** ({p.slug})",
            f"Description: {p.description}",
            "",
            "Key entities you should look for: " + ", ".join(p.ontology.entities),
        ]
        if p.ontology.regulations:
            lines.append("Relevant regulations: " + ", ".join(p.ontology.regulations))
        if p.ontology.metrics:
            lines.append("Industry metrics that matter: " + ", ".join(p.ontology.metrics))
        if p.content_pillars:
            lines.append("Content pillars to evaluate: " + ", ".join(p.content_pillars))
        if p.competitor_seeds:
            lines.append(
                "Known competitors in this vertical (verify before citing): "
                + ", ".join(p.competitor_seeds[:8])
            )
        if p.prompt_addendum:
            lines.append("")
            lines.append("Industry-specific guardrails:")
            lines.append(p.prompt_addendum.strip())
        return "\n".join(lines)
