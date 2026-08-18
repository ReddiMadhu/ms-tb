# Expression Compiler Specification — mstr-tableau-migrator

**Companion to:** `ir-schema.md`, `agents.md`  
**Date:** 17 August 2026  

---

## 1. Overview

The expression compiler is the core translation engine that converts MicroStrategy metric expression trees into Tableau calculated field syntax. It is the highest-risk component (70% feasibility confidence from the report) and receives the most engineering investment.

### Architecture

```
MSTR Expression Tree (JSON)
         │
    ┌────▼────┐
    │  Parser  │  → Normalize MSTR tree/tokens into canonical AST
    └────┬────┘
         │
    ┌────▼────────────┐
    │  Rule Compiler   │  → Deterministic pattern matching
    └────┬────────────┘
         │
    ┌────▼────────────────────────────────────────────┐
    │  3-Tier Fallback (if rule compiler confidence    │
    │  < 0.85 or pattern not matched)                  │
    │                                                  │
    │  Tier 1: Hash Lookup (exact match cache)         │
    │  Tier 2: Pattern Match (dimty→LOD catalog)       │
    │  Tier 3: Semantic Search (embedding similarity)  │
    │  Tier 4: LLM Translation (last resort)           │
    └────┬────────────────────────────────────────────┘
         │
    ┌────▼──────────┐
    │  Validator     │  → Golden test + syntax check
    └────┬──────────┘
         │
    Tableau Calculated Field String
```

---

## 2. MSTR Expression Tree Parser

### Input Format

MSTR metrics expose expressions in two formats via the Modeling API:

**Tree format** (`showExpressionAs=tree`):
```json
{
  "expression": {
    "text": "Sum(Revenue){~+}",
    "tree": {
      "type": "operator",
      "function": "sum",
      "children": [
        {
          "type": "object_reference",
          "objectId": "FA8BF04A...",
          "objectType": "fact",
          "name": "Revenue"
        }
      ]
    }
  },
  "dimty": {
    "dimtyUnits": [
      {
        "dimtyUnitType": "attribute",
        "target": {"objectId": "8D679D38...", "name": "Year"},
        "aggregation": "normal",
        "filtering": "standard",
        "groupBy": true
      }
    ],
    "allowAddition": true
  }
}
```

**Tokens format** (`showExpressionAs=tokens`):
```json
{
  "expression": {
    "text": "Sum(Revenue){~+}",
    "tokens": [
      {"type": "function", "value": "Sum"},
      {"type": "character", "value": "("},
      {"type": "object", "value": "Revenue", "objectId": "FA8BF04A..."},
      {"type": "character", "value": ")"},
      {"type": "level", "value": "{~+}"}
    ]
  }
}
```

### Canonical AST & EvaluationPlan (Audit v3 Architecture)

Both formats are parsed into a canonical internal AST, which is then compiled into a multi-phase **EvaluationPlan** before rendering target Tableau syntax:

```
MSTR Metric AST 
  → EvaluationPlan (Semantic Execution Blueprint) 
  → Target Tableau Formula
```

```python
@dataclass
class ASTNode:
    op: str                    # "agg", "arith", "cond", "comp", "func", "literal", "fieldRef", "lod"
    fn: Optional[str]          # "sum", "avg", "div", etc.
    args: list["ASTNode"]      # child nodes
    field: Optional[str]       # field reference (e.g., "fact:revenue")
    value: Optional[Any]       # literal value
    data_type: Optional[str]   # "number", "string", "date"
    lod_type: Optional[str]    # "fixed", "include", "exclude"
    grain: list[str]           # grain dimensions for LOD
    offset: Optional[dict]     # time offset for transformations
    filtering_mode: Optional[str]    # [AUDIT] "standard" | "absolute" — from MSTR dimty filtering flag
    condition_phase: Optional[str]   # [AUDIT] "pre_agg" | "post_agg" — conditionality position

@dataclass
class EvaluationPlan:
    """[Audit v3 — Critical] Explicit multi-phase semantic execution model."""
    id: str
    source_metric_id: str
    row_expression: Optional[ASTNode]        # Row-level calculations / pre-agg conditional logic
    pre_filters: list[ASTNode]               # Element qualifications applied before aggregation
    aggregation: str                         # sum, avg, count, countd, min, max, median
    metric_dimensionality: list[str]         # Dimensionality grain (FIXED / INCLUDE dimensions)
    filtering_mode: str                      # "standard" | "absolute"
    condition_phase: str                     # "pre_agg" | "post_agg"
    post_agg_condition: Optional[ASTNode]    # HAVING-style filter on aggregated value
    transformation: Optional[dict]           # Time intelligence / transformation specification
    window_calc: Optional[dict]              # Window / table calculation definition
    null_propagation: str                    # "propagate" | "ignore" (from VLDB)
    zero_division_result: str                # "null" | "zero" (from VLDB)
    confidence: float
```

> **Audit v3 Invariant:** The canonical output of the semantic compiler is the **EvaluationPlan**. A Tableau formula string is merely one dialect rendering of the evaluation plan.

---

## 3. Rule Compiler — Pattern Catalog

### 3.1 Simple Aggregation Metrics

| MSTR Pattern | Tableau Output | Confidence | Notes |
|-------------|----------------|------------|-------|
| `Sum(Fact)` | `SUM([Fact])` | 0.99 | |
| `Avg(Fact)` | `AVG([Fact])` | 0.99 | |
| `Count(Fact)` | `COUNT([Fact])` | 0.99 | Fact operand counts non-null fact rows |
| `Count(Attribute)` | `COUNTD([Attribute_ID])` | 0.98 | **[Audit v4 — Trap A]:** Operand is an Attribute (not Fact). MSTR counts distinct attribute elements. Under raw-grain extraction, `COUNT([attr_id])` counts transaction rows. Compiler MUST emit `COUNTD` of the ID form. |
| `Count(Distinct Attribute)` | `COUNTD([Attribute])` | 0.99 | |
| `Min(Fact)` | `MIN([Fact])` | 0.99 | |
| `Max(Fact)` | `MAX([Fact])` | 0.99 | |
| `Median(Fact)` | `MEDIAN([Fact])` | 0.99 | |

### 3.2 Derived Metrics (Arithmetic & Division Analysis)

| MSTR Pattern | Tableau Output | Confidence |
|-------------|----------------|------------|
| `Metric_A / Metric_B` | Context-aware division (see below) | 0.97 |
| `Metric_A - Metric_B` | `[Metric_A] - [Metric_B]` | 0.97 |
| `Metric_A * Constant` | `[Metric_A] * {Constant}` | 0.98 |
| `(Metric_A - Metric_B) / Metric_B` | Context-aware division (see below) | 0.95 |

> **Audit v3 (Context-Aware Division):** Division expressions are rendered based on operand tree analysis (`analyze_division_null_semantics`) and VLDB settings:
> - Default (`ZERO_DIVISION_RESULT = Null`, `NULL_PROPAGATION = propagate`): `[A] / NULLIF([B], 0)`
> - Project with `ZERO_DIVISION_RESULT = Zero`: `ZN([A] / NULLIF([B], 0))`
> - Project with `NULL_PROPAGATION = ignore`: `ZN([A]) / NULLIF(ZN([B]), 0)`

### 3.3 Conditional Metrics

#### 3.3a Pre-Aggregation Conditions (Row-Level Filters)

| MSTR Pattern | Tableau Output | Confidence | Condition Phase |
|-------------|----------------|------------|----------------|
| `Sum(Fact) {Filter}` | `SUM(IF [Filter_Field] = 'Value' THEN [Fact] END)` | 0.88 | `pre_agg` |
| `Sum(Fact) {AttributeQual}` | `SUM(IF [Attribute] = 'Value' THEN [Fact] END)` | 0.88 | `pre_agg` |
| `Sum(Fact) WHERE Condition` | `SUM(IF [Condition] THEN [Fact] END)` | 0.85 | `pre_agg` |

#### 3.3b Post-Aggregation Conditions (HAVING-Style — Audit Trap 3)

| MSTR Pattern | Tableau Output | Confidence | Condition Phase |
|-------------|----------------|------------|----------------|
| Metric conditionality: "show only where `Sum(Revenue) > 1M`" | `ZN(IF {FIXED [grain] : SUM([Revenue])} > 1000000 THEN {FIXED [grain] : SUM([Revenue])} END)` | 0.60 | `post_agg` |
| Metric joint element with aggregated threshold | `IF SUM([Fact]) > threshold THEN SUM([Fact]) END` (only valid when grain matches viz grain) | 0.55 | `post_agg` |

> **⚠️ CRITICAL (Audit Trap 3):** MSTR's post-aggregation conditionality (e.g., "Show Revenue only for Regions where Revenue > 1M") is equivalent to SQL `HAVING`. The pre-aggregation pattern `SUM(IF [Revenue] > 1000000 THEN [Revenue] END)` filters individual *rows* > 1M — almost always producing zero results. The parser must check the `conditionality` field in the MSTR metric API response and set `condition_phase: "post_agg"` when the condition applies to the aggregated result.

### 3.4 Level Metrics (Dimty → LOD) ★ Hardest

> **⛔ AUDIT F1 — FIXED LOD is NOT unconditionally safe:**
> FIXED LODs bypass dimension filters (Tableau OoP step 3 vs. step 5). If the dossier/worksheet has ANY dimension filter that interacts with the FIXED grain columns, the compiler **must** either:
> 1. Promote those interacting dimension filters to **context filters** in the worksheet XML (emitting `contextFilterRequirements` on the Measure/Worksheet IR), or
> 2. Use `{INCLUDE}` instead of `{FIXED}` where report-filter-respect is needed, or
> 3. Block with `Issue(warning, context_filter_lod_conflict)` for human review.
>
> The compiler receives filter context via `CompilationContext` (dossier filters, page filters, shelf grain). Confidence on FIXED patterns is **conditional** on filter-interaction analysis passing.

| MSTR Pattern | Tableau Output | Confidence | Notes |
|-------------|----------------|------------|-------|
| `Sum(Fact){~+}` (report level, `filtering: "standard"`, **not nested/conditional**) | `SUM([Fact])` (no LOD needed) | 0.95 | Only when used standalone on a grouped sheet |
| `Sum(Fact){~+}` (report level, `filtering: "standard"`, **nested in another metric or conditionality**) | `{FIXED : SUM([Fact])}` with all report filters promoted to context | 0.70 | **⚠️ Audit F1 — `{~+}` in nested context ignores template grouping, not viz grouping** |
| `Sum(Fact){~+}` (report level, `filtering: "absolute"`) | `{FIXED : SUM([Fact])}` (ignores all dim filters) | 0.90 | **Audit Trap 1** |
| `Sum(Fact){Year}` (fixed at Year, **no interacting dim filters**) | `{FIXED [Year] : SUM([Fact])}` | 0.82 | Requires filter-interaction analysis pass |
| `Sum(Fact){Year}` (fixed at Year, **has interacting dim filters**) | `{FIXED [Year] : SUM([Fact])}` + context filter promotion | 0.65 | **Audit F1** — emitter must promote interacting filters |
| `Sum(Fact){Year, Region}` (fixed at Year+Region) | `{FIXED [Year], [Region] : SUM([Fact])}` | 0.82 | Same filter-interaction rules apply |
| `Sum(Fact){~, Year}` (dimensionality includes Year) | `{INCLUDE [Year] : SUM([Fact])}` | 0.78 | |
| `Sum(Fact){~-Year}` (exclude Year from grain) | ⛔ **STRUCTURAL BLOCKER** (`requires_view_dependency_analysis`) | 0.40 | **[Audit v3 — Critical]:** `EXCLUDE` LODs in Tableau dynamically depend on what dimensions are placed on viz shelves. In MSTR, dimensionality is fixed regardless of view layout. Auto-publishing is **prohibited**; always routed to human review with shelf-freezing validation. |
| `Sum(Fact){~-ComputedDateDim}` (exclude computed date dim) | ❌ Cannot emit valid `{EXCLUDE}` | 0.20 | **[Audit v2/v3]:** `EXCLUDE` on computed date dimension is undefined. Blocker. |
| `Sum(Fact){~+, Year-1}` (year offset) — via `LOOKUP` | ~~`LOOKUP(SUM([Fact]), -1)`~~ | ~~0.65~~ **0.10** | **⛔ AUDIT FLAW 2: MANDATORY_REVIEW** |
| `Sum(Fact){~+, Year-1}` (year offset) — via materialization | `[Fact_Prior_Year]` (pre-computed Hyper column) | 0.92 | **PREFERRED PATH** |
| `Sum(Fact){~+, Year-1}` (year offset) — via shifted-key join | Hyper join on `Year-1` key (transformation table replication) | 0.85 | **SECONDARY PATH** |
| Nested level metric | Nested LOD | 0.55 | **⚠️ Audit: inner/outer LOD scoping differs from MSTR multi-pass** |

> **⛔ AUDIT FLAW 2 — LOOKUP is mathematically wrong in 95% of dashboards:**
> `LOOKUP()` is a *table calculation* that navigates the rendered result set. It returns `NULL` when: (a) no Year dimension is on the viz shelf, (b) a single-year quick filter is applied, (c) addressing/partitioning settings are changed by the user. MSTR's `{Year-1}` uses transformation tables that always produce the prior-year value regardless of the viz grid.
>
> **Preferred path:** If the cube supports transformation attributes, the HyperAgent should extract `Revenue` AND `Revenue_Prior_Year` as separate named columns during data extraction. The Tableau calc then references `[Revenue_Prior_Year]` directly — no table calc, no LOD, no breakage when users filter.
>
> **Secondary path:** Replicate the MSTR transformation table as a shifted-key join in the Hyper build (join date dimension to itself on `Year-1` key). Deterministic, filter-immune.
>
> **Last-resort fallback:** `LOOKUP` with explicit `MANDATORY_REVIEW` flag and constraint: "user must not filter below the offset grain." Confidence 0.10.
>
> **⛔ KILL:** ~~`{FIXED [Year]-1 : SUM([Fact])}`~~ — this is **invalid Tableau syntax** (LOD dimensions are field refs, not arithmetic expressions). Deleted from spec.

### 3.5 Transformation Metrics (Time Intelligence)

> **⚠️ All `LOOKUP()`-based translations in this section carry confidence 0.10 and `MANDATORY_REVIEW` flag.** See Audit Flaw 2 above. The preferred approach is HyperAgent materialization.

| MSTR Pattern | Tableau Output (Preferred: Materialization) | Tableau Output (Fallback: Table Calc) | Confidence (Preferred / Fallback) |
|-------------|----------------------------------------------|---------------------------------------|-----------------------------------|
| `Sum(Revenue){Year-1}` (prior year) | `[Revenue_Prior_Year]` (pre-computed column) | ~~`LOOKUP(SUM([Revenue]), -1)`~~ | 0.92 / 0.10 |
| `Sum(Revenue){Month-1}` (prior month) | `[Revenue_Prior_Month]` (pre-computed column) | ~~`LOOKUP(SUM([Revenue]), -1)`~~ | 0.92 / 0.10 |
| YTD aggregation | Pre-computed `[Revenue_YTD]` column | Running sum with date filter | 0.85 / 0.50 |
| MTD aggregation | Pre-computed `[Revenue_MTD]` column | Running sum with date filter | 0.85 / 0.50 |
| Moving average | N/A | `WINDOW_AVG(SUM([Fact]), -N, 0)` | — / 0.60 |

### 3.6 String & Date Functions

| MSTR Function | Tableau Function | Confidence |
|--------------|-----------------|------------|
| `Concat(A, B)` | `[A] + [B]` | 0.98 |
| `Length(A)` | `LEN([A])` | 0.98 |
| `Upper(A)` | `UPPER([A])` | 0.99 |
| `Lower(A)` | `LOWER([A])` | 0.99 |
| `Trim(A)` | `TRIM([A])` | 0.99 |
| `SubStr(A, start, len)` | `MID([A], start, len)` | 0.95 |
| `Position(sub, str)` | `FIND([str], sub)` | 0.95 |
| `CurrentDate` | `TODAY()` | 0.99 |
| `DaysBetween(A, B)` | `DATEDIFF('day', [A], [B])` | 0.95 |
| `Year(Date)` | `YEAR([Date])` | 0.99 |
| `Month(Date)` | `MONTH([Date])` | 0.99 |
| `AddDays(Date, N)` | `DATEADD('day', N, [Date])` | 0.95 |

### 3.7 Null Handling

#### 3.7a Pre-Aggregation Null Coalescing

| MSTR Pattern | Tableau Output | Confidence | Notes |
|-------------|----------------|------------|-------|
| `NullToZero(Fact)` (row-level) | `ZN([Fact])` or `IFNULL([Fact], 0)` | 0.98 | Coalesces NULL to 0 at row level before aggregation |
| `IsNull(Fact)` | `ISNULL([Fact])` | 0.98 | |
| `Coalesce(A, B)` | `IFNULL([A], [B])` | 0.97 | |

#### 3.7b Post-Aggregation Null Coalescing (Audit Fix)

| MSTR Pattern | Tableau Output | Confidence | Notes |
|-------------|----------------|------------|-------|
| `NullToZero(Sum(Fact))` (post-agg) | `ZN(SUM([Fact]))` | 0.95 | Aggregates first, then coalesces empty-set NULL to 0 |
| Division with post-agg ZN | `ZN(SUM([A]) / SUM([B]))` | 0.90 | Prevents `0/x` vs `NULL/x` discrepancy |

> **⚠️ Audit (2.3 NULL/zero semantics):** MSTR's `NullToZero` placement determines pre- vs post-aggregation semantics. Pre-agg: `ZN([F])` → NULLs become 0 before SUM (changes the SUM). Post-agg: `ZN(SUM([F]))` → empty-set SUM returns 0 instead of NULL (doesn't change the SUM for non-empty sets). The pattern must be keyed off AST position — `NullToZero` wrapping an `agg` node is post-agg.

#### 3.7c VLDB Null Propagation Policy (Audit v2 — Trap 9)

> **⛔ Audit v2:** The MSTR project-level VLDB `NULL_PROPAGATION` setting determines whether `NULL` in arithmetic propagates (`NULL * 10 = NULL`) or is ignored (`NULL * 10 = 0`). This setting is extracted by DiscoveryAgent (Step 7) and stored in `jobs.vldb_settings_json`. **The compiler must consume it.**

| VLDB `null_propagation` | Compiler Behavior | Notes |
|------------------------|-------------------|-------|
| `"propagate"` (default) | No change — Tableau default matches | Arithmetic `NULL` propagates naturally |
| `"ignore"` | Wrap **every arithmetic operand** in `ZN()` | `SUM([A]) + SUM([B])` → `ZN(SUM([A])) + ZN(SUM([B]))` |

The `CompilationContext` must carry `null_propagation: "propagate" | "ignore"` from the job's VLDB settings. When `"ignore"`, the rule compiler applies `ZN()` wrapping as a **project-level global transform** on all arithmetic AST nodes — not a per-metric setting.

```python
class CompilationContext:
    dimensions: list[str]
    measures: list[str]
    filters: list[FilterSpec]
    filtering_mode: Optional[str]
    condition_phase: Optional[str]
    null_propagation: str = "propagate"  # [Audit v2] from jobs.vldb_settings_json
    zero_division_result: str = "null"   # [Audit v2] from jobs.vldb_settings_json
```

### 3.8 Conditional Logic

| MSTR Pattern | Tableau Output | Confidence |
|-------------|----------------|------------|
| `If(Condition, ThenValue, ElseValue)` | `IF [Condition] THEN [ThenValue] ELSE [ElseValue] END` | 0.95 |
| `Case(Attr, Val1, Res1, Val2, Res2, Default)` | `CASE [Attr] WHEN 'Val1' THEN Res1 WHEN 'Val2' THEN Res2 ELSE Default END` | 0.90 |
| `ApplySimple("SQL", args)` | Direct SQL or `RAWSQL()` | 0.50 |

---

## 4. 3-Tier Fallback System

### Tier 1: Hash Lookup

```python
class HashLookup:
    """Exact match cache of previously-validated translations."""
    
    def __init__(self, cache_path: str = "expression_cache.json"):
        self.cache = self._load_cache(cache_path)
    
    def lookup(self, expression_hash: str) -> Optional[str]:
        """Canonical hash of MSTR expression tree → known Tableau calc."""
        return self.cache.get(expression_hash)
    
    def store(self, expression_hash: str, tableau_calc: str, validated: bool):
        """Store a validated translation for future reuse."""
        if validated:
            self.cache[expression_hash] = tableau_calc
            self._save_cache()
    
    @staticmethod
    def canonical_hash(ast: ASTNode) -> str:
        """Produce a canonical hash by serializing the AST deterministically."""
        canonical = json.dumps(ast.to_dict(), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()
```

### Tier 2: Pattern Match (Dimty → LOD Template Catalog)

```python
class PatternMatcher:
    """Match MSTR expression shapes against a catalog of known dimty→LOD patterns."""
    
    PATTERNS = [
        DimtyPattern(
            name="simple_fixed_single_dim",
            mstr_shape={"has_dimty": True, "dim_count": 1, "allow_addition": False},
            tableau_template="{FIXED [{dim_0}] : {agg_fn}([{fact}])}",
            confidence=0.82,
        ),
        DimtyPattern(
            name="simple_fixed_multi_dim",
            mstr_shape={"has_dimty": True, "dim_count": 2, "allow_addition": False},
            tableau_template="{FIXED [{dim_0}], [{dim_1}] : {agg_fn}([{fact}])}",
            confidence=0.82,
        ),
        DimtyPattern(
            name="include_single_dim",
            mstr_shape={"has_dimty": True, "dim_count": 1, "allow_addition": True, "modifier": "include"},
            tableau_template="{INCLUDE [{dim_0}] : {agg_fn}([{fact}])}",
            confidence=0.78,
        ),
        DimtyPattern(
            name="exclude_single_dim",
            mstr_shape={"has_dimty": True, "dim_count": 1, "allow_addition": False, "modifier": "exclude"},
            tableau_template="{EXCLUDE [{dim_0}] : {agg_fn}([{fact}])}",
            confidence=0.20,  # [AUDIT] Demoted from 0.78 — STRUCTURAL BLOCKER
            severity="blocker",
            requires_shelf_validation=True,
            mandatory_review=True,
        ),
        DimtyPattern(
            name="time_offset_lookup",
            mstr_shape={"has_dimty": True, "has_offset": True, "offset_type": "year"},
            tableau_template="LOOKUP({agg_fn}([{fact}]), -{offset_n})",
            confidence=0.10,  # [AUDIT] Demoted from 0.65 — MANDATORY_REVIEW
            severity="blocker",
            mandatory_review=True,
        ),
        # ... extend as golden tests reveal new patterns
    ]
    
    def match(self, ast: ASTNode, dimty: dict) -> Optional[PatternResult]:
        """Find the best matching pattern for this expression."""
        shape = self._extract_shape(ast, dimty)
        for pattern in self.PATTERNS:
            if pattern.matches(shape):
                return PatternResult(
                    tableau_calc=pattern.apply(shape),
                    confidence=pattern.confidence,
                    pattern_name=pattern.name
                )
        return None
```

### Tier 3: Semantic Search

```python
class SemanticSearch:
    """Embedding-based similarity search over previously-translated expressions."""
    
    def __init__(self, embeddings_db_path: str):
        self.embeddings = self._load_embeddings(embeddings_db_path)
    
    def search(self, expression_text: str, threshold: float = 0.85) -> Optional[TranslationResult]:
        """Find the most similar previously-translated expression."""
        query_embedding = self._embed(expression_text)
        best_match, similarity = self._nearest_neighbor(query_embedding)
        
        if similarity >= threshold:
            return TranslationResult(
                tableau_calc=best_match.tableau_calc,
                confidence=similarity * best_match.confidence,
                method="semantic_search",
                reference_expression=best_match.mstr_expression
            )
        return None
```

### Tier 4: LLM Translation

```python
class LLMTranslator:
    """Direct LLM API call for expression translation (last resort)."""
    
    SYSTEM_PROMPT = """You are an expert MicroStrategy to Tableau calculated field translator.

Given a MicroStrategy metric expression with dimensionality (dimty) context,
produce the equivalent Tableau calculated field expression.

CRITICAL RULES:
1. Use valid Tableau calculated field syntax only.
2. FIXED/INCLUDE/EXCLUDE LOD expressions for level metrics.
3. Use LOOKUP() or WINDOW functions for time-based transformations.
4. Do NOT invent fields — only reference fields provided in context.
5. Preserve mathematical equivalence exactly.
6. Return ONLY the Tableau expression, no explanation.

CONTEXT:
- Available dimensions: {dimensions}
- Available measures: {measures}
- Grain context: {grain}
"""

    def translate(self, mstr_expression: str, context: dict) -> LLMResult:
        prompt = self._build_prompt(mstr_expression, context)
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        
        # Check cache first
        if prompt_hash in self.cache:
            return self.cache[prompt_hash]
        
        # Call LLM API
        response = self._call_llm(prompt, max_retries=3)
        
        result = LLMResult(
            tableau_calc=response.calc,
            confidence=response.confidence,
            explanation=response.explanation,
            method="llm"
        )
        
        # Cache result
        self.cache[prompt_hash] = result
        self._save_cache()
        
        return result
```

---

## 5. Compilation Pipeline

```python
class ExpressionCompiler:
    """Main expression compilation pipeline."""
    
    def __init__(self):
        self.parser = MSTRExpressionParser()
        self.rule_compiler = RuleCompiler()
        self.hash_lookup = HashLookup()
        self.pattern_matcher = PatternMatcher()
        self.semantic_search = SemanticSearch()
        self.llm_translator = LLMTranslator()
    
    def compile(self, mstr_metric: dict, context: CompilationContext) -> CompilationResult:
        """Compile an MSTR metric into a Tableau calculated field."""
        
        # Step 1: Parse MSTR expression tree into canonical AST
        ast = self.parser.parse(mstr_metric["expression"])
        dimty = mstr_metric.get("dimty")
        
        # Step 2: Try rule compiler (deterministic)
        rule_result = self.rule_compiler.compile(ast, dimty, context)
        if rule_result and rule_result.confidence >= 0.85:
            return CompilationResult(
                tableau_calc=rule_result.tableau_calc,
                confidence=rule_result.confidence,
                method="rule_compiler",
                ast=ast
            )
        
        # Step 3: 3-Tier fallback
        expr_hash = HashLookup.canonical_hash(ast)
        
        # Tier 1: Hash lookup
        cached = self.hash_lookup.lookup(expr_hash)
        if cached:
            return CompilationResult(
                tableau_calc=cached,
                confidence=0.95,  # high confidence for previously-validated
                method="hash_cache",
                ast=ast
            )
        
        # Tier 2: Pattern match
        pattern_result = self.pattern_matcher.match(ast, dimty)
        if pattern_result:
            return CompilationResult(
                tableau_calc=pattern_result.tableau_calc,
                confidence=pattern_result.confidence,
                method=f"pattern:{pattern_result.pattern_name}",
                ast=ast
            )
        
        # Tier 3: Semantic search
        expr_text = mstr_metric["expression"].get("text", "")
        semantic_result = self.semantic_search.search(expr_text)
        if semantic_result:
            return CompilationResult(
                tableau_calc=semantic_result.tableau_calc,
                confidence=semantic_result.confidence,
                method="semantic_search",
                ast=ast
            )
        
        # Tier 4: LLM
        llm_result = self.llm_translator.translate(expr_text, context.to_dict())
        return CompilationResult(
            tableau_calc=llm_result.tableau_calc,
            confidence=llm_result.confidence,
            method="llm",
            ast=ast,
            requires_review=llm_result.confidence < 0.85
        )
```

---

## 6. Validation & Golden Tests

### Golden Test Structure

```
backend/golden_tests/
    metrics/
        simple_sum.json
        derived_margin.json
        level_metric_year.json
        conditional_metric.json
        yoy_transformation.json
        ...
```

Each golden test file:

```json
{
  "test_name": "level_metric_fixed_year",
  "mstr_expression": {
    "text": "Sum(Revenue){Year}",
    "tree": { "..." },
    "dimty": { "..." }
  },
  "expected_tableau_calc": "{FIXED [Year] : SUM([Revenue])}",
  "acceptable_alternatives": [
    "{ FIXED [Year] : SUM([Revenue]) }"
  ],
  "test_data": {
    "input_rows": [
      {"Year": 2025, "Revenue": 1200},
      {"Year": 2025, "Revenue": 1800},
      {"Year": 2026, "Revenue": 4500}
    ],
    "expected_results": [
      {"Year": 2025, "result": 3000},
      {"Year": 2026, "result": 4500}
    ]
  }
}
```

> **⛔ AUDIT FIX (F2 golden fixture):** Previous fixture used `{Year:2025 → 3000, Year:2026 → 3000}` — both years summed to 3000, making the test **unable to distinguish a correct FIXED from a broken one** (identity bug). Fixed: asymmetric inputs (2025=3000, 2026=4500) so a broken translation that ignores grain or drops offsets produces visibly wrong results.
>
> **Fixture linter mandate:** All golden test fixtures must have **distinct expected values across grain rows**. A fixture where all expected values are identical is a non-test and must be rejected by CI.

### Validation Checks

1. **Syntax validation**: Parse the generated calc with sqlglot (Tableau dialect) or regex-based validator
2. **Semantic equivalence**: Compare against `expected_tableau_calc` and `acceptable_alternatives`
3. **Numeric equivalence** (when `test_data` is provided): Execute both expressions against test data and compare results
4. **Field resolution**: Verify all referenced fields exist in the compilation context

---

## 7. Unsupported Expressions

The following MSTR expression patterns are flagged as `Issue(severity=BLOCKER)`:

| Pattern | Reason | Action |
|---------|--------|--------|
| Training metrics | Excluded from MSTR Modeling API | Review queue |
| Extreme metrics | Excluded from MSTR Modeling API | Review queue |
| Relationship metrics | Excluded from MSTR Modeling API | Review queue |
| `ApplySimple()` with stored procedure call + Hyper path | `RAWSQL()` requires live DB connection; incompatible with Hyper extract | **Blocker immediately** — do NOT attempt RAWSQL |
| `ApplySimple()` with warehouse-specific SQL + Live connection | Non-portable but viable via `RAWSQL()` | Attempt RAWSQL(), else review |
| Recursive metrics | No direct Tableau equivalent | Review queue |
| `ApplyOLAP()` functions | Complex window semantics | Attempt WINDOW_*, else review |
| Custom plugin viz expressions | No standard translation | Review queue |
| Multi-pass aggregation (nested metrics with LODs) | Tableau resolves calcs in single pass; nesting with LODs produces different results | Flag parent `Issue(warning, multi_pass_aggregation)` if any constituent has `confidence < 0.90` |
| Cross-cube compound metrics | Metric references facts/metrics from multiple cubes; single-cube extraction fails | `Issue(blocker, cross_cube_scope)` |
| Custom groups (MSTR set-like qualifiers) | Maps to Tableau Sets/Groups | Extract `customGroupElements` → emit `<group>` XML |
| Derived elements present (Audit v4 Trap B) | Ad-hoc group/sum elements on template | `Issue(blocker, derived_elements_present)` |
| Prompt in condition / filter (Audit v4 Trap C) | Metric condition references prompt | `Issue(blocker, prompt_in_condition)` |
| Dossier multi-dataset blend (Audit v4 Trap D) | Visualization blends multiple cubes | `Issue(blocker, dossier_multi_dataset_blend)` |
| Semi-additive measure (Audit v4 Trap E) | Fact subtotal is not SUM (e.g. LAST) | `Issue(warning, semi_additive_measure)` + rolled grain check |
| Data drift (Audit v4 ADR-030) | Watermark timestamp discrepancy | `Issue(info, data_drift)` |

---

## 8. Building the Pattern Catalog

The pattern catalog grows through three mechanisms:

1. **Manual curation**: Add patterns as you encounter real MSTR metrics in the target estate
2. **Golden test feedback**: When a golden test reveals a working translation, extract the pattern and add it to the catalog
3. **LLM-to-rule promotion**: When the LLM successfully translates an expression and it passes golden tests, analyze the pattern and codify it as a deterministic rule

### Catalog Growth Workflow

```
New MSTR metric encountered
    │
    ├─ Rule compiler handles it? → ✅ Done
    │
    ├─ LLM translates it? → Golden test passes?
    │       │                       │
    │       │                       ├─ Yes → Extract pattern → Add to catalog
    │       │                       └─ No → Review queue
    │       │
    │       └─ LLM fails → Review queue
    │
    └─ Human provides translation → Add to golden tests + catalog
```
