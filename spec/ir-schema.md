# BI-IR JSON Schema Specification — mstr-tableau-migrator

**Companion to:** `architecture.md`  
**Version:** 1.0.0  
**Date:** 17 August 2026  

---

## 1. Schema Overview

The BI Intermediate Representation (BI-IR) is the canonical data model between MSTR extraction and Tableau emission. It is:

- **MSTR-first with extension points** (ADR-001): optimized for MSTR→Tableau, with `vendorExtensions` blocks for future adapters
- **JSON Schema validated**: every IR document conforms to this schema
- **Confidence-scored**: every translated node carries a confidence float
- **Issue-aware**: compilation problems are captured in-band as `Issue` entities

---

## 2. Root Document

```json
{
  "$schema": "https://mstr-tableau-migrator/schemas/bi-ir/v1.0.0.json",
  "irVersion": "1.0.0",
  "source": {
    "vendor": "microstrategy",
    "platform": "strategy-one",
    "projectId": "B7CA92F04B9FAE8D941C3E9B7E0CD754",
    "projectName": "Sales Analytics",
    "serverVersion": "2024.0402.0200",
    "extractedAt": "2026-08-17T14:30:00Z",
    "extractedBy": "mstr-tableau-migrator/0.1.0"
  },
  "target": {
    "vendor": "tableau",
    "serverVersion": "2024.2",
    "templateVersion": "2024.2"
  },
  "model": {
    "tables": [],
    "relationships": [],
    "dimensions": [],
    "measures": [],
    "filters": [],
    "securityPolicies": [],
    "parameters": []
  },
  "content": {
    "datasources": [],
    "worksheets": [],
    "dashboards": [],
    "reports": []
  },
  "lineage": {
    "nodes": [],
    "edges": []
  },
  "issues": [],
  "statistics": {
    "totalObjects": 187,
    "compiledObjects": 175,
    "skippedObjects": 12,
    "averageConfidence": 0.89
  }
}
```

---

## 3. Model Entities

### 3.1 Table

Represents a physical or logical table in the data model.

```json
{
  "id": "table:lu_region",
  "name": "LU_REGION",
  "schema": "dbo",
  "catalog": "SALES_DW",
  "tableType": "dimension",
  "columns": [
    {
      "name": "REGION_ID",
      "dataType": "integer",
      "nullable": false,
      "isPrimaryKey": true
    },
    {
      "name": "REGION_NAME",
      "dataType": "string",
      "nullable": false,
      "isPrimaryKey": false
    },
    {
      "name": "REGION_DESC",
      "dataType": "string",
      "nullable": true,
      "isPrimaryKey": false
    }
  ],
  "provenance": {
    "mstrObjectId": "EA8BF04A4F89...",
    "mstrObjectType": "logical_table",
    "apiEndpoint": "/api/model/tables/EA8BF04A4F89...",
    "extractedAt": "2026-08-17T14:30:05Z"
  },
  "extractionGrain": {
    "physicalGrain": ["date", "customer_id", "product_id", "region_id"],
    "semanticGrain": ["dim:date", "dim:customer", "dim:product", "dim:region"],
    "keys": ["transaction_id"],
    "aggregationState": "raw",
    "snapshotIdentity": null
  },
  "vendorExtensions": {}
}
```

> **Audit v2 (Flaw E — Extraction Grain Contract, ADR-022):** Every table must declare its `extractionGrain`. The `aggregationState` field is critical: `"raw"` means fact-level rows from warehouse-direct extraction; `"pre_aggregated"` means MSTR API result data (used for golden tests only). A calculation requiring grain `[Customer]` against a table with `aggregationState: "pre_aggregated"` at `[Year, Region]` grain must emit `Issue(blocker, insufficient_extraction_grain)`. The `snapshotIdentity` is set when the table data is extracted and used to detect stale/changed data on crash recovery (ADR-016/022).

### 3.2 Relationship

Represents a join/FK relationship between tables.

```json
{
  "id": "rel:region_to_sales",
  "type": "many_to_one",
  "fromTable": "table:fact_sales",
  "fromColumns": ["REGION_ID"],
  "toTable": "table:lu_region",
  "toColumns": ["REGION_ID"],
  "joinModel": "logical_relationship",
  "cardinality": "many_to_one",
  "crossFilter": "single",
  "surrogateKey": null,
  "provenance": {
    "mstrRelationshipType": "one_to_many",
    "mstrParentAttribute": "attr:region",
    "mstrChildAttribute": "attr:sales_record"
  }
}
```

> **Audit fix (Trap 4 — Compound Keys):** `fromColumns` and `toColumns` are **arrays** to support compound attribute keys (e.g., `["CATEGORY_ID", "PRODUCT_ID"]`). Single-column joins use a single-element array. The `joinModel` field specifies `"logical_relationship"` (Tableau noodles model, recommended) or `"physical_join"` (legacy). The Hyper/TDS emitter must generate the correct XML structure for each model.
>
> **New audit fields:** `cardinality` declares join cardinality (`many_to_one`, `one_to_one`, `many_to_many`) for Tableau relationship XML. `crossFilter` specifies Tableau cross-filter direction (`single`|`both`). `surrogateKey` (nullable string) specifies a materialized concatenated key column name for compound keys that cannot be expressed as multi-column joins.

### 3.3 Dimension

Represents an MSTR attribute compiled into a Tableau dimension.

```json
{
  "id": "dim:region",
  "name": "Region",
  "dataType": "string",
  "fields": [
    {
      "name": "Region",
      "role": "display",
      "sourceColumn": "REGION_NAME",
      "sourceTable": "table:lu_region"
    },
    {
      "name": "Region ID",
      "role": "id",
      "sourceColumn": "REGION_ID",
      "sourceTable": "table:lu_region",
      "hidden": true
    }
  ],
  "hierarchy": null,
  "confidence": 0.99,
  "provenance": {
    "mstrObjectId": "8D679D3811D3E4981000E787EC6DE8A4",
    "mstrObjectType": "attribute",
    "mstrForms": ["ID", "DESC"],
    "apiEndpoint": "/api/model/attributes/8D679D3811D3E4981000E787EC6DE8A4"
  },
  "vendorExtensions": {}
}
```

### 3.4 Measure

Represents an MSTR metric compiled into a Tableau calculated field or measure.

```json
{
  "id": "meas:revenue",
  "name": "Revenue",
  "dataType": "number",
  "semanticFingerprint": {
    "fingerprintHash": "sha256:8f434346648f6b96df89dda901c5176b10a6d83961dd3c1ac88b59b2dc327aa4",
    "astHash": "sha256:7f83b165...",
    "sourceDependencies": ["table:fact_sales", "col:fact_sales.revenue"],
    "datasourceDomain": "domain:sales_dw",
    "physicalGrain": ["order_date", "customer_id", "product_id"],
    "semanticGrain": ["dim:date", "dim:customer", "dim:product"],
    "aggregation": "sum",
    "filteringMode": "standard",
    "conditionPhase": "none",
    "transformation": null,
    "nullPolicy": "propagate",
    "zeroDivisionPolicy": "null",
    "securityScope": "sec:region_rls"
  },
  "evaluationPlan": {
    "id": "eval:meas_revenue",
    "sourceMetricId": "28B7F04A4F89C3E45721F...",
    "rowExpression": null,
    "preFilters": [],
    "aggregation": "sum",
    "metricDimensionality": [],
    "filteringMode": "standard",
    "conditionPhase": "none",
    "postAggCondition": null,
    "transformation": null,
    "windowCalc": null,
    "nullPropagation": "propagate",
    "zeroDivisionResult": "null",
    "confidence": 0.99
  },
  "expression": {
    "dialect": "bi-ir",
    "ast": {
      "op": "agg",
      "fn": "sum",
      "field": "fact:revenue"
    },
    "sourceRaw": {
      "vendor": "microstrategy",
      "expressionText": "Sum(Revenue)",
      "expressionTree": { "...MSTR tree JSON..." },
      "tokens": "..."
    },
    "compiledTableau": "SUM([Revenue])"
  },
  "grainHints": [],
  "dimty": null,
  "conditionality": null,
  "scope": "shared",
  "conditionPhase": null,
  "filteringMode": "standard",
  "transformationType": "none",
  "format": {
    "category": "currency",
    "currencySymbol": "$",
    "decimalPlaces": 2,
    "useThousandSeparator": true
  },
  "thresholds": [],
  "confidence": 0.99,
  "translationMethod": "rule_compiler",
  "provenance": {
    "mstrObjectId": "28B7F04A4F89C3E45721F...",
    "mstrObjectType": "metric",
    "apiEndpoint": "/api/model/metrics/28B7F04A4F89C3E45721F..."
  },
  "vendorExtensions": {}
}
```

#### Complex Measure Example (Level Metric → LOD)

```json
{
  "id": "meas:revenue_yoy",
  "name": "Revenue YoY",
  "dataType": "number",
  "expression": {
    "dialect": "bi-ir",
    "ast": {
      "op": "div",
      "args": [
        {"op": "agg", "fn": "sum", "field": "fact:revenue"},
        {
          "op": "lod",
          "lodType": "fixed",
          "grain": ["dim:year"],
          "fn": "sum",
          "field": "fact:revenue",
          "offset": {"year": -1}
        }
      ]
    },
    "sourceRaw": {
      "vendor": "microstrategy",
      "expressionText": "Sum(Revenue) / Sum(Revenue){~+, Year-1}",
      "expressionTree": {}
    },
    "compiledTableau": "SUM([Revenue]) / [Revenue_Prior_Year]"
  },
  "grainHints": ["dim:year", "dim:region"],
  "dimty": {
    "dimensionality": "year",
    "allowAddition": true,
    "filtering": "standard"
  },
  "conditionality": null,
  "grainContract": {
    "allowAddition": true,
    "semiAdditive": false,
    "nullPropagation": "default"
  },
  "transformation": {
    "strategy": "precomputed_column",
    "offset": {"year": -1},
    "grain": ["dim:year"],
    "transformationTableRef": null,
    "precomputedColumnName": "Revenue_Prior_Year"
  },
  "contextFilterRequirements": [],
  "format": {
    "category": "percent",
    "decimalPlaces": 1
  },
  "confidence": 0.72,
  "translationMethod": "ai_llm",
  "provenance": {
    "mstrObjectId": "5A8F3B..."
  },
  "vendorExtensions": {}
}
```

> **Audit fix (F2 — YoY example):** The previous `compiledTableau` was `"SUM([Revenue]) / {FIXED [Year]: SUM([Revenue])}"` — the offset was **dropped**, making it identically 1.0 for all rows. Fixed to reference the pre-computed prior-year column. The `transformation` block specifies the strategy (`precomputed_column` preferred, `shifted_join` alternative, `table_calc_fallback` last resort).
>
> **New fields:**
> - `grainContract`: captures `allowAddition` (semi-additive guard), `semiAdditive` flag (prevents re-aggregation), `nullPropagation` (from MSTR VLDB settings).
> - `transformation`: offset strategy, grain, and reference to transformation table or pre-computed column.
> - `contextFilterRequirements`: array of filter IDs that must be promoted to Tableau context filters for FIXED LODs to produce correct results (output of filter-interaction analysis from F1).

### 3.5 Filter

```json
{
  "id": "filter:east_region",
  "name": "East Region Filter",
  "filterType": "attribute_qualification",
  "predicate": {
    "op": "eq",
    "field": "dim:region",
    "value": "East"
  },
  "compiledTableau": "[Region] = 'East'",
  "confidence": 0.98,
  "provenance": {
    "mstrObjectId": "C2E4F..."
  }
}
```

### 3.6 SecurityPolicy (Audit v4 — ADR-031)

```json
{
  "id": "sec:region_rls",
  "name": "Region Security Filter",
  "policyType": "row_level_security",
  "predicate": {
    "op": "in",
    "field": "dim:region",
    "valueSource": "user_attribute"
  },
  "userGroupBindings": [
    {"mstrGroup": "East Sales Team", "allowedValues": ["East"]},
    {"mstrGroup": "West Sales Team", "allowedValues": ["West"]},
    {"mstrGroup": "All Regions", "allowedValues": ["*"]}
  ],
  "tableauImplementation": {
    "method": "entitlement_table",
    "entitlementDatasource": "ds:entitlements_locked",
    "entitlementTableName": "SECURITY_ENTITLEMENTS",
    "matchColumn": "USERNAME",
    "filterColumn": "ALLOWED_REGION",
    "predicateTemplate": "CONTAINS('|' + [ALLOWED_REGION] + '|', '|' + [Region] + '|')",
    "identityMapRef": "map:mstr_to_tableau_users"
  },
  "confidence": 1.0,
  "provenance": {
    "mstrObjectId": "SEC1...",
    "mstrObjectType": "security_filter"
  }
}
```
    "mstrObjectId": "D3F5A..."
  }
}
```

### 3.7 Parameter (Future)

```json
{
  "id": "param:selected_year",
  "name": "Selected Year",
  "dataType": "integer",
  "allowedValues": [2023, 2024, 2025, 2026],
  "defaultValue": 2026,
  "mstrPromptType": "value_prompt",
  "tableauParameterName": "Selected Year",
  "migrationStatus": "deferred",
  "confidence": 0.0,
  "provenance": {
    "mstrObjectId": "E4G6B..."
  }
}
```

### 3.8 Selector (Audit Addition)

MSTR Selectors are distinct from Prompts — they are in-dossier dimension selectors, not pre-execution prompts. The spec previously conflated them under ADR-013.

```json
{
  "id": "sel:year_selector",
  "name": "Year Selector",
  "selectorType": "attribute_selector",
  "targetAttribute": "dim:year",
  "defaultValue": 2026,
  "multiSelect": false,
  "displayStyle": "dropdown",
  "tableauMapping": "quick_filter",
  "appliesTo": ["ws:revenue_by_region", "ws:cost_by_category"],
  "confidence": 0.80,
  "provenance": {
    "mstrObjectId": "SEL1...",
    "mstrObjectType": "selector",
    "mstrDossierId": "F5H7C...",
    "mstrChapterIndex": 0
  }
}
```
> **Selector Types:** `attribute_selector` (maps to Tableau Quick Filter), `metric_selector` (maps to Tableau Measure Filter), `element_selector` (maps to Tableau Set/Parameter). Selectors with `multiSelect: true` map to multi-select quick filters.

---

## 4. Content Entities

### 4.0 DatasourcePlan (Audit v3 Addition — ADR-028)

Represents the pre-emission topological decision for a datasource.

```json
{
  "id": "dsplan:sales_shared",
  "datasourceId": "ds:shared_sales",
  "mode": "published",
  "artifactType": "hyper_and_tdsx",
  "estimatedSizeBytes": 34603008,
  "stagingPublishPath": "_migration_staging/Datasources/Sales Analytics Shared",
  "productionPublishPath": "Public Objects/Sales/Datasources/Sales Analytics Shared",
  "requiresStandaloneExtract": false,
  "compatibilityDomain": "domain:sales_dw",
  "securityScope": "sec:region_rls"
}
```

### 4.1 Datasource

```json
{
  "id": "ds:shared_sales",
  "name": "Sales Analytics Shared",
  "type": "published",
  "connectionType": "hyper",
  "datasourcePlanId": "dsplan:sales_shared",
  "tables": ["table:fact_sales", "table:lu_region", "table:lu_category", "table:lu_time"],
  "relationships": ["rel:region_to_sales", "rel:category_to_sales", "rel:time_to_sales"],
  "calculatedFields": ["meas:revenue", "meas:cost", "meas:profit_margin", "meas:revenue_yoy"],
  "dimensions": ["dim:region", "dim:category", "dim:year", "dim:quarter", "dim:month"],
  "securityPolicies": ["sec:region_rls"],
  "hyperFilePath": "artifacts/jobs/{job_id}/shared_sales.hyper",
  "tdsFilePath": null,
  "fieldNameMapping": {},
  "provenance": {
    "mstrProjectId": "B7CA92F04B9FAE8D941C3E9B7E0CD754"
  }
}
```

### 4.2 Worksheet (Visual Spec)

```json
{
  "id": "ws:revenue_by_region",
  "name": "Revenue by Region",
  "datasource": "ds:shared_sales",
  "markType": "bar",
  "shelves": {
    "rows": [{"field": "meas:revenue", "aggregation": "sum"}],
    "columns": [{"field": "dim:region"}],
    "color": null,
    "size": null,
    "label": [{"field": "meas:revenue", "aggregation": "sum"}],
    "detail": [],
    "tooltip": [{"field": "meas:revenue"}, {"field": "meas:cost"}]
  },
  "filters": [
    {"field": "dim:year", "filterType": "single_value", "defaultValue": 2026}
  ],
  "viewFilters": [],
  "contextFilterPromotions": [],
  "sorts": [
    {"field": "meas:revenue", "direction": "desc"}
  ],
  "formatting": {
    "headerFontSize": 12,
    "valueFontSize": 10,
    "headerColor": "#333333",
    "valueNumberFormat": "$#,##0"
  },
  "confidence": 0.95,
  "subtotals": false,
  "subtotalWarning": false,
  "provenance": {
    "mstrVisualizationKey": "K1",
    "mstrDossierId": "F5H7C...",
    "mstrChapterIndex": 0,
    "mstrPageIndex": 0
  }
}
```

> **Audit v2 (Trap 7 — Subtotals):** `subtotals: true` when the source MSTR report displayed subtotals. `subtotalWarning: true` when at least one measure on this worksheet has `conditionPhase: "post_agg"` or `transformationType != "none"` — flags to the human reviewer that Tableau subtotal values will differ from MSTR (Tableau re-aggregates underlying data; MSTR uses separate SQL rollup passes). See Validation Rule 12.

### 4.3 Dashboard

```json
{
  "id": "dash:sales_overview",
  "name": "Sales Overview",
  "worksheets": ["ws:revenue_by_region", "ws:cost_by_category", "ws:margin_trend", "ws:kpi_summary"],
  "layout": "auto_tiled",
  "filters": [
    {
      "field": "dim:year",
      "applyTo": ["ws:revenue_by_region", "ws:cost_by_category", "ws:margin_trend"],
      "filterType": "single_value"
    }
  ],
  "actions": [],
  "zones": [],
  "confidence": 0.92,
  "provenance": {
    "mstrDossierId": "F5H7C...",
    "mstrChapterIndex": 0
  }
}
```

### 4.4 Report (Paginated / Grid)

```json
{
  "id": "rep:monthly_financials",
  "name": "Monthly Financial Summary",
  "worksheet": "ws:financial_grid",
  "pageSetup": {
    "orientation": "landscape",
    "paperSize": "letter"
  },
  "confidence": 0.95,
  "provenance": {
    "mstrReportId": "9E8C7A..."
  }
}
```

---

## 5. Lineage Graph

```json
{
  "nodes": [
    {"id": "table:fact_sales", "type": "table", "name": "FACT_SALES"},
    {"id": "meas:revenue", "type": "measure", "name": "Revenue"},
    {"id": "ws:revenue_by_region", "type": "worksheet", "name": "Revenue by Region"}
  ],
  "edges": [
    {"source": "table:fact_sales", "target": "meas:revenue", "type": "FEEDS"},
    {"source": "meas:revenue", "target": "ws:revenue_by_region", "type": "USES"}
  ]
}
```

---

## 6. Issues

```json
{
  "id": "iss:001",
  "objectId": "meas:revenue_yoy",
  "objectType": "measure",
  "severity": "warning",
  "category": "dimty_translation_low_confidence",
  "message": "Level metric with offset required AI fallback translation. Confidence: 0.72",
  "suggestedFix": "Review compiled Tableau expression in Review Queue",
  "autoFixable": false
}
```

### Issue Categories

| Category | Description |
|----------|-------------|
| `unsupported_metric_type` | Training/extreme/relationship metric |
| `unsupported_prompt_type` | Hierarchy/expression/level prompt |
| `dimty_translation_low_confidence` | LOD translation uncertain |
| `ffsql_complex` | FFSQL with stored procs or temp tables |
| `security_filter_complex` | Security predicate uses MSTR-specific functions |
| `rsd_document` | Legacy Report Services Document |
| `api_extraction_failed` | MSTR API returned error for this object |
| `xsd_validation_failed` | Generated TWB XML failed XSD check |
| `numeric_validation_failed` | KPI values don't match within tolerance |
| `formatting_lost` | Complex formatting could not be preserved |
| `stored_proc_incompatible_with_hyper` | `ApplySimple()` with stored procedure; RAWSQL requires live connection, incompatible with Hyper |
| `cross_cube_scope` | Compound metric references metrics from multiple cubes; requires manual Hyper assembly |
| `multi_pass_aggregation` | Nested metrics with LODs/conditionality; Tableau single-pass evaluation may differ from MSTR multi-pass |
| `post_agg_conditionality` | Metric has post-aggregation condition (HAVING-style); pre-agg IF/THEN translation produces wrong results |
| `compound_key_mismatch` | Attribute has compound key; single-column join attempted |
| `context_filter_lod_conflict` | FIXED LOD in worksheet with context filter on same grain dimension |
| `insufficient_extraction_grain` | **[Audit v2]** Calculation requires a grain (e.g., Customer) absent from the extracted dataset. ADR-022 blocker. |
| `subtotal_math_divergence` | **[Audit v2]** Worksheet has subtotals + conditional/transformation metrics; Tableau subtotals will differ from MSTR |
| `exclude_lod_computed_dim` | **[Audit v2]** `EXCLUDE` LOD targets a computed date dimension (DATETRUNC); semantics undefined |
| `cross_db_rawsql` | **[Audit v2]** `ApplySimple()` references cross-schema tables; RAWSQL translation may fail at runtime |
| `semantic_fingerprint_collision` | **[Audit v3]** Measures with identical formula strings but different semantic fingerprints attempted to share a definition |
| `exclude_lod_view_dependent` | **[Audit v3]** EXCLUDE LOD detected; auto-publish prohibited without frozen shelf validation |
| `evaluation_plan_mismatch` | **[Audit v3]** Rendered formula AST diverges from EvaluationPlan semantic contract |
| `derived_elements_present` | **[Audit v4]** Report template contains derived elements / ad-hoc element groups |
| `prompt_in_condition` | **[Audit v4]** Metric conditionality or filter references an MSTR prompt |
| `dossier_multi_dataset_blend` | **[Audit v4]** Visualization blends multiple cubes at differing grains |
| `semi_additive_measure` | **[Audit v4]** Fact has non-SUM subtotal function (e.g. LAST) requiring grain-rollup verification |
| `data_drift` | **[Audit v4]** Numeric variance caused by warehouse timestamp boundary drift |

---

## 7. Validation Rules

1. **Version semver**: `irVersion` must be `1.x.y`. Readers reject major version mismatch.
2. **Acyclic calc graph**: `USES` edges between measures must form a DAG (unless explicitly flagged).
3. **Field resolution**: Every shelf field in a worksheet must resolve to a dimension, measure, or calculated field in the referenced datasource.
4. **Security policy references**: Every security policy must reference existing dimensions.
5. **Unique IDs**: All entity IDs must be unique within the document.
6. **Confidence range**: All `confidence` values must be in `[0.0, 1.0]`.
7. **Provenance required**: Every entity must have a `provenance` object tracing back to the source.
8. **Local scope binding**: For every `Measure` with `scope: "local"`, the containing `Datasource` must be a published datasource reference (not embedded). Local measures are emitted as workbook-level calculated fields referencing the shared published datasource.
9. **Compound join parity**: For every `Relationship`, `fromColumns.length` must equal `toColumns.length`.
10. **No context-filter/LOD conflicts**: For every worksheet containing a `{FIXED}` LOD calc, no filter in that worksheet's filter mappings may have `action="include"` on the same dimension as the `FIXED` grain. Emit `Issue(warning, context_filter_lod_conflict)` if detected.
11. **Nested metric aggregation safety**: If a `Measure` references another `Measure` via `fieldRef` in its AST, and any constituent measure has `confidence < 0.90` or `translationMethod != "rule_compiler"`, flag the parent with `Issue(warning, multi_pass_aggregation)`.
12. **Subtotal math divergence (Audit v2):** For every `Worksheet` with `subtotals: true` and at least one `Measure` with `conditionPhase: 'post_agg'` or `transformationType != 'none'`, emit `Issue(warning, subtotal_math_divergence)`. Subtotal values in Tableau for these measures are computed by re-aggregating underlying data and will differ from MSTR's subtotal values.
13. **Extraction grain sufficiency (Audit v2, ADR-022):** For every `Measure` with an LOD expression (op: `lod`) referencing a grain dimension, verify that the datasource's underlying table has that dimension in its `extractionGrain.physicalGrain`. If absent, emit `Issue(blocker, insufficient_extraction_grain)`.
14. **Semantic fingerprint parity (Audit v3, ADR-027):** For any two `Measure` entities sharing a published datasource definition with `scope: "shared"`, their `semanticFingerprint` hashes must be identical. If fingerprints differ, emit `Issue(blocker, semantic_fingerprint_collision)` and force `scope: "local"`.
15. **EvaluationPlan consistency (Audit v3):** For every `Measure`, the `evaluationPlan` must be structurally consistent with the expression AST (matching aggregation operator and condition phase). If mismatched, emit `Issue(blocker, evaluation_plan_mismatch)`.
16. **Entitlement substring safety (Audit v4, ADR-031):** Every entitlement predicate must wrap operands in delimiter tokens (`CONTAINS("|" + [ALLOWED_VALUES] + "|", "|" + [Dimension] + "|")`). Assert that no unescaped delimiter character exists within raw dimension values.
17. **Template version ceiling (Audit v4):** `template_version <= server_version`. Reject jobs where template version exceeds the detected Tableau Server target version.
18. **Mandatory review blocks auto-publish (Audit v4):** If any `Measure` within a wave carries a `MANDATORY_REVIEW` flag or view-dependent LOD (e.g. `EXCLUDE`), `ValidationScorecard.mandatory_review_flags` must be > 0 and `auto_publish_ok` must evaluate to `False`.
19. **Semi-additive rollup verification (Audit v4):** For every `Measure` where `grainContract.semiAdditive == True`, the scorecard must contain a passed `semi_additive_rollup` check comparing rolled time-grain values against MSTR ground truth.
20. **Mandatory Extraction Grain Invariant (Audit v5):** No Hyper table may be emitted without a validated `ExtractionGrain`. No Tableau LOD calculation may reference a table whose physical grain is insufficient to evaluate that LOD (`insufficient_extraction_grain` = BLOCKER).
21. **Heterogeneous Fact Grain Isolation (Audit v5, ADR-032):** Facts with differing physical grains (e.g. daily sales vs monthly budget) must never be joined on partial dimension keys alone. Unproven multi-fact joins must be emitted as separate logical tables in the relationship model or flagged as `heterogeneous_fact_grain_join` (BLOCKER).

---

## 8. Compilation Context & Caption Registry Schemas

### 8.1 CompilationContext Schema
```json
{
  "nullPolicy": "propagate | ignore | zero",
  "zeroDivisionPolicy": "null | zero",
  "filterSemantics": "pre_aggregation | post_aggregation",
  "lodSemantics": "fixed | include | exclude",
  "sourceGrain": ["dim:date", "dim:customer", "dim:product"],
  "targetGrain": ["dim:year", "dim:region"],
  "interactingFilters": ["filter:region_east"]
}
```

### 8.2 CaptionRegistryEntry Schema
```json
{
  "caption": "Profit Margin",
  "fingerprintHash": "sha256:8f434346648f...",
  "scope": "shared | local",
  "datasourceId": "ds:shared_sales",
  "tableauFieldName": "Calculation_Profit_Margin_2",
  "sourceObjectIds": ["meas:profit_margin_dossier_b"],
  "collisionIndex": 2
}
```

---

## 9. Expression AST Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `agg` | Aggregation function | `{"op": "agg", "fn": "sum", "field": "fact:revenue"}` |
| `lod` | Level of Detail (FIXED/INCLUDE/EXCLUDE) | `{"op": "lod", "lodType": "fixed", "grain": [...], ...}` |
| `arith` | Arithmetic (+, -, *, /) | `{"op": "arith", "fn": "div", "args": [...]}` |
| `cond` | Conditional (IF/CASE) | `{"op": "cond", "test": {...}, "then": {...}, "else": {...}}` |
| `comp` | Comparison (=, !=, >, <, etc.) | `{"op": "comp", "fn": "gt", "args": [...]}` |
| `logic` | Logical (AND, OR, NOT) | `{"op": "logic", "fn": "and", "args": [...]}` |
| `func` | Built-in function | `{"op": "func", "fn": "datepart", "args": [...]}` |
| `literal` | Literal value | `{"op": "literal", "value": 100, "dataType": "number"}` |
| `fieldRef` | Field reference | `{"op": "fieldRef", "field": "dim:region"}` |
| `window` | Window function (table calc) | `{"op": "window", "fn": "running_sum", ...}` |
