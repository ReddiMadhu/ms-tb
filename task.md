# Task Tracker: Wire Pipeline Agents

## Phase 1: Core Pipeline → Produce .twbx

- `[x]` Step 1.1: Install missing Python packages (`tableauhyperapi`, `tableauserverclient`, `langchain-openai`, `pandas`)
- `[x]` Step 1.2: Wire SemanticAgent (Stage 3)
- `[x]` Step 1.3: Wire IRCompilerAgent + Dedup (Stages 4-5)
- `[x]` Step 1.4: Wire AITranslationAgent (Stage 6)
- `[x]` Step 1.5: Wire VisualizationAgent (Stage 7)
- `[x]` Step 1.6: Wire HyperBuilderAgent (Stage 8)
- `[x]` Step 1.7: Wire TableauEmitterAgent (Stages 9, 10, 15)
- `[x]` Step 1.8: Add download endpoint + UI button

## Phase 2: Validation & Publishing

- `[x]` Step 2.1: Wire ValidationAgent (Stages 12-14)
- `[x]` Step 2.2: Wire PublishAgent (Stages 11, 16, 17)

## Phase 3: Report & Review

- `[x]` Step 3.1: Implement Report generation in orchestrator (Stage 18)
- `[x]` Step 3.2: Verify full test suite (10/10 tests passing) & e2e test
