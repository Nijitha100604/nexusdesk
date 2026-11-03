# Evaluation dataset (synthetic)

`test_tickets.jsonl`: 69 labelled employee messages for Phase 15 evaluation.

Rules
- Never load these into ServiceNow or the knowledge base.
- Never include them in prompts, examples or tuning data for the agents.
- Tune thresholds on `split = dev`; report final results on `split = test` only.

Fields: eval_id, split, scenario, message, expected_category, expected_urgency,
expected_impact, expected_priority, expected_article (art_id or null),
expected_route (answer | clarify | approval | escalate | refuse), notes.

Scenarios: article_match (40), no_kb (8), critical (4), sensitive (4), security (3),
vague (6, static), injection (4, static).
Labels come from scripts/seed/seed_data.py; the LLM only wrote the message wording.
expected_article uses local article IDs; map them to KB numbers with the local
seed_manifest.json after seeding.
