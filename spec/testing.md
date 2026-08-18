# Testing Strategy Specification — mstr-tableau-migrator

**Companion to:** `architecture.md`, `agents.md`, `expression-compiler.md`  
**Date:** 17 August 2026  

---

## 1. Testing Layers

| Layer | Scope | Priority | When to Build |
|-------|-------|----------|---------------|
| **Unit tests** | Expression compiler patterns, IR validation, AST parsing | P0 — Critical | During expression compiler development |
| **Integration tests** | MSTR API client against live environment | P0 — Critical | During discovery/semantic agent development |
| **Golden test suite** | Curated MSTR metrics → known-correct Tableau calcs | P0 — Critical | Before compiler is trusted |
| **End-to-end smoke test** | Extract → compile → emit TWB → XSD validate | P1 — High | After pipeline is connected |
| **Snapshot tests** | Generated TWB XML regression detection | P2 — Medium | After emitter stabilizes |
| **Performance benchmarks** | Extraction throughput, compilation time | P3 — Low | Before scaling |

---

## 2. Unit Tests — Expression Compiler

### 2.1 Test Structure

```
backend/tests/
    unit/
        test_expression_parser.py       # MSTR tree/token → canonical AST
        test_rule_compiler.py           # Deterministic pattern matching
        test_pattern_matcher.py         # Dimty→LOD pattern catalog
        test_hash_lookup.py             # Expression cache
        test_ir_validator.py            # BI-IR schema validation
        test_ast_canonical_hash.py      # Deterministic hashing
        test_tableau_calc_syntax.py     # Syntax validation of output
        test_mstr_function_map.py       # MSTR→Tableau function mapping
```

### 2.2 Expression Parser Tests

```python
# backend/tests/unit/test_expression_parser.py

import pytest
from app.services.expression.parser import MSTRExpressionParser

parser = MSTRExpressionParser()


class TestSimpleAggregations:
    def test_sum_fact(self):
        tree = {
            "type": "operator",
            "function": "sum",
            "children": [
                {"type": "object_reference", "objectId": "FA1...", "name": "Revenue"}
            ]
        }
        ast = parser.parse_tree(tree)
        assert ast.op == "agg"
        assert ast.fn == "sum"
        assert ast.field == "fact:revenue"

    def test_count_distinct(self):
        tree = {
            "type": "operator",
            "function": "count",
            "distinct": True,
            "children": [
                {"type": "object_reference", "objectId": "AT1...", "name": "Customer"}
            ]
        }
        ast = parser.parse_tree(tree)
        assert ast.op == "agg"
        assert ast.fn == "countd"

    def test_nested_arithmetic(self):
        """Sum(Profit) / Sum(Revenue) → div(agg(sum, profit), agg(sum, revenue))"""
        tree = {
            "type": "operator",
            "function": "divide",
            "children": [
                {"type": "operator", "function": "sum",
                 "children": [{"type": "object_reference", "name": "Profit"}]},
                {"type": "operator", "function": "sum",
                 "children": [{"type": "object_reference", "name": "Revenue"}]}
            ]
        }
        ast = parser.parse_tree(tree)
        assert ast.op == "arith"
        assert ast.fn == "div"
        assert len(ast.args) == 2


class TestTokenParser:
    def test_simple_sum_tokens(self):
        tokens = [
            {"type": "function", "value": "Sum"},
            {"type": "character", "value": "("},
            {"type": "object", "value": "Revenue", "objectId": "FA1..."},
            {"type": "character", "value": ")"},
        ]
        ast = parser.parse_tokens(tokens)
        assert ast.op == "agg"
        assert ast.fn == "sum"

    def test_dimty_tokens(self):
        tokens = [
            {"type": "function", "value": "Sum"},
            {"type": "character", "value": "("},
            {"type": "object", "value": "Revenue"},
            {"type": "character", "value": ")"},
            {"type": "level", "value": "{Year}"},
        ]
        ast = parser.parse_tokens(tokens)
        assert ast.op == "lod"
        assert ast.lod_type == "fixed"
        assert "dim:year" in ast.grain
```

### 2.3 Rule Compiler Tests

```python
# backend/tests/unit/test_rule_compiler.py

import pytest
from app.services.expression.compiler import ExpressionCompiler


class TestSimpleMetrics:
    @pytest.mark.parametrize("mstr_fn,tableau_fn", [
        ("sum", "SUM"), ("avg", "AVG"), ("count", "COUNT"),
        ("min", "MIN"), ("max", "MAX"), ("median", "MEDIAN"),
    ])
    def test_simple_aggregation(self, mstr_fn, tableau_fn):
        compiler = ExpressionCompiler()
        result = compiler.compile_simple_agg(mstr_fn, "Revenue")
        assert result.tableau_calc == f"{tableau_fn}([Revenue])"
        assert result.confidence >= 0.99

    def test_count_distinct(self):
        compiler = ExpressionCompiler()
        result = compiler.compile_simple_agg("countd", "Customer")
        assert result.tableau_calc == "COUNTD([Customer])"


class TestDerivedMetrics:
    def test_division(self):
        compiler = ExpressionCompiler()
        ast = ASTNode(op="arith", fn="div", args=[
            ASTNode(op="agg", fn="sum", field="fact:profit"),
            ASTNode(op="agg", fn="sum", field="fact:revenue"),
        ])
        result = compiler.compile(ast, dimty=None, context=mock_context)
        assert result.tableau_calc == "SUM([Profit]) / SUM([Revenue])"
        assert result.confidence >= 0.95

    def test_percentage_change(self):
        compiler = ExpressionCompiler()
        # (A - B) / B
        ast = ASTNode(op="arith", fn="div", args=[
            ASTNode(op="arith", fn="sub", args=[
                ASTNode(op="agg", fn="sum", field="fact:current"),
                ASTNode(op="agg", fn="sum", field="fact:previous"),
            ]),
            ASTNode(op="agg", fn="sum", field="fact:previous"),
        ])
        result = compiler.compile(ast, dimty=None, context=mock_context)
        assert "(SUM([Current]) - SUM([Previous])) / SUM([Previous])" in result.tableau_calc


class TestLevelMetrics:
    def test_fixed_single_dimension(self):
        """Sum(Revenue){Year} → {FIXED [Year] : SUM([Revenue])}"""
        compiler = ExpressionCompiler()
        ast = ASTNode(op="agg", fn="sum", field="fact:revenue")
        dimty = {"dimtyUnits": [{"target": {"name": "Year"}, "groupBy": True}], "allowAddition": False}
        result = compiler.compile(ast, dimty=dimty, context=mock_context)
        assert result.tableau_calc == "{FIXED [Year] : SUM([Revenue])}"
        assert result.confidence >= 0.78

    def test_fixed_multi_dimension(self):
        """Sum(Revenue){Year, Region} → {FIXED [Year], [Region] : SUM([Revenue])}"""
        compiler = ExpressionCompiler()
        ast = ASTNode(op="agg", fn="sum", field="fact:revenue")
        dimty = {
            "dimtyUnits": [
                {"target": {"name": "Year"}, "groupBy": True},
                {"target": {"name": "Region"}, "groupBy": True},
            ],
            "allowAddition": False
        }
        result = compiler.compile(ast, dimty=dimty, context=mock_context)
        assert "{FIXED [Year], [Region] : SUM([Revenue])}" in result.tableau_calc

    def test_report_level_no_lod(self):
        """Sum(Revenue){~+} → SUM([Revenue]) (no LOD needed at report level)"""
        compiler = ExpressionCompiler()
        ast = ASTNode(op="agg", fn="sum", field="fact:revenue")
        dimty = {"dimtyUnits": [], "allowAddition": True}
        result = compiler.compile(ast, dimty=dimty, context=mock_context)
        assert result.tableau_calc == "SUM([Revenue])"
        assert result.confidence >= 0.95


class TestFunctionMapping:
    @pytest.mark.parametrize("mstr_func,expected_tableau", [
        ("Concat", "+"),
        ("Length", "LEN"),
        ("Upper", "UPPER"),
        ("Lower", "LOWER"),
        ("Trim", "TRIM"),
        ("NullToZero", "ZN"),
        ("CurrentDate", "TODAY()"),
    ])
    def test_function_mapping(self, mstr_func, expected_tableau):
        compiler = ExpressionCompiler()
        result = compiler.map_function(mstr_func)
        assert expected_tableau in result
```

### 2.4 IR Validator Tests

```python
# backend/tests/unit/test_ir_validator.py

import pytest
from app.services.ir.validator import IRValidator


class TestIRValidation:
    def test_valid_ir_passes(self, sample_valid_ir):
        validator = IRValidator()
        result = validator.validate(sample_valid_ir)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_missing_field_reference_fails(self):
        """Worksheet referencing a field not in the datasource should fail."""
        ir = build_ir_with_missing_field()
        validator = IRValidator()
        result = validator.validate(ir)
        assert result.valid is False
        assert any("field resolution" in e.message for e in result.errors)

    def test_cyclic_calc_graph_detected(self):
        """Circular measure dependencies should be detected."""
        ir = build_ir_with_cycle()
        validator = IRValidator()
        result = validator.validate(ir)
        assert any("cyclic" in e.message.lower() for e in result.errors)

    def test_confidence_out_of_range_fails(self):
        ir = build_ir_with_confidence(1.5)
        validator = IRValidator()
        result = validator.validate(ir)
        assert result.valid is False

    def test_security_policy_references_existing_dimension(self, sample_valid_ir):
        validator = IRValidator()
        result = validator.validate(sample_valid_ir)
        # All security policies should reference valid dimensions
        assert result.valid is True
```

---

## 3. Integration Tests — MSTR API Client

### 3.1 Test Structure

```
backend/tests/
    integration/
        test_mstr_auth.py              # Login / session management
        test_mstr_discovery.py         # Folder walk, object search
        test_mstr_attributes.py        # Attribute extraction
        test_mstr_metrics.py           # Metric extraction (tree + tokens)
        test_mstr_dossiers.py          # Dossier definition extraction
        test_mstr_cubes.py             # Cube definition + data extraction
        test_mstr_filters.py           # Filter extraction
        test_mstr_security.py          # Security filter extraction
        conftest.py                    # Fixtures with live MSTR credentials
```

### 3.2 Configuration

```python
# backend/tests/integration/conftest.py

import pytest
import os

@pytest.fixture(scope="session")
def mstr_config():
    """Requires MSTR_* env vars to be set for integration tests."""
    return {
        "base_url": os.environ["MSTR_BASE_URL"],
        "username": os.environ["MSTR_USERNAME"],
        "password": os.environ["MSTR_PASSWORD"],
        "project_id": os.environ["MSTR_PROJECT_ID"],
    }

@pytest.fixture(scope="session")
def mstr_client(mstr_config):
    from app.services.mstr_client.client import MSTRClient
    client = MSTRClient(**mstr_config)
    client.login()
    yield client
    client.logout()
```

### 3.3 Example Tests

```python
# backend/tests/integration/test_mstr_auth.py

class TestMSTRAuth:
    def test_login_succeeds(self, mstr_config):
        client = MSTRClient(**mstr_config)
        token = client.login()
        assert token is not None
        assert len(token) > 0
        client.logout()

    def test_login_bad_credentials_fails(self, mstr_config):
        client = MSTRClient(
            base_url=mstr_config["base_url"],
            username="bad_user",
            password="bad_pass",
            project_id=mstr_config["project_id"],
        )
        with pytest.raises(AuthenticationError):
            client.login()

    def test_session_renewal(self, mstr_client):
        """Verify the client can renew an expired session."""
        # Simulate expiry by invalidating token
        mstr_client._token = "expired_token"
        # Next API call should auto-renew
        result = mstr_client.get_server_info()
        assert result is not None


# backend/tests/integration/test_mstr_metrics.py

class TestMSTRMetricExtraction:
    def test_extract_simple_metric(self, mstr_client, known_metric_id):
        metric = mstr_client.get_metric(known_metric_id, expression_format="tree")
        assert metric["information"]["name"] is not None
        assert "expression" in metric
        assert "tree" in metric["expression"]

    def test_extract_metric_dimty(self, mstr_client, known_level_metric_id):
        metric = mstr_client.get_metric(known_level_metric_id, expression_format="tree")
        assert "dimty" in metric
        assert "dimtyUnits" in metric["dimty"]

    def test_extract_blocked_metric_type(self, mstr_client, training_metric_id):
        """Training metrics should return an error or empty expression."""
        with pytest.raises(UnsupportedMetricError):
            mstr_client.get_metric(training_metric_id)
```

### 3.4 Running Integration Tests

```bash
# Set environment variables
export MSTR_BASE_URL="https://env-xxxxx.customer.cloud.microstrategy.com/MicroStrategyLibrary"
export MSTR_USERNAME="service_account"
export MSTR_PASSWORD="..."
export MSTR_PROJECT_ID="B7CA92F04B9FAE8D941C3E9B7E0CD754"

# Run integration tests only
pytest backend/tests/integration/ -v --tb=short

# Run with specific marker
pytest -m integration -v
```

### 3.5 Staging Publish & Semantic Validation Integration Test (ADR-017 / Audit F5)

```python
# backend/tests/integration/test_staged_publish.py

import pytest
from app.agents.publisher import PublishAgent
from app.agents.validation import ValidationAgent

@pytest.mark.integration
async def test_staged_publish_and_crosstab_validation(sample_twbx_path, tableau_config):
    """Verify semantic validity by publishing to _migration_staging,
    exporting rendered crosstab data via REST API, and cleaning up.
    """
    # 1. Publish to staging project
    staging_wb = await PublishAgent.publish_to_staging(
        sample_twbx_path, 
        project_name="_migration_staging"
    )
    assert staging_wb.id is not None
    
    try:
        # 2. Query rendered view data via Tableau Server REST API
        view_data = await ValidationAgent.fetch_rendered_crosstab(staging_wb.default_view_id)
        assert len(view_data.rows) > 0
        assert "Revenue" in view_data.columns
        
        # 3. Assert numeric KPI parity against golden values
        assert abs(view_data.get_kpi("Revenue") - 4000.0) < 0.01
    finally:
        # 4. Teardown: delete workbook from staging
        await PublishAgent.delete_staging_workbook(staging_wb.id)
```

---

## 4. Golden Test Suite

### 4.1 Purpose

A curated set of real MSTR metrics from the target estate with manually-verified correct Tableau calculated field translations. This is the **ground truth** for compiler correctness.

### 4.2 Structure

```
backend/golden_tests/
    metrics/
        001_simple_sum_revenue.json
        002_simple_avg_price.json
        003_derived_profit_margin.json
        004_derived_percentage_change.json
        005_conditional_filtered_revenue.json
        006_level_fixed_year.json
        007_level_fixed_year_region.json
        008_level_include_quarter.json
        009_level_exclude_year.json
        010_transformation_yoy.json
        011_nested_level_metric.json
        012_case_statement.json
        013_null_handling.json
        014_string_function.json
        015_date_function.json
        ...
    README.md                         # How to add new golden tests
```

### 4.3 Golden Test File Format

```json
{
  "id": "006_level_fixed_year",
  "description": "Level metric fixed at Year grain",
  "mstr_metric": {
    "name": "Revenue by Year",
    "mstr_id": "28B7F04A4F89...",
    "expression_text": "Sum(Revenue){Year}",
    "expression_tree": {
      "type": "operator",
      "function": "sum",
      "children": [
        {"type": "object_reference", "name": "Revenue", "objectId": "FA1..."}
      ]
    },
    "dimty": {
      "dimtyUnits": [
        {"target": {"objectId": "AT1...", "name": "Year"}, "groupBy": true}
      ],
      "allowAddition": false
    }
  },
  "expected_tableau_calc": "{FIXED [Year] : SUM([Revenue])}",
  "acceptable_alternatives": [
    "{ FIXED [Year] : SUM([Revenue]) }",
    "{FIXED [Year]: SUM([Revenue])}"
  ],
  "minimum_confidence": 0.75,
  "context": {
    "dimensions": ["Year", "Region", "Category"],
    "measures": ["Revenue", "Cost", "Profit"]
  },
  "numeric_test": {
    "input_data": [
      {"Year": 2024, "Region": "East", "Revenue": 1000},
      {"Year": 2024, "Region": "West", "Revenue": 2000},
      {"Year": 2025, "Region": "East", "Revenue": 1500},
      {"Year": 2025, "Region": "West", "Revenue": 2500}
    ],
    "expected_results": {
      "description": "Revenue summed at Year grain, regardless of Region",
      "rows": [
        {"Year": 2024, "expected_value": 3000},
        {"Year": 2025, "expected_value": 4000}
      ]
    }
  },
  "tags": ["level_metric", "fixed_lod", "single_dimension"]
}
```

### 4.4 Fixture Linter & Integrity Mandate (Audit Addition)

> **⛔ AUDIT FIX (F2 Golden Bug Prevention):**
> All golden test fixtures must pass the **Fixture Linter** before inclusion in CI:
> 1. **Asymmetric input data:** Fixtures must use distinct input values per group/time-period (e.g. Year 2024 = 3000, Year 2025 = 4000). Fixtures where all expected values are identical across grain rows are rejected because they cannot detect identity/offset-dropping bugs.
> 2. **Interacting filter scenario:** For `{FIXED}` LOD tests, at least one test case must include an active dimension filter at a lower grain to verify that context filter requirements are properly flagged.
> 3. **Suite versioning:** Every test file metadata carries `golden_suite_version: "1.1.0"`. Cache entries in `expression_cache` are invalidated when this version increments.

### 4.4 Golden Test Runner

```python
# backend/tests/golden/test_golden_metrics.py

import json
import glob
import pytest
from app.services.expression.compiler import ExpressionCompiler

GOLDEN_DIR = "backend/golden_tests/metrics/"


def load_golden_tests():
    tests = []
    for path in sorted(glob.glob(f"{GOLDEN_DIR}*.json")):
        with open(path) as f:
            tests.append(json.load(f))
    return tests


@pytest.mark.parametrize("golden", load_golden_tests(), ids=lambda g: g["id"])
def test_golden_metric(golden):
    compiler = ExpressionCompiler()
    
    # Build context
    context = CompilationContext(
        dimensions=golden.get("context", {}).get("dimensions", []),
        measures=golden.get("context", {}).get("measures", []),
    )
    
    # Compile
    result = compiler.compile(
        mstr_metric=golden["mstr_metric"],
        context=context
    )
    
    # Check calc matches expected or alternatives
    expected = [golden["expected_tableau_calc"]] + golden.get("acceptable_alternatives", [])
    normalized = [normalize_whitespace(e) for e in expected]
    actual_normalized = normalize_whitespace(result.tableau_calc)
    
    assert actual_normalized in normalized, (
        f"Expected one of: {expected}\n"
        f"Got: {result.tableau_calc}"
    )
    
    # Check confidence meets minimum
    min_conf = golden.get("minimum_confidence", 0.5)
    assert result.confidence >= min_conf, (
        f"Confidence {result.confidence} below minimum {min_conf}"
    )


def normalize_whitespace(s: str) -> str:
    """Normalize whitespace for comparison."""
    return " ".join(s.split()).strip()
```

### 4.5 Growing the Golden Test Suite

**Process:**

1. Extract a metric from the live MSTR environment
2. Manually determine the correct Tableau calc translation
3. Write a golden test JSON file
4. Run the golden suite — if the compiler gets it right, great; if not, improve the compiler
5. Commit the test — it guards against regressions

**Target:** Start with 20 golden tests covering the most common patterns, grow to 100+ as the compiler matures.

---

## 5. End-to-End Smoke Tests

### 5.1 Purpose

Verify the full pipeline works: MSTR extraction → IR compilation → Hyper generation → TWB emission → XSD validation → (optionally) publish to Tableau Server.

### 5.2 Test Structure

```
backend/tests/
    e2e/
        test_single_dossier_migration.py
        test_single_report_migration.py
        test_twb_xsd_validation.py
        test_hyper_generation.py
        test_publish_and_verify.py
```

### 5.3 Example E2E Test

```python
# backend/tests/e2e/test_single_dossier_migration.py

import pytest
from app.services.pipeline.orchestrator import MigrationOrchestrator

@pytest.mark.e2e
class TestSingleDossierMigration:
    
    def test_extract_compile_emit(self, mstr_config, known_dossier_id, tmp_path):
        """Full pipeline: extract a known dossier, compile to IR, emit TWB."""
        spec = MigrationJobSpec(
            mstr=mstr_config,
            tableau={"server_url": "", "site_id": "", ...},  # skip publish
            options={
                "template_version": "2024.2",
                "scope": {"specific_object_ids": [known_dossier_id]},
                "auto_publish": False,  # don't publish, just emit
            }
        )
        
        orchestrator = MigrationOrchestrator(spec, job_id="test-e2e")
        result = orchestrator.run_sync()
        
        # Assert pipeline completed
        assert result.status == "COMPLETE"
        
        # Assert TWB was generated
        twbx_files = list(tmp_path.glob("*.twbx"))
        assert len(twbx_files) >= 1
        
        # Assert XSD validation passed
        assert result.structural_score >= 0.99
        
        # Assert numeric score
        assert result.numeric_score >= 0.90

    def test_twb_opens_structurally(self, generated_twbx_path):
        """Verify the TWB XML is well-formed and passes XSD."""
        from app.services.tableau.xsd_validator import validate_twb
        
        result = validate_twb(generated_twbx_path)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_hyper_has_correct_row_count(self, mstr_client, generated_hyper_path, known_cube_id):
        """Verify Hyper extract row count matches MSTR cube."""
        from tableauhyperapi import HyperProcess, Connection, Telemetry
        
        # Get MSTR row count
        mstr_data = mstr_client.get_cube_data(known_cube_id)
        mstr_rows = len(mstr_data.rows)
        
        # Get Hyper row count
        with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA) as hyper:
            with Connection(hyper.endpoint, generated_hyper_path) as conn:
                result = conn.execute_scalar_query("SELECT COUNT(*) FROM main_table")
                hyper_rows = result
        
        assert hyper_rows == mstr_rows
```

### 5.4 Critical Architecture Tests (Audit v2 Addition)

> **⛔ These test categories are ABSENT from the original spec and must be implemented before production use.**

#### 5.4a Multi-Workbook Shared Datasource Collision Tests

```python
# backend/tests/e2e/test_shared_datasource_collision.py

@pytest.mark.e2e
class TestSharedDatasourceCollision:

    def test_local_metrics_same_name_no_collision(self, two_dossier_ir):
        """Two dossiers with scope:'local' metrics named 'Revenue' must NOT
        overwrite each other's <column> definitions in the shared datasource XML."""
        emitter = TableauEmitter()
        twb_a = emitter.emit(two_dossier_ir.dossier_a, target_environment="production")
        twb_b = emitter.emit(two_dossier_ir.dossier_b, target_environment="production")
        
        # Shared datasource should contain only 'shared' metrics
        ds_columns = parse_datasource_columns(two_dossier_ir.shared_ds)
        local_a = [c for c in ds_columns if c.caption == "Revenue" and c.scope == "local"]
        assert len(local_a) == 0, "Local metrics must NOT appear on shared datasource"

    def test_caption_registry_global_consistency(self, two_dossier_ir):
        """Caption registry must be global per datasource. Two workbooks referencing
        the same shared datasource must use the same caption-to-field mapping."""
        registry = CaptionRegistry.load(two_dossier_ir.job_id, two_dossier_ir.shared_ds_id)
        
        # Both workbooks should resolve 'Revenue' to the same ir_id
        assert registry.resolve("Revenue") == "meas:revenue"
```

#### 5.4b Staging/Production Path Rewrite Tests

```python
# backend/tests/e2e/test_path_rewrite.py

@pytest.mark.e2e
class TestStagingProductionPathRewrite:

    def test_staging_twb_has_staging_path(self, sample_ir, staging_config):
        """TWB emitted with target_environment='staging' must reference the
        staging project datasource path, not the production path."""
        emitter = TableauEmitter()
        twb = emitter.emit(sample_ir, target_environment="staging")
        
        connections = parse_connections(twb)
        for conn in connections:
            assert "_migration_staging" in conn.dbname, \
                f"Staging TWB references non-staging path: {conn.dbname}"

    def test_production_twb_has_production_path(self, sample_ir, production_config):
        """TWB emitted with target_environment='production' must reference the
        production project datasource path."""
        emitter = TableauEmitter()
        twb = emitter.emit(sample_ir, target_environment="production")
        
        connections = parse_connections(twb)
        for conn in connections:
            assert "_migration_staging" not in conn.dbname, \
                f"Production TWB references staging path: {conn.dbname}"
```

#### 5.4c Pre-Aggregated Data Detection Tests

```python
# backend/tests/e2e/test_extraction_grain.py

@pytest.mark.e2e
class TestExtractionGrainSafety:

    def test_mstr_api_data_flagged_as_pre_aggregated(self, mock_mstr_api_response):
        """Data from MSTR JSON Data API must be flagged as 'pre_aggregated'
        and NEVER used as Hyper extract source for production."""
        grain = ExtractionGrainAnalyzer.analyze(mock_mstr_api_response)
        assert grain.aggregation_state == "pre_aggregated"

    def test_pre_aggregated_data_blocks_lod_calc(self, pre_agg_table_ir, lod_measure):
        """A FIXED LOD calc targeting a grain absent from pre-aggregated data
        must emit Issue(blocker, insufficient_extraction_grain)."""
        validator = IRValidator()
        issues = validator.validate_grain_sufficiency(lod_measure, pre_agg_table_ir)
        
        blockers = [i for i in issues if i.severity == "blocker"]
        assert len(blockers) > 0
        assert any("insufficient_extraction_grain" in b.category for b in blockers)

    def test_warehouse_direct_data_is_raw_grain(self, warehouse_query_result):
        """Data from warehouse-direct extraction must be flagged as 'raw'
        and contain physical FK columns for star-schema joins."""
        grain = ExtractionGrainAnalyzer.analyze(warehouse_query_result)
        assert grain.aggregation_state == "raw"
        assert len(grain.keys) > 0, "Raw extraction must have key columns"
```

#### 5.4d Column Topo-Sort Tests

```python
# backend/tests/unit/test_column_toposort.py

class TestColumnTopoSort:

    def test_calc_dependencies_ordered(self, sample_datasource_ir):
        """Calculated fields that reference other calcs must appear AFTER
        their dependencies in the emitted <column> sequence."""
        emitter = TableauEmitter()
        columns = emitter._topo_sort_columns(sample_datasource_ir)
        
        seen = set()
        for col in columns:
            for dep in col.dependencies:
                assert dep in seen, \
                    f"Column '{col.name}' appears before dependency '{dep}'"
            seen.add(col.id)
```

#### 5.4e PhysicalModelPlanner Compiler Tests (Audit v3 Addition)

```python
# backend/tests/unit/test_physical_model_planner.py

class TestPhysicalModelPlanner:

    def test_fact_expression_compiles_to_warehouse_sql(self, mock_mstr_fact_bundle, mock_db_schema):
        """MSTR fact expression (e.g. CASE WHEN status='POSTED' THEN net_amount END)
        must compile to valid ANSI/dialect warehouse SQL AST."""
        planner = PhysicalModelPlanner(mock_mstr_fact_bundle, mock_db_schema)
        plan = planner.plan()
        
        table_plan = plan.table_plans[0]
        assert "CASE WHEN" in table_plan.extract_sql
        assert "status = 'POSTED'" in table_plan.extract_sql
        assert table_plan.expected_grain == ["date", "customer_id", "product_id"]

    def test_compound_attribute_form_creates_composite_keys(self, mock_mstr_compound_attr):
        """Attribute with multiple ID forms must generate composite join keys in SQL AST."""
        planner = PhysicalModelPlanner(mock_mstr_compound_attr)
        plan = planner.plan()
        
        join_edge = plan.join_graph[0]
        assert len(join_edge.from_columns) == len(join_edge.to_columns)
        assert len(join_edge.from_columns) >= 2, "Compound attribute must generate multi-column join"
```

#### 5.4f SemanticFingerprint Collision & Deduplication Tests (Audit v3 Addition)

```python
# backend/tests/unit/test_semantic_fingerprint.py

class TestSemanticFingerprint:

    def test_identical_formula_different_facts_do_not_share(self, measure_factory):
        """Two metrics with identical rendered string 'SUM([Revenue])' but pointing
        to fact_sales.revenue vs fact_returns.revenue must produce DIFFERENT fingerprints
        and NOT be merged into a shared datasource calculation."""
        m_sales = measure_factory(name="Revenue", fact="fact_sales.revenue", grain=["date", "region"])
        m_returns = measure_factory(name="Revenue", fact="fact_returns.revenue", grain=["date", "region"])
        
        fp_sales = SemanticFingerprint.compute(m_sales)
        fp_returns = SemanticFingerprint.compute(m_returns)
        
        assert fp_sales.fingerprint_hash != fp_returns.fingerprint_hash
        assert fp_sales.source_dependencies != fp_returns.source_dependencies
        
        deduper = MetricDeduplicator()
        bundle = deduper.deduplicate([m_sales, m_returns])
        assert bundle.get_scope(m_sales.id) == "local"
        assert bundle.get_scope(m_returns.id) == "local"

    def test_identical_semantics_across_dossiers_becomes_shared(self, measure_factory):
        """Identical metrics across two dossiers sharing the same fact and grain must get scope:'shared'."""
        m1 = measure_factory(name="Sales", fact="fact_sales.revenue", grain=["date", "store"])
        m2 = measure_factory(name="Sales", fact="fact_sales.revenue", grain=["date", "store"])
        
        deduper = MetricDeduplicator()
        bundle = deduper.deduplicate([m1, m2])
        assert bundle.get_scope(m1.id) == "shared"
```

#### 5.4g Publish Idempotency & Rollback Tests (Audit v3 Addition)

```python
# backend/tests/e2e/test_publish_idempotency.py

@pytest.mark.e2e
class TestPublishIdempotencyAndRollback:

    def test_publish_operation_idempotency(self, sample_twbx, publish_agent):
        """Publishing the same artifact twice with same idempotency key must not duplicate entities."""
        op1 = publish_agent.publish_workbook(sample_twbx, env="staging")
        assert op1.status == "COMPLETED"
        
        op2 = publish_agent.publish_workbook(sample_twbx, env="staging")
        assert op2.remote_id == op1.remote_id, "Idempotent re-run must return existing remote ID"

    def test_validation_failure_triggers_rollback(self, failing_staging_twbx, orchestrator):
        """If server render or numeric validation fails, staging artifacts must be cleaned up
        and production target left completely unmodified."""
        result = orchestrator.run_with_failing_validation(failing_staging_twbx)
        assert result.status == "FAILED"
        assert orchestrator.verify_staging_empty() is True
        assert orchestrator.verify_production_unmodified() is True
```

#### 5.4h Static Validation Ordering Test (Audit v3 Addition)

```python
# backend/tests/unit/test_pipeline_ordering.py

class TestPipelineOrdering:

    def test_static_validation_precedes_staging_publish(self, orchestrator_pipeline_trace):
        """Assert that STATIC_VALIDATE stage index strictly precedes STAGING_PUBLISH stage index."""
        stages = orchestrator_pipeline_trace.executed_stages
        static_idx = stages.index("STATIC_VALIDATE")
        staging_pub_idx = stages.index("STAGING_PUBLISH")
        
        assert static_idx < staging_pub_idx, \
            f"STATIC_VALIDATE (index {static_idx}) must run before STAGING_PUBLISH (index {staging_pub_idx})"
```

#### 5.4i Delimiter-Wrapped Entitlement Safety Tests (Audit v4 Addition — ADR-031)

```python
# backend/tests/unit/test_entitlement_safety.py

class TestEntitlementSafety:

    def test_delimiter_wrapped_predicate_prevents_substring_collision(self):
        """Assert that 'East' does NOT match 'Northeast' or 'South East' under delimiter wrapping."""
        from app.services.expression.evaluator import evaluate_predicate
        
        predicate = 'CONTAINS("|" + [ALLOWED_VALUES] + "|", "|" + [Region] + "|")'
        
        # User entitled to Northeast
        row_ne = {"ALLOWED_VALUES": "Northeast|Northwest", "Region": "Northeast"}
        assert evaluate_predicate(predicate, row_ne) is True
        
        # User with Northeast must NOT match East
        row_collision = {"ALLOWED_VALUES": "Northeast|Northwest", "Region": "East"}
        assert evaluate_predicate(predicate, row_collision) is False, \
            "Substring collision detected! Delimiter wrapping must prevent 'East' matching 'Northeast'"

    def test_entitlement_keys_on_username_not_fullname(self, mock_security_policy):
        """Assert that generated entitlement table joins on USERNAME(), never FULLNAME()."""
        emitter = TableauEmitter()
        policy = emitter.compile_security_policy(mock_security_policy)
        assert policy.match_column == "USERNAME"
        assert "USERNAME()" in policy.compiled_tableau_filter
```

#### 5.4j Validation Snapshot Watermark Consistency Tests (Audit v4 Addition — ADR-030)

```python
# backend/tests/integration/test_watermark_consistency.py

class TestWatermarkConsistency:

    def test_warehouse_extraction_sql_includes_watermark(self, physical_planner, watermark_ts):
        """Assert that all physical warehouse extraction SQL queries inject WHERE load_timestamp <= watermark."""
        plan = physical_planner.plan(watermark=watermark_ts)
        for table_plan in plan.table_plans:
            assert f"load_timestamp <= '{watermark_ts}'" in table_plan.extract_sql or \
                   f"AT (TIMESTAMP => '{watermark_ts}')" in table_plan.extract_sql

    def test_mstr_golden_query_passes_watermark(self, golden_generator, watermark_ts):
        """Assert that MSTR report instance execution receives the identical watermark prompt filter."""
        request_body = golden_generator.build_instance_request(watermark=watermark_ts)
        assert any(watermark_ts in str(p) for p in request_body.get("prompts", []))
```

#### 5.4k Semi-Additive Rolled-Grain Verification Tests (Audit v4 Addition)

```python
# backend/tests/unit/test_semi_additive_rollup.py

class TestSemiAdditiveRollup:

    def test_semi_additive_flag_triggers_rollup_validation(self, semi_additive_measure, validation_agent):
        """Assert that a semi-additive measure (subtotal != SUM) generates a semi_additive_rollup check."""
        scorecard = validation_agent.validate_measure(semi_additive_measure)
        rollup_checks = [c for c in scorecard.checks if c.check_type == "semi_additive_rollup"]
        assert len(rollup_checks) >= 1, "Semi-additive measure must have a rolled-grain validation check"
```

#### 5.4l Template Version Ceiling & Production Write-Lock Tests (Audit v4 Addition)

```python
# backend/tests/e2e/test_version_ceiling_and_lock.py

@pytest.mark.e2e
class TestVersionCeilingAndProductionLock:

    def test_newer_template_rejected_at_job_creation(self, client):
        """Assert POST /jobs returns 400 if template_version > server_version."""
        response = client.post("/jobs", json={
            "name": "Test Job",
            "tableau": {"server_version": "2024.2"},
            "options": {"template_version": "2025.1"}
        })
        assert response.status_code == 400
        assert "template_version exceeds server_version" in response.json()["message"]

    def test_production_target_untouched_until_promote(self, orchestrator_trace):
        """Assert that NO write operation targeted production project prior to PROMOTE stage."""
        staging_phase_ops = orchestrator_trace.get_publish_ops(stage="STAGING_VALIDATE")
        assert all(op.environment == "staging" for op in staging_phase_ops)
```

## 6. Snapshot Tests — TWB XML Regression

### 6.1 Purpose

Detect unintended changes in generated TWB XML. When the emitter is modified, snapshot tests catch regressions.

### 6.2 Implementation

```python
# backend/tests/snapshot/test_twb_snapshots.py

import pytest
from app.services.tableau.emitter import TableauEmitter

SNAPSHOT_DIR = "backend/tests/snapshot/snapshots/"


def test_simple_bar_chart_twb(snapshot):
    """Snapshot test for a simple bar chart worksheet."""
    ir = build_simple_bar_chart_ir()
    emitter = TableauEmitter(template_version="2024.2")
    twb_xml = emitter.emit(ir)
    
    # Compare against stored snapshot
    snapshot.assert_match(twb_xml, "simple_bar_chart.twb")


def test_multi_worksheet_dashboard_twb(snapshot):
    """Snapshot test for a multi-worksheet dashboard."""
    ir = build_multi_worksheet_ir()
    emitter = TableauEmitter(template_version="2024.2")
    twb_xml = emitter.emit(ir)
    
    snapshot.assert_match(twb_xml, "multi_worksheet_dashboard.twb")
```

To update snapshots after intentional changes:
```bash
pytest backend/tests/snapshot/ --snapshot-update
```

---

## 7. Test Configuration

### 7.1 pytest.ini

```ini
[pytest]
testpaths = backend/tests
markers =
    unit: Unit tests (fast, no external dependencies)
    integration: Integration tests (requires live MSTR environment)
    golden: Golden metric translation tests
    e2e: End-to-end pipeline tests
    snapshot: TWB XML snapshot tests
    slow: Tests that take > 10 seconds

# Default: run only unit and golden tests
addopts = -m "unit or golden" --tb=short -q
```

### 7.2 Running Test Subsets

```bash
# Unit tests only (fast, no dependencies)
pytest -m unit

# Golden metric tests
pytest -m golden -v

# Integration tests (requires MSTR env vars)
pytest -m integration -v

# End-to-end (requires MSTR + optionally Tableau)
pytest -m e2e -v

# All tests
pytest -m "" -v

# With coverage
pytest -m "unit or golden" --cov=app --cov-report=html
```

---

## 8. CI Pipeline (Future)

```yaml
# .github/workflows/test.yml (future — not MVP)
name: Tests
on: [push, pull_request]
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r backend/requirements.txt
      - run: pytest -m "unit or golden" --tb=short

  integration:
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    env:
      MSTR_BASE_URL: ${{ secrets.MSTR_BASE_URL }}
      MSTR_USERNAME: ${{ secrets.MSTR_USERNAME }}
      MSTR_PASSWORD: ${{ secrets.MSTR_PASSWORD }}
      MSTR_PROJECT_ID: ${{ secrets.MSTR_PROJECT_ID }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -r backend/requirements.txt
      - run: pytest -m integration --tb=short
```

---

## 9. The 25 Adversarial Golden Scenarios (T01 to T25)

The following 25 test suites serve as the mandatory adversarial gatekeepers for platform qualification:

| Suite ID | Test Name | Invariant Under Test |
| :--- | :--- | :--- |
| **`T01`** | `test_composite_attribute_key.py` | Multi-form primary keys (`[CAT_ID, PROD_ID]`) produce composite join predicates; no single-column fallback. |
| **`T02`** | `test_duplicate_attribute_ids.py` | Repeated sub-keys across categories do NOT produce Cartesian fan joins. |
| **`T03`** | `test_inaccessible_cube_dependency.py` | Permission-denied cube dependency immediately marks parent dossier `BLOCKED(inaccessible_dependency)`. |
| **`T04`** | `test_expired_mstr_token.py` | Proactive token renewal within 60s margin + dynamic 401 re-authentication recovery. |
| **`T05`** | `test_expired_cube_instance.py` | HTTP 404 instance expiry re-creates cube instance and resumes from committed page offset. |
| **`T06`** | `test_checkpoint_failure_recovery.py` | Crash at object 149/200 resumes without re-extracting objects 1–149. |
| **`T07`** | `test_selector_vs_prompt.py` | Type 60 in-dossier selectors map to Tableau Quick Filters; pre-execution prompts are deferred. |
| **`T08`** | `test_vldb_null_propagation.py` | Project-level `NULL_PROPAGATION = ignore` injects operand-level `ZN()` in arithmetic ASTs. |
| **`T09`** | `test_cyclic_scc_atomic_compile.py` | Strongly-connected components collapse into single `MigrationUnit` and compile atomically. |
| **`T10`** | `test_failed_base_metric_cascade.py` | Failed base metric in Wave 1 transitively poisons 3 dependent dossiers in Wave 3 to `BLOCKED`. |
| **`T11`** | `test_heterogeneous_fact_grains.py` | Unproven join between Daily Sales and Monthly Budget emits `Issue(BLOCKER, heterogeneous_fact_grain_join)`. |
| **`T12`** | `test_transformation_table_prior_year.py` | Shifted-key transformation tables replicate prior-period joins without table calculations. |
| **`T13`** | `test_insufficient_lod_grain.py` | `{FIXED [Customer] : SUM([Revenue])}` against table without `customer_id` emits blocker issue. |
| **`T14`** | `test_fixed_dim_filter_conflict.py` | Interacting dimension filter with `FIXED` LOD promotes filter to `<filter context="true">`. |
| **`T15`** | `test_count_attribute_vs_countd.py` | MSTR `Count(Attribute)` compiles to `COUNTD([Attr_ID])` instead of transaction-row `COUNT()`. |
| **`T16`** | `test_null_arithmetic.py` | Non-propagating NULL arithmetic evaluated with operand AST transformations. |
| **`T17`** | `test_identical_formula_diff_fingerprint.py` | Identical syntax `SUM([Revenue])` with different physical grain hashes forced to `scope: "local"`. |
| **`T18`** | `test_same_caption_diff_fingerprint.py` | `CaptionRegistry` disambiguates identical names against shared datasource without overwriting. |
| **`T19`** | `test_east_vs_northeast_security_attack.py` | Delimiter-wrapped RLS matching prevents `"East"` from matching `"Northeast"`. |
| **`T20`** | `test_mutable_warehouse_watermark.py` | Temporal / Time-Travel snapshot filters isolate mutable in-place update drift. |
| **`T21`** | `test_hyper_partial_write_crash.py` | Streaming insert crash leaves `.hyper.tmp` uncommitted; existing `.hyper` untouched. |
| **`T22`** | `test_tableau_xsd_vs_server_render.py` | XSD-valid workbook with unresolved field reference caught and blocked by Staging Render Gate. |
| **`T23`** | `test_publish_network_timeout.py` | Timeout during publish transitions to `AMBIGUOUS` and reconciles via remote idempotency hash check. |
| **`T24`** | `test_production_publish_partial_failure.py` | Staging failure executes compensating deletion; production project remains strictly write-locked. |
| **`T25`** | `test_human_ir_edit_revalidation.py` | Review Queue IR patch submission re-runs golden tests and triggers staging validation. |

