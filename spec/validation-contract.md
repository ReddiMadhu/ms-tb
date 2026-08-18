# Canonical Validation Contract — mstr-tableau-migrator

**Product:** MicroStrategy → Tableau Migration Platform  
**Document:** `validation-contract.md`  
**Classification:** Normative Quality Gate Specification  
**Version:** 1.0.0  
**Date:** 17 August 2026  

---

## 1. Overview & Normative Authority

This document defines the **single authoritative mathematical, structural, and security validation contract** for the `mstr-tableau-migrator` engine. 

All quality gates, automated assertions, and publication decisions evaluated by `ValidationAgent` and checked by the `Orchestrator` before promotion **must strictly conform to the formulas and thresholds defined herein**.

---

## 2. Mathematical Parity & Tolerance Formulas

### 2.1 Financial KPI Parity Gate
For continuous numerical measures and financial metrics under identical filter predicates and watermark boundaries:

#### Non-Zero Expected Values:
$$\text{RelativeError} = \frac{|\text{Actual}_{\text{Tableau}} - \text{Expected}_{\text{MSTR}}|}{\max(|\text{Expected}_{\text{MSTR}}|, \epsilon)} \le 0.001 \quad (0.1\% \text{ tolerance})$$
Where $\epsilon = 10^{-6}$ (floating-point epsilon guard).

#### Zero Expected Values:
$$\text{If } \text{Expected}_{\text{MSTR}} = 0 \implies |\text{Actual}_{\text{Tableau}}| \le 10^{-5}$$
*(Prevents undefined or infinite relative errors when dividing by zero).*

---

### 2.2 Row Count & Grain Invariant Gates
- **Row Count Parity:** At the exact declared `ExtractionGrain` and watermark timestamp:
  $$\text{RowCount}(\text{Tableau Hyper Table}) \equiv \text{RowCount}(\text{Warehouse Source Query})$$
- **Primary Key Uniqueness:**
  $$\text{DuplicateKeys}(\text{Hyper Table}) == 0$$
- **Foreign Key Orphan Check:**
  $$\text{OrphanRecords}(\text{Fact Table} \to \text{Dimension Table}) == 0$$

---

### 2.3 Integer & Semi-Additive Rollup Gates
- **Discrete Integer Counts:**
  $$\text{Actual}_{\text{Tableau}} == \text{Expected}_{\text{MSTR}}$$
- **Semi-Additive Measures:**
  For measures with non-SUM rollup functions (e.g. `LAST`, `OPENING_BALANCE`), verify that rolled time-grain values (Monthly, Quarterly, Annual) match MSTR ground-truth:
  $$\text{SemiAdditiveError} \le 0.001$$

---

### 2.4 Set Membership & Dimension Parity
- **Filter Set Enumeration:**
  $$\text{MemberSet}_{\text{Tableau}} == \text{MemberSet}_{\text{MSTR}}$$
  *(Asserts exact equality of distinct set members, not merely member count).*

---

## 3. Row-Level Security (RLS) Impersonation Contract

### 3.1 Connected App JWT Impersonation
The `ValidationAgent` performs automated live security testing against Tableau Server by generating signed JWTs for 3 mandatory test identities:
1. `mgr_east` (Restricted regional access)
2. `mgr_west` (Restricted regional access)
3. `admin_user` (Unrestricted global access `*`)

### 3.2 Security Validation Assertion:
$$\forall u \in \text{TestIdentities}: \quad \text{VisibleDimensionMembers}_{\text{Tableau}}(u) \equiv \text{ExpectedSecurityScope}_{\text{MSTR}}(u)$$

### 3.3 Delimiter Normalization Specification:
Security entitlement tables must store pipe-delimited, uppercase, NFKC-normalized strings:
$$\text{ALLOWED\_VALUES} = \text{"|" + TRIM(UPPER(VAL\_1)) + "|" + TRIM(UPPER(VAL\_2)) + "|"}$$
Tableau filter predicate:
```tableau
CONTAINS([ALLOWED_VALUES_NORMALIZED], "|" + UPPER(TRIM([Region])) + "|")
```

---

## 4. Unified Canonical `ValidationScorecard`

### 4.1 Schema Definition
```python
@dataclass
class ValidationScorecard:
    job_id: str
    security_confidence: float        # STRICT: Must be == 1.00
    security_parity: bool             # STRICT: Must be == True (100% member-set match)
    financial_kpi_confidence: float   # STRICT: Must be >= 0.98
    structural_confidence: float      # STRICT: Must be >= 0.99
    visual_confidence: float          # SOFT: Warn if < 0.80, routes to Review if < 0.80
    blocker_issues: int               # STRICT: Must be == 0
    mandatory_review_flags: int       # STRICT: Must be == 0
    warning_issues: int               # Informational only
    checks_total: int
    checks_passed: int
    checks: list[ValidationCheck]

    @property
    def auto_publish_ok(self) -> bool:
        """Normative auto-publish gate contract."""
        return (
            self.security_confidence >= 1.00
            and self.security_parity is True
            and self.financial_kpi_confidence >= 0.98
            and self.structural_confidence >= 0.99
            and self.visual_confidence >= 0.80
            and self.blocker_issues == 0
            and self.mandatory_review_flags == 0
        )

@dataclass
class ValidationCheck:
    check_type: str        # "row_count" | "kpi_value" | "filter_set" | "xsd" | "security_member_set" | "semi_additive_rollup"
    object_id: str
    expected: Any
    actual: Any
    passed: bool
    tolerance: Optional[float]
    message: str
```

### 4.2 Triage Matrix:
| Scorecard Condition | Resulting Action |
| :--- | :--- |
| `auto_publish_ok == True` | Fast-track to `PROMOTE` step |
| `blocker_issues > 0` | Immediate `FAILED_VALIDATION` $\to$ `ROLLBACK_STAGING` $\to$ Review Queue |
| `security_parity == False` | Hard Security Blocker $\to$ Production write-lock maintained $\to$ Review Queue |
| `visual_confidence < 0.80` | Soft Warning $\to$ `REVIEW_REQUIRED` (Human operator approval required before promote) |
| `kpi_confidence < 0.98` | Accuracy Variance $\to$ Review Queue with side-by-side AST and diff display |

---

## 5. Concrete Validation Implementations

### 5.1 Extraction Row-Count Parity
```python
async def validate_extraction_row_parity(
    warehouse_client: WarehouseConnection,
    hyper_table_path: str,
    table_name: str,
    compiled_warehouse_sql: str
) -> ValidationResult:
    """Exact row-count comparison between warehouse query and Hyper extract."""
    warehouse_count = await warehouse_client.query_count(compiled_warehouse_sql)
    with tableauhyperapi.HyperProcess() as hyper_proc:
        with hyper_proc.connect(hyper_table_path) as conn:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
            hyper_count = cursor.fetchone()[0]
            
    if warehouse_count != hyper_count:
        return ValidationResult(
            passed=False,
            blocker=True,
            message=f"Row count parity failed: warehouse={warehouse_count}, hyper={hyper_count}",
            expected=warehouse_count,
            actual=hyper_count,
            tolerance=0.0
        )
    return ValidationResult(passed=True, message=f"Row count exact match: {warehouse_count}")
```

### 5.2 Primary Key & Foreign Key Integrity
```python
def validate_primary_key_uniqueness(
    hyper_conn: tableauhyperapi.Connection,
    table_name: str,
    grain_keys: list[str]
) -> ValidationResult:
    """Asserts duplicate primary keys == 0."""
    cols = ", ".join(grain_keys)
    cursor = hyper_conn.execute(f"SELECT {cols}, COUNT(*) as cnt FROM {table_name} GROUP BY {cols} HAVING cnt > 1")
    dups = cursor.fetchall()
    if dups:
        return ValidationResult(passed=False, blocker=True, message=f"Duplicate PKs detected: {len(dups)} collisions")
    return ValidationResult(passed=True, message="Primary key uniqueness verified (0 duplicates)")

def validate_foreign_key_integrity(
    hyper_conn: tableauhyperapi.Connection,
    fact_table: str,
    dim_table: str,
    fact_fk: str,
    dim_pk: str
) -> ValidationResult:
    """Asserts 0 orphaned fact records."""
    query = f"""
    SELECT COUNT(*) FROM {fact_table} f
    LEFT JOIN {dim_table} d ON f.{fact_fk} = d.{dim_pk}
    WHERE d.{dim_pk} IS NULL AND f.{fact_fk} IS NOT NULL
    """
    cursor = hyper_conn.execute(query)
    orphans = cursor.fetchone()[0]
    if orphans > 0:
        return ValidationResult(passed=False, blocker=False, message=f"FK orphans detected: {orphans} rows")
    return ValidationResult(passed=True, message=f"FK integrity verified: 0 orphans")
```

### 5.3 VLDB Null Handling Equivalence
```python
def validate_null_handling_equivalence(
    mstr_result: Optional[float],
    tableau_result: Optional[float],
    null_propagation: str
) -> bool:
    """Asserts parity between MSTR and Tableau under VLDB null settings."""
    if null_propagation == "propagate":
        return mstr_result == tableau_result
    elif null_propagation == "ignore":
        if tableau_result is None:
            return mstr_result is None or mstr_result == 0.0
        return abs((mstr_result - tableau_result) / max(abs(mstr_result), 1e-6)) <= 0.001
    return False
```
