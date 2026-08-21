"""
AITranslationAgent — 3-tier fallback for low-confidence expressions.

Ref: spec/agents.md §Agent 5
ADR-018: LLM cache with SHA-256 hash-based JSON file cache

Responsibilities:
  1. Hash lookup → known translations
  2. Pattern match → dimty→LOD template catalog
  3. LLM fallback → via centralized get_llm() (OpenAI or Azure)
  4. sqlglot syntax validation of generated Tableau calc
"""

import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.llm import get_llm
from app.models.job import Job
from app.models.objects import MigrationObject, ReviewTask

logger = logging.getLogger(__name__)


class TableauMetricTranslation(BaseModel):
    """Structured response schema for MicroStrategy to Tableau calculation translation."""

    tableau_calc: str = Field(
        description="The exact Tableau calculated field formula using valid Tableau Desktop syntax (e.g. 'SUM([Sales])', '{ FIXED [Region] : AVG([Profit]) }')"
    )
    explanation: str = Field(
        default="LLM translated calculation",
        description="Concise 1-2 sentence explanation of the translation logic and level-of-detail mapping."
    )
    confidence: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0 reflecting syntax certainty."
    )
    requires_human_review: bool = Field(
        default=False,
        description="Set to true if the formula contains unsupported MicroStrategy functions, ambiguous joins, or requires domain review; otherwise false."
    )


@dataclass
class LLMTranslationResult:
    """Result from LLM translation."""
    tableau_calc: str
    explanation: str
    confidence: float
    requires_human_review: bool


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Dimty → LOD Template Catalog (Tier 2)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DIMTY_LOD_TEMPLATES = {
    # Dimty pattern → Tableau LOD template
    "level_metric_fixed": "{{ FIXED [{grain_dims}] : {agg}([{measure}]) }}",
    "level_metric_include": "{{ INCLUDE [{grain_dims}] : {agg}([{measure}]) }}",
    "level_metric_exclude": "{{ EXCLUDE [{grain_dims}] : {agg}([{measure}]) }}",
    "running_sum": "RUNNING_SUM(SUM([{measure}]))",
    "running_avg": "RUNNING_AVG(AVG([{measure}]))",
    "percent_of_total": "SUM([{measure}]) / TOTAL(SUM([{measure}]))",
    "rank": "RANK(SUM([{measure}]))",
    "moving_average": "WINDOW_AVG(SUM([{measure}]), -{window}, 0)",
    "year_over_year": "SUM([{measure}]) - LOOKUP(SUM([{measure}]), -1)",
    "percent_change": "(SUM([{measure}]) - LOOKUP(SUM([{measure}]), -1)) / ABS(LOOKUP(SUM([{measure}]), -1))",
}


class TranslationCache:
    """SHA-256 hash-based JSON file cache for LLM translations (ADR-018)."""

    def __init__(self, cache_dir: str):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _hash_key(self, expression: str) -> str:
        return hashlib.sha256(expression.encode()).hexdigest()

    def get(self, expression: str) -> Optional[LLMTranslationResult]:
        """Lookup cached translation by expression hash."""
        key = self._hash_key(expression)
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            data = json.loads(cache_file.read_text())
            return LLMTranslationResult(**data)
        return None

    def put(self, expression: str, result: LLMTranslationResult):
        """Cache a translation result."""
        key = self._hash_key(expression)
        cache_file = self.cache_dir / f"{key}.json"
        cache_file.write_text(json.dumps({
            "tableau_calc": result.tableau_calc,
            "explanation": result.explanation,
            "confidence": result.confidence,
            "requires_human_review": result.requires_human_review,
        }, indent=2))


class AITranslationAgent:
    """
    Agent 5: AI-assisted translation for low-confidence expressions.

    Uses a 3-tier fallback sequence:
    1. Hash lookup (cached translations)
    2. Pattern match (dimty→LOD templates)
    3. LLM translation via centralized get_llm() (OpenAI or Azure)

    Only processes IR measures with confidence < 0.85.
    """

    def __init__(self, db: Session, job: Job, artifacts_dir: str):
        self.db = db
        self.job = job
        self.cache = TranslationCache(
            os.path.join(artifacts_dir, "translation_cache")
        )
        self.llm = get_llm(temperature=0.1)

    async def run(self, ir, translate_all: bool = False) -> None:
        """
        Process measures in the IR using the 3-tier fallback translation sequence.

        Modifies measures in-place with translated Tableau calcs and updates database MigrationObjects.
        """
        if translate_all:
            candidates = [m for m in ir.measures if m.confidence < 0.95 or (m.expression_text and "<" in m.expression_text)]
        elif self.llm is not None:
            # Translate low-confidence measures (< 0.85) and complex MSTR expressions (<, /, If, Case, Rank, Lag)
            candidates = [
                m for m in ir.measures
                if m.confidence < 0.85
                or (m.expression_text and any(k in m.expression_text for k in ["<", "/", "If(", "Case(", "Rank(", "Lag("]))
            ]
        else:
            candidates = [m for m in ir.measures if m.confidence < 0.85]

        if not candidates:
            logger.info("No candidate measures requiring AI translation")
            # Still ensure all DB MigrationObjects have their compiled tableau_calc
            for measure in ir.measures:
                obj = (
                    self.db.query(MigrationObject)
                    .filter(
                        MigrationObject.job_id == self.job.id,
                        MigrationObject.mstr_id == measure.mstr_id,
                    )
                    .first()
                )
                if obj and not obj.tableau_calc:
                    obj.tableau_calc = measure.tableau_calc
                    obj.expression_text = measure.expression_text
                    obj.confidence = measure.confidence
                    obj.translation_method = "AST Expression Engine"
            self.db.commit()
            return

        logger.info("Translating %d measures via AI translation sequence", len(candidates))

        for measure in candidates:
            result = await self._translate(measure)

            if result and result.tableau_calc and not result.tableau_calc.startswith("// TODO"):
                measure.tableau_calc = result.tableau_calc
                measure.confidence = max(measure.confidence, result.confidence)

                # Update DB MigrationObject
                obj = (
                    self.db.query(MigrationObject)
                    .filter(
                        MigrationObject.job_id == self.job.id,
                        MigrationObject.mstr_id == measure.mstr_id,
                    )
                    .first()
                )
                if obj:
                    obj.tableau_calc = result.tableau_calc
                    obj.confidence = measure.confidence
                    obj.translation_method = "LLM Engine (Centralized)"

                if result.requires_human_review:
                    self._create_review_task(measure, result)
            else:
                # Ensure existing AST calc is preserved in DB
                obj = (
                    self.db.query(MigrationObject)
                    .filter(
                        MigrationObject.job_id == self.job.id,
                        MigrationObject.mstr_id == measure.mstr_id,
                    )
                    .first()
                )
                if obj and not obj.tableau_calc:
                    obj.tableau_calc = measure.tableau_calc
                    obj.expression_text = measure.expression_text
                    obj.confidence = measure.confidence
                    obj.translation_method = "AST Expression Engine"

        self.db.commit()

    async def _translate(self, measure) -> Optional[LLMTranslationResult]:
        """Execute 3-tier fallback translation."""
        expr_key = measure.expression_text or str(measure.mstr_id)

        # ── Tier 1: Hash lookup ─────────────────────────────────
        cached = self.cache.get(expr_key)
        if cached:
            logger.debug("Tier 1 hit (cache) for %s", measure.name)
            return cached

        # ── Tier 2: Pattern match ───────────────────────────────
        pattern_result = self._pattern_match(measure)
        if pattern_result:
            logger.debug("Tier 2 hit (pattern) for %s", measure.name)
            self.cache.put(expr_key, pattern_result)
            return pattern_result

        # ── Tier 3: LLM translation ────────────────────────────
        llm_result = await self._llm_translate(measure)
        if llm_result:
            logger.debug("Tier 3 (LLM) for %s", measure.name)
            self.cache.put(expr_key, llm_result)
            return llm_result

        return None

    def _pattern_match(self, measure) -> Optional[LLMTranslationResult]:
        """Match dimty patterns to LOD templates."""
        dimty = getattr(measure, "dimty", None)
        expr_text = measure.expression_text or ""

        # Detect percent-of-total pattern
        if "/" in expr_text and "total" in expr_text.lower():
            measure_name = re.search(r'Sum\((.+?)\)', expr_text, re.IGNORECASE)
            if measure_name:
                calc = DIMTY_LOD_TEMPLATES["percent_of_total"].format(
                    measure=measure_name.group(1)
                )
                return LLMTranslationResult(
                    tableau_calc=calc,
                    explanation="Matched percent-of-total pattern",
                    confidence=0.90,
                    requires_human_review=False,
                )

        # Detect running sum/avg
        for pattern in ("running_sum", "running_avg"):
            if pattern.replace("_", " ") in expr_text.lower():
                measure_name = re.search(r'Sum\((.+?)\)', expr_text, re.IGNORECASE)
                if measure_name:
                    calc = DIMTY_LOD_TEMPLATES[pattern].format(
                        measure=measure_name.group(1)
                    )
                    return LLMTranslationResult(
                        tableau_calc=calc,
                        explanation=f"Matched {pattern} pattern",
                        confidence=0.88,
                        requires_human_review=False,
                    )

        # Detect rank
        if "rank" in expr_text.lower():
            measure_name = re.search(r'Rank\((.+?)\)', expr_text, re.IGNORECASE)
            if measure_name:
                calc = DIMTY_LOD_TEMPLATES["rank"].format(
                    measure=measure_name.group(1)
                )
                return LLMTranslationResult(
                    tableau_calc=calc,
                    explanation=f"Matched rank pattern",
                    confidence=0.88,
                    requires_human_review=False,
                )

        # LOD from dimty
        if dimty and isinstance(dimty, dict):
            level_type = dimty.get("type", "").lower()
            grain_dims = dimty.get("attributes", [])
            agg = dimty.get("aggregation", "SUM")

            if level_type in ("fixed", "include", "exclude") and grain_dims:
                template_key = f"level_metric_{level_type}"
                template = DIMTY_LOD_TEMPLATES.get(template_key)
                if template:
                    calc = template.format(
                        grain_dims="], [".join(grain_dims),
                        agg=agg.upper(),
                        measure=measure.name,
                    )
                    return LLMTranslationResult(
                        tableau_calc=calc,
                        explanation=f"Matched dimty→LOD {level_type} pattern",
                        confidence=0.85,
                        requires_human_review=False,
                    )

        return None

    async def _llm_translate(self, measure) -> Optional[LLMTranslationResult]:
        """
        Use centralized get_llm() for expression translation (Tier 3).

        Calls the LangChain-wrapped OpenAI/Azure client via .invoke().
        """
        if not self.llm:
            logger.warning("No LLM configured — skipping LLM translation for %s", measure.name)
            return LLMTranslationResult(
                tableau_calc=f"// TODO: AI translation needed for {measure.name}",
                explanation="No LLM API key configured",
                confidence=0.30,
                requires_human_review=True,
            )

        try:
            prompt = f"""Translate this MicroStrategy metric expression to a Tableau calculated field.

MicroStrategy Metric: {measure.name}
Expression: {measure.expression_text or 'Not available'}
Dimensionality: {json.dumps(getattr(measure, 'dimty', None))}
Conditionality: {json.dumps(getattr(measure, 'conditionality', None))}

Rules:
- Use Tableau Desktop syntax (SUM, AVG, COUNT, COUNTD, MIN, MAX, etc.)
- Use FIXED/INCLUDE/EXCLUDE LOD expressions where dimensionality indicates
- Handle null with ZN() if needed
- Handle zero division with IIF(denominator = 0, NULL, ...)
- Do NOT use RAWSQL or custom SQL"""

            # 1. Prefer structured output (Pydantic schema enforcement)
            if hasattr(self.llm, "with_structured_output"):
                try:
                    structured_llm = self.llm.with_structured_output(TableauMetricTranslation)
                    res = structured_llm.invoke(prompt)
                    if isinstance(res, TableauMetricTranslation):
                        calc_val = res.tableau_calc.strip()
                        return LLMTranslationResult(
                            tableau_calc=calc_val,
                            explanation=res.explanation,
                            confidence=float(res.confidence),
                            requires_human_review=bool(res.requires_human_review),
                        )
                    elif isinstance(res, dict):
                        calc_val = str(res.get("tableau_calc", "")).strip()
                        return LLMTranslationResult(
                            tableau_calc=calc_val,
                            explanation=str(res.get("explanation", "LLM translated")),
                            confidence=float(res.get("confidence", 0.90)),
                            requires_human_review=bool(res.get("requires_human_review", False)),
                        )
                except Exception as struct_err:
                    logger.debug("Structured output invoke fallback: %s", struct_err)

            # 2. Fallback to standard prompt invoke + JSON extraction
            full_prompt = f"""{prompt}
- Output ONLY valid JSON in format:
{{"tableau_calc": "...", "explanation": "...", "confidence": 0.0-1.0, "requires_human_review": true/false}}"""

            response = self.llm.invoke(full_prompt)

            # Extract content from LangChain AIMessage or CachedAIMessage
            content = response.content if hasattr(response, "content") else str(response)

            # Robust JSON extraction handling markdown ```json ... ``` blocks or raw json
            parsed = None
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(1))
                except Exception:
                    pass
            if not parsed:
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group(0))
                    except Exception:
                        pass
            if not parsed:
                parsed = json.loads(content)

            # Validate via Pydantic model for strict type coercion
            validated = TableauMetricTranslation.model_validate(parsed)
            calc_val = validated.tableau_calc.strip()

            # Validate with sqlglot if possible
            try:
                import sqlglot
                sqlglot.parse(calc_val)
            except Exception:
                logger.debug("sqlglot notice for LLM output: %s", calc_val)

            return LLMTranslationResult(
                tableau_calc=calc_val,
                explanation=validated.explanation,
                confidence=float(validated.confidence),
                requires_human_review=bool(validated.requires_human_review),
            )

        except Exception as e:
            logger.error("LLM translation failed for %s: %s", measure.name, e)
            return LLMTranslationResult(
                tableau_calc=f"// TODO: LLM translation failed for {measure.name}",
                explanation=f"LLM error: {str(e)[:200]}",
                confidence=0.20,
                requires_human_review=True,
            )

    def _create_review_task(self, measure, result: LLMTranslationResult):
        """Create a review task for human review of AI-translated expression."""
        obj = self.db.query(MigrationObject).filter(
            MigrationObject.job_id == self.job.id,
            MigrationObject.mstr_id == measure.mstr_id,
        ).first() if self.db else None

        task = ReviewTask(
            id=str(uuid.uuid4()),
            job_id=self.job.id,
            object_id=obj.id if obj else None,
            severity="warning" if result.confidence >= 0.50 else "blocker",
            reason=f"AI-translated with confidence {result.confidence:.2f}: {result.explanation}",
            mstr_expression=measure.expression_text,
            generated_calc=result.tableau_calc,
            confidence=result.confidence,
            status="pending",
        )
        self.db.add(task)

