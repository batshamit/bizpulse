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

_BASE_RULES = dedent(
    """
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
    """
).strip()

_AGENT_ROLES: dict[AgentName, str] = {
    "orchestrator": "You orchestrate a multi-agent marketing-strategy pipeline. Your job is to plan which sub-agents to call and in what order, given the input and currently available context.",
    "industry_classifier": "You classify a business into one of the supported industry verticals based on its website content.",
    "brand_analyst": "You extract brand positioning, tone, and value propositions from a company's website content.",
    "audience_analyst": "You infer the ideal customer profile (ICP) — demographics, motivations, pain points — from website copy, testimonials, and case studies.",
    "competitor_scout": "You identify 3-5 competitors. For each, return name, url, positioning, and verified=true ONLY if the competitor was confirmed via independent search. Do not fabricate competitors.",
    "content_auditor": "You audit a business's marketing content. Identify which content pillars are strong, which are weak, and surface specific findings backed by evidence.",
    "strategist": "You synthesize prior agent outputs into a final marketing strategy with prioritized, channel-specific recommendations. Each recommendation MUST cite the chunk_ids that support it.",
    "critic": "You re-read the Strategist's output and verify every analytical claim is supported by a real chunk in the context. Flag ungrounded claims, fabricated competitors, or schema violations. Return either a clean output or a list of issues for retry.",
    "audience_simulator": "You simulate an audience's reaction to a proposed marketing campaign. Spawn N personas matching the ICP and report aggregate sentiment, common objections, and red flags.",
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
    ) -> str:
        """User-side prompt. Presents the task, context, and schema name."""
        parts: list[str] = [f"Task: {task}", ""]
        parts.append(f"Output schema: `{output_schema_name}`. Reply with a JSON object matching it.")
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
    ) -> tuple[str, str]:
        return self.system_prompt(agent), self.user_prompt(task, context_chunks, output_schema_name)

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
