# Frontend Review UI Specification — mstr-tableau-migrator

**Companion to:** `architecture.md`, `api.md`  
**Date:** 17 August 2026  
**Stack:** Next.js (TypeScript) — App Router  
**Communication:** REST API polling against FastAPI backend  

---

## 1. Overview

The review UI is a web-based dashboard for migration operators. It provides:

- Project-level migration overview with progress tracking
- Object-level status drill-down with confidence scores
- Side-by-side expression comparison (MSTR vs Tableau)
- Inline IR editing with re-compilation triggers
- Validation scorecard visualization
- Review queue with one-click actions
- Dependency/blast-radius visualization

> **Build order (ADR-015):** The entire backend pipeline is built and verified first. The frontend is the last major component.

---

## 2. Page Structure

```
/                           → Dashboard (job list + summary)
/jobs/new                   → New Job Wizard (Scan & Select Dossiers)
/jobs/{jobId}               → Job Detail (progress, stages, scores)
/jobs/{jobId}/objects        → Object Catalog (filterable table)
/jobs/{jobId}/objects/{id}   → Object Detail (expression comparison, IR, dependencies)
/jobs/{jobId}/validation     → Validation Scorecard
/jobs/{jobId}/review         → Review Queue
/jobs/{jobId}/review/{id}    → Review Task Detail (side-by-side + actions)
/jobs/{jobId}/report         → Migration Report (download links)
/jobs/{jobId}/lineage        → Cross-Reference / Lineage View
```

---

## 3. Page Specifications

### 3.1 Dashboard (`/`)

**Purpose:** Landing page showing all migration jobs with high-level status.

| Element | Description |
|---------|-------------|
| Job list table | Name, status, created date, progress %, score, review count |
| Status badges | Color-coded: green (complete), blue (running), yellow (review needed), red (failed) |
| "New Migration Job" button | Navigates to `/jobs/new` (Interactive Scan & Select Wizard) |
| Summary cards | Total jobs, active jobs, objects migrated, average score |

**Polling:** Refresh job list every 10 seconds while any job is in a running state.

---

### 3.2 New Job: Scan & Select Dossiers Wizard (`/jobs/new`)

**Purpose:** 3-step interactive wizard enabling operators to discover, inspect, multi-select specific dossiers, and launch targeted migration with one click.

**Workflow Steps:**
1. **Step 1: Connection & Discovery:** Select saved MSTR & Tableau connections, select project, and click `[🔍 Scan Available Dossiers]`. Calls `POST /discovery/dossiers`.
2. **Step 2: Interactive Dossier Grid:** Filterable, searchable catalog of discovered dossiers with checkboxes, chapter counts, dataset counts, and "Select All" toggle.
3. **Step 3: Configuration & Launch:** Choose target Tableau Server project, configure auto-publish threshold, and click `[🚀 Start Migration (N Selected)]`. Submits `POST /jobs` with `scope.specific_object_ids`.

**Layout:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🚀 New Migration Job: Scan & Select Dossiers                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Source & Target Connections                                              │
│                                                                             │
│  MSTR Server:     [ https://mstr.company.com/MicroStrategyLibrary        ]  │
│  MSTR Project:    [ Sales Analytics (B7CA92F04B...)                    ▼ ]  │
│  Target Tableau:  [ Tableau Prod 2024.2 (https://tableau.company.com)  ▼ ]  │
│                                                                             │
│                                              [ 🔍 Scan Available Dossiers ] │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. Select Dossiers to Migrate (Found: 18 Dossiers in Project)               │
│                                                                             │
│ 🔍 Search: [ sales                ]     📁 Folder Filter: [ All Folders ▼ ] │
│                                                                             │
│ [x] Select All (3 Selected)                                                 │
│                                                                             │
│ [✓]  Dossier Name              Folder Path             Chapters   Datasets  │
│ ─────────────────────────────────────────────────────────────────────────── │
│ [✓]  Executive Sales Overview  /Shared/Executive/       4 pages    2 Cubes  │
│ [✓]  Regional KPI Dashboard    /Shared/Regional/        3 pages    1 Cube   │
│ [ ]  Marketing Campaign ROI    /Shared/Marketing/       6 pages    3 Cubes  │
│ [✓]  Year-over-Year Finance    /Shared/Finance/         2 pages    1 Cube   │
│ [ ]  Supply Chain Inventory    /Shared/Operations/      5 pages    2 Cubes  │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. Target Options & Execution                                               │
│                                                                             │
│  Tableau Project:  [ Migrated Dashboards                                 ]  │
│  Options:          [✓] Auto-Publish if >98%    [✓] Skip Unused Metrics      │
│  Numeric Gate:     [ 0.98 ]                                                 │
│                                                                             │
│                                                 [ 🚀 Start Migration (3) ]  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### 3.3 Job Detail (`/jobs/{jobId}`)

**Purpose:** Detailed progress view for a single migration job.

**Layout:**

```
┌─────────────────────────────────────────────────────┐
│  Job: "Q3 2026 Sales Migration"     Status: RUNNING │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │  Stage Progress Bar                           │  │
│  │  ████████████░░░░░░░░░░  SEMANTIC (Wave 2/4)  │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐      │
│  │Objects │ │Succeed │ │Failed  │ │Review  │      │
│  │  187   │ │  142   │ │   8    │ │   15   │      │
│  └────────┘ └────────┘ └────────┘ └────────┘      │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │  Score Summary                                │  │
│  │  Numeric: 0.97  Structural: 0.99  Security: ✓ │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │  Stage Timeline (vertical list)               │  │
│  │  ✅ Discovery      12s                        │  │
│  │  ✅ Graph           2s                        │  │
│  │  🔄 Semantic       45s (in progress)          │  │
│  │  ⏳ IR Compile                                │  │
│  │  ⏳ AI Translate                              │  │
│  │  ⏳ Visualization                             │  │
│  │  ⏳ Hyper Build                               │  │
│  │  ⏳ Tableau Emit                              │  │
│  │  ⏳ Validation                                │  │
│  │  ⏳ Publish                                   │  │
│  │  ⏳ Report                                    │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  [View Objects]  [Review Queue]  [Validation]       │
│  [Download Report]  [Resume Job]  [Cancel Job]      │
└─────────────────────────────────────────────────────┘
```

> **Audit note:** When a job fails or is cancelled, the **[Resume Job]** action triggers `POST /jobs/{jobId}/resume` to restart from the last stage checkpoint (ADR-016) without re-running completed waves. A **Checkpoints Drawer** allows inspecting per-cube extraction offsets.

**Polling:** Refresh every 5 seconds while job is running.

---

### 3.3 Object Catalog (`/jobs/{jobId}/objects`)

**Purpose:** Filterable, searchable table of all discovered MSTR objects.

**Filters:**
- Type dropdown: metric, attribute, dossier, report, cube, fact, filter, all
- Status dropdown: all, extracted, compiled, published, failed, skipped, review
- Search by name (debounced)
- Sort by: name, type, confidence, status

**Table columns:**

| Column | Description |
|--------|-------------|
| Name | Clickable → Object Detail |
| Type | metric / attribute / dossier / etc. |
| MSTR Path | Folder hierarchy |
| Status | Badge (color-coded) |
| Confidence | Progress bar (0–100%) with numeric label |
| Method | rule_compiler / pattern / llm / hash_cache |
| Issues | Count with severity icon |

**Summary bar at top:** Objects by status pie chart + confidence histogram.

---

### 3.4 Object Detail (`/jobs/{jobId}/objects/{id}`)

**Purpose:** Deep inspection of a single object's extraction, compilation, and migration status.

**Layout (for metrics):**

```
┌─────────────────────────────────────────────────────────┐
│  Metric: "Profit Margin"                                │
│  MSTR ID: 28B7F04A...  │  Status: compiled  │  95%     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─── MSTR Expression ──────┐  ┌─── Tableau Calc ────┐ │
│  │                          │  │                      │ │
│  │  Sum(Profit) / Sum(      │  │  SUM([Profit]) /     │ │
│  │  Revenue)                │  │  SUM([Revenue])      │ │
│  │                          │  │                      │ │
│  │  Dimty: Report Level     │  │  Method: rule_       │ │
│  │  Format: %, 2 dec        │  │  compiler            │ │
│  └──────────────────────────┘  └──────────────────────┘ │
│                                                         │
│  ┌─── Confidence Breakdown ─────────────────────────┐  │
│  │  Expression parsing:    ████████████████  0.99    │  │
│  │  Dimty resolution:      ████████████████  0.98    │  │
│  │  Function mapping:      ████████████████  0.99    │  │
│  │  Overall:               ███████████████   0.95    │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
│  ┌─── Dependencies (uses) ──────────────────────────┐  │
│  │  → fact:profit (Revenue fact)                     │  │
│  │  → fact:revenue (Profit fact)                     │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
│  ┌─── Dependents (used by) ─────────────────────────┐  │
│  │  ← dossier:sales_performance                      │  │
│  │  ← report:quarterly_review                        │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
│  ┌─── Issues ───────────────────────────────────────┐  │
│  │  (none)                                           │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
│  ┌─── Raw MSTR Definition (collapsible JSON) ──────┐  │
│  │  { ... }                                          │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
│  ┌─── IR Node (collapsible JSON) ──────────────────┐  │
│  │  { ... }                                          │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

### 3.5 Review Queue (`/jobs/{jobId}/review`)

**Purpose:** List of all objects requiring human review, with one-click actions.

**Filters:**
- Status: pending, approved, rejected, redesign, assigned
- Severity: blocker, warning
- Sort by: severity (blockers first), confidence (lowest first), created date

**Table columns:**

| Column | Description |
|--------|-------------|
| Object Name | Clickable → Review Task Detail |
| Type | metric / filter / etc. |
| Severity | 🔴 blocker / 🟡 warning |
| Reason | Short description of why review is needed |
| Confidence | Numeric + bar |
| Blast Radius | Count of affected downstream objects |
| Status | pending / approved / etc. |
| Actions | Quick buttons: Approve, Reject, Assign |

**Summary cards:** Total pending, blockers, warnings, avg time-in-queue.

---

### 3.6 Review Task Detail (`/jobs/{jobId}/review/{id}`)

**Purpose:** Full review interface with side-by-side comparison and editing capabilities.

This is the most complex page and the primary workhorse for migration operators.

**Layout:**

```
┌─────────────────────────────────────────────────────────────┐
│  Review: "Revenue YoY Growth"  │  🟡 Warning  │  Conf: 72% │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Reason: Level metric with dimty at Year grain —            │
│          LOD translation confidence 0.72                    │
│                                                             │
│  ┌─── Side-by-Side ────────────────────────────────────┐   │
│  │                                                      │   │
│  │  MSTR Expression          │  Generated Tableau Calc  │   │
│  │  ─────────────            │  ──────────────────────  │   │
│  │  Sum(Revenue) /           │  SUM([Revenue]) /        │   │
│  │  Sum(Revenue){~+, Year-1} │  LOOKUP(SUM([Revenue]),  │   │
│  │                           │    -1)                   │   │
│  │  Dimty:                   │                          │   │
│  │    Year (allow addition)  │  Method: llm             │   │
│  │    Offset: Year - 1       │  Confidence: 0.72        │   │
│  │                           │                          │   │
│  │  [Syntax Highlighted]     │  [Syntax Highlighted]    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─── Confidence Breakdown ─────────────────────────────┐  │
│  │  ⚠️ Dimty resolution:     ██████░░░░░░░░░  0.65      │  │
│  │  ✅ Function mapping:     ████████████████  0.95      │  │
│  │  ⚠️ Time offset handling: ███████░░░░░░░░  0.70      │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─── Blast Radius ────────────────────────────────────┐   │
│  │  This metric is used by:                             │   │
│  │  • Dossier: Sales Overview (chapter: YoY Analysis)   │   │
│  │  • Report: Annual Summary                            │   │
│  │  Fixing this will affect 2 downstream objects.       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─── Edit Calculated Field ───────────────────────────┐   │
│  │  ┌──────────────────────────────────────────────┐   │   │
│  │  │  SUM([Revenue]) / [Revenue_Prior_Year]       │   │   │
│  │  │  ▌                                           │   │   │
│  │  └──────────────────────────────────────────────┘   │   │
│  │  [Validate Syntax]  [Re-run Golden Tests]           │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─── Edit IR (Advanced, collapsible) ─────────────────┐   │
│  │  JSON editor with schema validation                  │   │
│  │  [Save & Re-compile]                                 │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─── Actions ─────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  [✅ Approve As-Is]  [📝 Save Edit & Approve]       │   │
│  │  [🚫 Flag for Redesign]  [👤 Assign to Developer]   │   │
│  │                                                      │   │
│  │  Notes: ____________________________________________ │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

### 3.7 Validation Scorecard (`/jobs/{jobId}/validation`)

**Purpose:** Visual summary of all validation checks with pass/fail indicators.

**Layout:**
- Overall score cards (numeric, structural, security)
- Grouped check results by type (KPI values, row counts, filter sets, XSD, open test)
- Each check: object name, filter scenario, expected vs actual, pass/fail, tolerance
- Fail-only filter toggle

---

### 3.8 Cross-Reference (`/jobs/{jobId}/lineage`)

**Purpose:** Searchable cross-reference table mapping MSTR GUIDs to Tableau IDs.

**Table columns:**
| MSTR Name | MSTR Type | MSTR Path | Tableau Workbook | Tableau Field | Migrated At |

**Search:** By MSTR name, MSTR ID, Tableau field name.

---

## 4. Component Library

### Key Reusable Components

| Component | Description |
|-----------|-------------|
| `<StatusBadge status={...} />` | Color-coded status pill |
| `<ConfidenceBar value={0.85} />` | Horizontal progress bar with numeric label |
| `<ExpressionViewer code={...} language="mstr" />` | Syntax-highlighted expression display |
| `<ExpressionEditor value={...} onChange={...} />` | Editable code area for Tableau calcs |
| `<SideBySide left={...} right={...} />` | Two-panel comparison layout |
| `<JsonViewer data={...} collapsed />` | Collapsible JSON tree |
| `<DependencyList items={[...]} type="uses" />` | Clickable dependency links |
| `<ScoreCard label="Numeric" value={0.97} />` | Big number display card |
| `<StageTimeline stages={[...]} />` | Vertical timeline with status icons |
| `<FilterBar filters={[...]} onFilterChange={...} />` | Composable filter controls |
| `<DataTable columns={[...]} data={[...]} />` | Sortable, paginated data table |
| `<DossierPickerTable dossiers={[...]} onSelectionChange={...} />` | Interactive multi-select dossier discovery table with search and filters |

### Syntax Highlighting

Use a lightweight code highlighter (e.g., `prism-react-renderer` or `shiki`) with custom language definitions for:
- **MSTR expressions**: `Sum()`, `{~+}`, dimty syntax
- **Tableau calcs**: `SUM()`, `{FIXED ...}`, `LOOKUP()`, `IF/THEN/END`

---

## 5. API Integration Layer

```typescript
// frontend/src/lib/api.ts

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export const api = {
  // Pre-Job Discovery
  discoverDossiers: (req: DiscoverDossiersRequest) =>
    fetch(`${API_BASE}/discovery/dossiers`, { method: 'POST', body: JSON.stringify(req), headers: {'Content-Type': 'application/json'} }).then(r => r.json()),

  // Jobs
  listJobs: (params?: JobListParams) => 
    fetch(`${API_BASE}/jobs?${new URLSearchParams(params)}`).then(r => r.json()),
  
  getJob: (jobId: string) => 
    fetch(`${API_BASE}/jobs/${jobId}`).then(r => r.json()),
  
  createJob: (spec: CreateJobSpec) => 
    fetch(`${API_BASE}/jobs`, { method: 'POST', body: JSON.stringify(spec), headers: {'Content-Type': 'application/json'} }).then(r => r.json()),
  
  cancelJob: (jobId: string) => 
    fetch(`${API_BASE}/jobs/${jobId}/cancel`, { method: 'POST' }).then(r => r.json()),
  
  resumeJob: (jobId: string, forceStage?: string) =>
    fetch(`${API_BASE}/jobs/${jobId}/resume`, { method: 'POST', body: JSON.stringify({ force_stage: forceStage }), headers: {'Content-Type': 'application/json'} }).then(r => r.json()),

  getCheckpoints: (jobId: string) =>
    fetch(`${API_BASE}/jobs/${jobId}/checkpoints`).then(r => r.json()),
  
  // Objects
  listObjects: (jobId: string, params?: ObjectListParams) => 
    fetch(`${API_BASE}/jobs/${jobId}/objects?${new URLSearchParams(params)}`).then(r => r.json()),
  
  getObject: (jobId: string, objectId: string) => 
    fetch(`${API_BASE}/jobs/${jobId}/objects/${objectId}`).then(r => r.json()),
  
  // Review
  listReviewTasks: (params?: ReviewListParams) => 
    fetch(`${API_BASE}/review?${new URLSearchParams(params)}`).then(r => r.json()),
  
  getReviewTask: (taskId: string) => 
    fetch(`${API_BASE}/review/${taskId}`).then(r => r.json()),
  
  resolveReviewTask: (taskId: string, action: ResolveAction) => 
    fetch(`${API_BASE}/review/${taskId}/resolve`, { method: 'POST', body: JSON.stringify(action), headers: {'Content-Type': 'application/json'} }).then(r => r.json()),
  
  editIR: (taskId: string, patch: IRPatch) => 
    fetch(`${API_BASE}/review/${taskId}/edit-ir`, { method: 'POST', body: JSON.stringify(patch), headers: {'Content-Type': 'application/json'} }).then(r => r.json()),
  
  // Validation
  getValidation: (jobId: string) => 
    fetch(`${API_BASE}/jobs/${jobId}/validation`).then(r => r.json()),
  
  // Cross-reference
  queryCrossRef: (params: CrossRefParams) => 
    fetch(`${API_BASE}/cross-reference?${new URLSearchParams(params)}`).then(r => r.json()),
  
  // Reports
  generateReport: (jobId: string, format: string) => 
    fetch(`${API_BASE}/jobs/${jobId}/report`, { method: 'POST', body: JSON.stringify({ format }), headers: {'Content-Type': 'application/json'} }).then(r => r.json()),
  
  // Audit
  queryAudit: (params: AuditParams) => 
    fetch(`${API_BASE}/audit?${new URLSearchParams(params)}`).then(r => r.json()),
};
```

### Polling Hook

```typescript
// frontend/src/lib/usePolling.ts

import { useState, useEffect, useRef } from 'react';

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  enabled: boolean = true
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const intervalRef = useRef<NodeJS.Timeout>();

  useEffect(() => {
    if (!enabled) return;
    
    const poll = async () => {
      try {
        const result = await fetcher();
        setData(result);
        setError(null);
      } catch (e) {
        setError(e as Error);
      }
    };
    
    poll(); // Initial fetch
    intervalRef.current = setInterval(poll, intervalMs);
    
    return () => clearInterval(intervalRef.current);
  }, [fetcher, intervalMs, enabled]);

  return { data, error };
}
```

---

## 6. Design Guidelines

### Color Palette

| Purpose | Color | Hex |
|---------|-------|-----|
| Background | Dark charcoal | `#0f1117` |
| Surface | Dark gray | `#1a1d27` |
| Card | Slightly lighter | `#222634` |
| Primary text | White | `#e4e4e7` |
| Secondary text | Muted gray | `#9ca3af` |
| Accent / Primary | Blue | `#3b82f6` |
| Success | Green | `#22c55e` |
| Warning | Amber | `#f59e0b` |
| Error / Blocker | Red | `#ef4444` |
| Info | Cyan | `#06b6d4` |
| Confidence high | Green gradient | `#22c55e → #16a34a` |
| Confidence medium | Yellow gradient | `#f59e0b → #d97706` |
| Confidence low | Red gradient | `#ef4444 → #dc2626` |

### Typography

- **Font:** Inter (Google Fonts)
- **Headings:** Semi-bold, tracking tight
- **Body:** Regular, 14px base
- **Code/expressions:** JetBrains Mono

### Status Colors

| Status | Color | Icon |
|--------|-------|------|
| PENDING | Gray | ⏳ |
| RUNNING | Blue (pulse animation) | 🔄 |
| COMPLETE | Green | ✅ |
| FAILED | Red | ❌ |
| REVIEW | Amber | ⚠️ |
| SKIPPED | Gray (dimmed) | ⏭️ |

---

## 7. Dependencies

```json
{
  "dependencies": {
    "next": "^15.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "typescript": "^5.5.0",
    "@radix-ui/react-dialog": "^1.1.0",
    "@radix-ui/react-dropdown-menu": "^2.1.0",
    "@radix-ui/react-select": "^2.1.0",
    "@radix-ui/react-tabs": "^1.1.0",
    "@radix-ui/react-tooltip": "^1.1.0",
    "lucide-react": "^0.400.0",
    "prism-react-renderer": "^2.3.0",
    "recharts": "^2.12.0",
    "clsx": "^2.1.0"
  }
}
```
