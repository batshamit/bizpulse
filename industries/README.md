# Industry knowledge packs

Each YAML in this directory is a self-contained vertical config that drives BizPulse's reasoning for that industry. Adding a new vertical = drop a new YAML + 4–5 golden eval examples. The platform is designed so this is a one-day exercise.

## Schema

```yaml
slug:                    # short identifier, used as Qdrant metadata key
name:                    # human label
description:             # one-line pitch, used in industry-classifier confidence prompts
ontology:                # entities + concepts that matter in this vertical
  entities: [...]
  regulations: [...]     # compliance flags the Critic surfaces
  metrics: [...]
competitor_seeds:        # 5–10 well-known players; Competitor Scout starts here
channel_weights:         # 0.0–1.0 importance per channel; Strategist uses for ranking
  instagram: 1.0
  linkedin: 0.6
  ...
content_pillars:         # typical content categories for this vertical
prompt_addendum: |       # appended to Strategist's base prompt at runtime
  ...
golden_eval_seeds:       # references to tests/eval/golden/{slug}/*.json (4–5 hand-labeled cases)
  - "..."
```

## Currently shipped

- **fintech** — B2C, regulated, digital-first; matches the target company's vertical.
- **real_estate** — B2C, high-ticket, local, visual; very different content patterns.
- **construction_materials** — B2B, technical, channel-driven; proves we handle B2B.
