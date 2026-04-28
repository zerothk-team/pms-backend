# Copilot Prompt — Frontend Enhancement + Documentation Consolidation
> **Model**: Claude Sonnet 4.6
> **Paste into**: VS Code GitHub Copilot Chat (`Ctrl+Shift+I`) with both `pms-frontend/` and `pms-backend/` workspaces open
> **Run after**: Backend enhancements 1, 2, and 3 are fully implemented and tests pass
> **Scope**: @workspace — this prompt touches both `src/` (frontend) and docs at repo root

---

## READ THIS FIRST — What This Prompt Does

This is a **single, self-contained prompt** covering three things:

1. **Frontend catch-up for Enhancement 1** — Per-KPI Scoring Config UI (types, RTK Query endpoints, components, updated existing pages)
2. **Frontend catch-up for Enhancement 2** — Formula Variables & External Data Binding UI (types, RTK Query endpoints, components, updated actuals entry)
3. **Single-source documentation consolidation** — Merge all existing `.md` prompt files + the user guide Word doc into one living `MASTER_USER_GUIDE.md` so there is never conflicting documentation

**Do not** create new backend files — the backend is already done. Only touch:
- `pms-frontend/src/` for all code changes
- `MASTER_USER_GUIDE.md` at the repo root for documentation

---

## SYSTEM CONTEXT (paste this into every follow-up message too)

```
@workspace

Backend is FastAPI (Python 3.11) in pms-backend/.
Frontend is React 18 + TypeScript + Vite in pms-frontend/.
State: Redux Toolkit + RTK Query (fakeBaseQuery with mock JSON).
UI: shadcn/ui + Tailwind CSS + Framer Motion + dnd-kit.
Icons: Lucide React.

Roles: hr_admin | executive | manager | employee
All enums match backend Python exactly (same string values).

Enhancement 1 added:
  - kpi_scoring_configs table (5 system presets + custom)
  - scoring_config_id FK on kpis table (KPI-level default)
  - scoring_config_id FK on kpi_targets table (target-level override, highest precedence)
  - scoring_config_snapshot JSON on performance_scores (audit trail)
  - Precedence: target_override > kpi_default > cycle_default

Enhancement 2 added:
  - kpi_variables table (named slots in formulas: REVENUE, EXPENSES, HEADCOUNT)
  - variable_actuals table (raw values per variable per period, full audit)
  - 5 adapter types: rest_api | database | influxdb | webhook_receive | kpi_actual
  - DataSyncService.compute_formula_actual() — full pipeline
  - FormulaEvaluator — AST-safe, uses FormulaParser.extract_variable_names()
  - New endpoints: /kpis/{id}/variables/, /actuals/variables/, /integrations/

Key backend routes added:
  GET/POST  /api/v1/scoring/configs/
  GET/PUT   /api/v1/scoring/configs/{id}
  POST      /api/v1/scoring/configs/from-preset
  GET       /api/v1/scoring/configs/{id}/preview
  PATCH     /api/v1/kpis/{id}/scoring-config
  PATCH     /api/v1/targets/{id}/scoring-config
  GET       /api/v1/targets/{id}/scoring-config   (effective config + source)
  GET/POST  /api/v1/kpis/{id}/variables/
  PUT/DEL   /api/v1/kpis/{id}/variables/{var_id}
  POST      /api/v1/kpis/{id}/variables/{var_id}/test-sync
  POST      /api/v1/actuals/variables/
  GET       /api/v1/actuals/variables/{kpi_id}/{period}
  POST      /api/v1/actuals/variables/bulk-sync/{kpi_id}
  POST      /api/v1/integrations/push/{endpoint_key}
  GET       /api/v1/integrations/adapters/
  POST      /api/v1/integrations/adapters/test
```

---

# PART 1 — FRONTEND: ENHANCEMENT 1 (Per-KPI Scoring Config)

## 1.1 New File: `src/types/scoring-config.types.ts`

Create this file with the following complete TypeScript types. Every field name and every enum value must match the backend Pydantic schemas exactly.

```typescript
import { RatingLabel } from './enums';

// ── Enums ─────────────────────────────────────────────────────────

export const ScoringPreset = {
  STANDARD: 'standard',
  STRICT:   'strict',
  LENIENT:  'lenient',
  BINARY:   'binary',
  SALES:    'sales',
  CUSTOM:   'custom',
} as const;
export type ScoringPreset = typeof ScoringPreset[keyof typeof ScoringPreset];

// ── Core types ────────────────────────────────────────────────────

export interface KPIScoringConfig {
  id: string;
  name: string;
  description: string | null;
  preset: ScoringPreset;
  // All threshold values are achievement % required for that rating
  exceptional_min: number;    // default 120.0
  exceeds_min: number;        // default 100.0
  meets_min: number;          // default 80.0
  partially_meets_min: number; // default 60.0
  does_not_meet_min: number;  // always 0.0 (explicit for clarity)
  achievement_cap: number;    // default 200.0 — max achievable score
  adjustment_justification_threshold: number | null;
  is_system_preset: boolean;  // true = seeded, read-only
  organisation_id: string | null;
  summary: string;            // auto-computed: "Exceptional:≥120% | Exceeds:≥100% | ..."
  created_at: string;
}

export interface KPIScoringConfigCreate {
  name: string;
  description?: string;
  preset: ScoringPreset;
  exceptional_min: number;
  exceeds_min: number;
  meets_min: number;
  partially_meets_min: number;
  achievement_cap: number;
  adjustment_justification_threshold?: number;
}

export interface KPIScoringConfigUpdate extends Partial<KPIScoringConfigCreate> {}

export interface EffectiveScoringConfig extends KPIScoringConfig {
  // Which config level is actually being used for a target
  source: 'target_override' | 'kpi_default' | 'cycle_default';
  source_name: string;  // human-readable: "Safety Compliance" or "Standard (system)"
}

export interface ScoringConfigPreviewPoint {
  achievement_pct: number;
  rating: RatingLabel;
  label: string;         // "Meets Expectations"
  colour: string;        // Tailwind colour class for the UI badge
}

export interface AssignScoringConfigRequest {
  scoring_config_id: string | null;  // null = remove override, fall back to higher-level
}

// ── Utility: client-side rating computation ────────────────────────
// Mirrors backend determine_rating_with_config() — used for live preview
export function computeRatingFromConfig(
  achievementPct: number,
  config: Pick<KPIScoringConfig, 'exceptional_min' | 'exceeds_min' | 'meets_min' | 'partially_meets_min' | 'achievement_cap'>
): RatingLabel {
  const capped = Math.min(achievementPct, config.achievement_cap);
  if (capped >= config.exceptional_min)    return 'exceptional';
  if (capped >= config.exceeds_min)        return 'exceeds_expectations';
  if (capped >= config.meets_min)          return 'meets_expectations';
  if (capped >= config.partially_meets_min) return 'partially_meets';
  return 'does_not_meet';
}

export const RATING_COLOURS: Record<RatingLabel, string> = {
  exceptional:            'bg-emerald-100 text-emerald-800 border-emerald-300',
  exceeds_expectations:   'bg-green-100 text-green-800 border-green-300',
  meets_expectations:     'bg-blue-100 text-blue-800 border-blue-300',
  partially_meets:        'bg-amber-100 text-amber-800 border-amber-300',
  does_not_meet:          'bg-red-100 text-red-800 border-red-300',
  not_rated:              'bg-gray-100 text-gray-500 border-gray-300',
};

export const RATING_LABELS: Record<RatingLabel, string> = {
  exceptional:            '⭐ Exceptional',
  exceeds_expectations:   '✅ Exceeds Expectations',
  meets_expectations:     '✓ Meets Expectations',
  partially_meets:        '⚠️ Partially Meets',
  does_not_meet:          '❌ Does Not Meet',
  not_rated:              '— Not Rated',
};

export const PRESET_DEFAULTS: Record<Exclude<ScoringPreset, 'custom'>, Omit<KPIScoringConfigCreate, 'name' | 'description' | 'preset'>> = {
  standard: { exceptional_min: 120, exceeds_min: 100, meets_min: 80,  partially_meets_min: 60,  achievement_cap: 200 },
  strict:   { exceptional_min: 130, exceeds_min: 110, meets_min: 95,  partially_meets_min: 80,  achievement_cap: 200 },
  lenient:  { exceptional_min: 110, exceeds_min: 90,  meets_min: 70,  partially_meets_min: 50,  achievement_cap: 200 },
  binary:   { exceptional_min: 100, exceeds_min: 100, meets_min: 90,  partially_meets_min: 0,   achievement_cap: 100 },
  sales:    { exceptional_min: 120, exceeds_min: 100, meets_min: 85,  partially_meets_min: 70,  achievement_cap: 200 },
};
```

---

## 1.2 New Mock Data: `src/mocks/scoring_configs.json`

Create this file with exactly 6 entries — 5 system presets (read-only) and 1 custom org config:

```json
[
  {
    "id": "sc-system-standard",
    "name": "Standard",
    "preset": "standard",
    "exceptional_min": 120, "exceeds_min": 100, "meets_min": 80, "partially_meets_min": 60,
    "does_not_meet_min": 0, "achievement_cap": 200,
    "is_system_preset": true, "organisation_id": null,
    "summary": "Exceptional:≥120% | Exceeds:≥100% | Meets:≥80% | Partial:≥60%",
    "description": "Default balanced thresholds for most KPIs",
    "adjustment_justification_threshold": null,
    "created_at": "2025-01-01T00:00:00Z"
  },
  {
    "id": "sc-system-strict",
    "name": "Strict",
    "preset": "strict",
    "exceptional_min": 130, "exceeds_min": 110, "meets_min": 95, "partially_meets_min": 80,
    "does_not_meet_min": 0, "achievement_cap": 200,
    "is_system_preset": true, "organisation_id": null,
    "summary": "Exceptional:≥130% | Exceeds:≥110% | Meets:≥95% | Partial:≥80%",
    "description": "High-bar thresholds for compliance, safety, and quality KPIs",
    "adjustment_justification_threshold": 5.0,
    "created_at": "2025-01-01T00:00:00Z"
  },
  {
    "id": "sc-system-lenient",
    "name": "Lenient",
    "preset": "lenient",
    "exceptional_min": 110, "exceeds_min": 90, "meets_min": 70, "partially_meets_min": 50,
    "does_not_meet_min": 0, "achievement_cap": 200,
    "is_system_preset": true, "organisation_id": null,
    "summary": "Exceptional:≥110% | Exceeds:≥90% | Meets:≥70% | Partial:≥50%",
    "description": "Wider bands for innovation, R&D, and aspirational KPIs",
    "adjustment_justification_threshold": null,
    "created_at": "2025-01-01T00:00:00Z"
  },
  {
    "id": "sc-system-binary",
    "name": "Binary (Pass/Fail)",
    "preset": "binary",
    "exceptional_min": 100, "exceeds_min": 100, "meets_min": 90, "partially_meets_min": 0,
    "does_not_meet_min": 0, "achievement_cap": 100,
    "is_system_preset": true, "organisation_id": null,
    "summary": "Meets:≥90% | Does Not Meet:<90% (binary rating only)",
    "description": "Pass/fail for compliance checkboxes and certification KPIs",
    "adjustment_justification_threshold": null,
    "created_at": "2025-01-01T00:00:00Z"
  },
  {
    "id": "sc-system-sales",
    "name": "Sales Org",
    "preset": "sales",
    "exceptional_min": 120, "exceeds_min": 100, "meets_min": 85, "partially_meets_min": 70,
    "does_not_meet_min": 0, "achievement_cap": 200,
    "is_system_preset": true, "organisation_id": null,
    "summary": "Exceptional:≥120% | Exceeds:≥100% | Meets:≥85% | Partial:≥70%",
    "description": "Sales-optimised thresholds — slightly higher bar for Meets",
    "adjustment_justification_threshold": null,
    "created_at": "2025-01-01T00:00:00Z"
  },
  {
    "id": "sc-custom-safety",
    "name": "Safety Compliance",
    "preset": "custom",
    "exceptional_min": 100, "exceeds_min": 99, "meets_min": 98, "partially_meets_min": 95,
    "does_not_meet_min": 0, "achievement_cap": 100,
    "is_system_preset": false, "organisation_id": "org-001",
    "summary": "Meets:≥98% | Partial:≥95% | DNM:<95% — near-zero tolerance",
    "description": "Zero tolerance for non-compliance. 97% still triggers partial rating.",
    "adjustment_justification_threshold": 2.0,
    "created_at": "2025-03-01T00:00:00Z"
  }
]
```

---

## 1.3 New RTK Query Endpoints: `src/services/endpoints/scoringConfigEndpoints.ts`

Create this file, injecting into the existing `apiService`. Implement all methods with `fakeBaseQuery` + mock data + simulated 300–600ms latency:

```typescript
// Endpoints to implement:
//
// listScoringConfigs       → GET /scoring/configs/        (providesTags: ['ScoringConfig'])
// getScoringConfig         → GET /scoring/configs/{id}
// createScoringConfig      → POST /scoring/configs/       (invalidatesTags: ['ScoringConfig'])
// updateScoringConfig      → PUT  /scoring/configs/{id}   (system presets return 403)
// deleteScoringConfig      → DEL  /scoring/configs/{id}   (system presets return 403)
// createFromPreset         → POST /scoring/configs/from-preset
// previewScoringConfig     → GET  /scoring/configs/{id}/preview?values=50,60,75,85,95,100,110,120,130
//
// assignScoringConfigToKPI     → PATCH /kpis/{kpiId}/scoring-config
// assignScoringConfigToTarget  → PATCH /targets/{targetId}/scoring-config
// getEffectiveScoringConfig    → GET   /targets/{targetId}/scoring-config
//
// Client-side validation rule (mirror backend Pydantic validator):
//   exceptional_min > exceeds_min > meets_min > partially_meets_min >= 0
//   If violated: return { error: { status: 422, error: 'Thresholds must be strictly descending' } }
//
// previewScoringConfig: compute client-side using computeRatingFromConfig()
//   for values [0,10,20,30,40,50,60,65,70,75,80,85,90,95,100,105,110,115,120,125,130]
//   return ScoringConfigPreviewPoint[] with rating + colour
```

---

## 1.4 New Component: `src/features/scoring/components/ScoringConfigManager.tsx`

Build a full-page component with three shadcn `Tabs`:

### Tab 1 — "All Configs" (list view)

```
┌────────────────────────────────────────────────────────────────────┐
│  Scoring Configurations                          [+ New Config]     │
│                                                                     │
│  All Configs  |  Builder  |  Preview                               │
│  ─────────────────────────────────────────────────────────────     │
│  Name              Preset    Thresholds             Used by  Action│
│  Standard          System  ≥120/100/80/60        12 KPIs    🔒 View│
│  Strict            System  ≥130/110/95/80         3 KPIs    🔒 View│
│  Safety Compliance Custom  ≥100/99/98/95           1 KPI   ✏️ Edit │
│                                                              🗑 Del │
└────────────────────────────────────────────────────────────────────┘
```

Rules:
- System presets show a `🔒 Lock` icon — no Edit or Delete actions
- "Used by N KPIs" is computed from mock kpis data (count of kpis with matching scoring_config_id)
- Clicking a row name opens a read-only detail popover showing all thresholds

### Tab 2 — "Builder" (create/edit form)

Field layout (use react-hook-form + zod):

```
Name:        [___________________________]
Description: [___________________________]

Start from preset: [Standard ▾]  ← populates all fields when changed

Thresholds:
  ┌──────────────────────────────────────────────────────────────┐
  │  ⭐ Exceptional    ≥ [120] %  ███████████████████████████    │
  │  ✅ Exceeds        ≥ [100] %  █████████████████████          │
  │  ✓  Meets          ≥ [ 80] %  ████████████████               │
  │  ⚠️  Partially M.  ≥ [ 60] %  ████████████                   │
  │  ❌ Does Not Meet  <   60  %  (auto = partially_meets_min)   │
  └──────────────────────────────────────────────────────────────┘

  Each threshold row has:
  - A colour-coded icon matching RATING_COLOURS
  - A number input (0–500, step 1)
  - A visual bar (width = threshold/200 * 100%) using the rating colour

Achievement Cap: [200] %
  ℹ️ Scores above this % are capped before rating is determined

  [Validate]  ← shows inline error if thresholds not strictly descending
  [Save Config]  [Cancel]
```

Zod schema validation (client-side):
```typescript
const schema = z.object({
  name: z.string().min(2).max(100),
  exceptional_min: z.number().min(0).max(500),
  exceeds_min: z.number().min(0).max(500),
  meets_min: z.number().min(0).max(500),
  partially_meets_min: z.number().min(0).max(500),
  achievement_cap: z.number().min(100).max(1000),
}).refine(
  d => d.exceptional_min > d.exceeds_min && d.exceeds_min > d.meets_min && d.meets_min > d.partially_meets_min,
  { message: 'Thresholds must be strictly descending: Exceptional > Exceeds > Meets > Partial' }
);
```

### Tab 3 — "Preview" (interactive live preview)

```
┌────────────────────────────────────────────────────────────────────┐
│  Config to preview: [Safety Compliance ▾]                          │
│                                                                     │
│  Achievement %:  88  ←──────────────────────────── [slider 0-150] │
│                                                                     │
│  ┌────────────────────────┬──────────────────────────────────────┐ │
│  │ Under "Safety":         │ ⚠️ PARTIALLY MEETS (needs ≥98%)     │ │
│  │ Under "Standard":       │ ✓  MEETS EXPECTATIONS               │ │
│  └────────────────────────┴──────────────────────────────────────┘ │
│                                                                     │
│  Full threshold comparison:                                         │
│  Rating          Safety Compliance   Standard   Difference         │
│  Exceptional     ≥ 100%              ≥ 120%     Safety is stricter │
│  Exceeds         ≥  99%              ≥ 100%                        │
│  Meets           ≥  98%              ≥  80%     ← 18pt gap         │
│  Partially Meets ≥  95%              ≥  60%                        │
│                                                                     │
│  Full spectrum (0%–150%):                                           │
│  [colour-coded bar: red|orange|amber|green|emerald from 0→150%]   │
└────────────────────────────────────────────────────────────────────┘
```

Implementation notes:
- Slider uses shadcn `Slider` component (0–150 range)
- Bar uses CSS linear-gradient with stops at each threshold
- Comparison always shows "Standard" as the reference config regardless of selection
- All computation done client-side via `computeRatingFromConfig()`

---

## 1.5 Update Existing: `src/features/kpis/components/KPIBuilderForm.tsx`

In **Step 4 — Scoring**, add a scoring config selector **below** the existing scoring direction toggle:

```tsx
// Add after the ScoringDirection radio group in Step 4:

<div className="space-y-2">
  <Label>KPI-Level Scoring Config (optional)</Label>
  <Select
    value={form.watch('scoring_config_id') ?? ''}
    onValueChange={(val) => form.setValue('scoring_config_id', val || null)}
  >
    <SelectTrigger>
      <SelectValue placeholder="Use cycle default" />
    </SelectTrigger>
    <SelectContent>
      <SelectItem value="">Use cycle default</SelectItem>
      {scoringConfigs?.map(config => (
        <SelectItem key={config.id} value={config.id}>
          {config.is_system_preset ? '🔒 ' : '✏️ '}{config.name}
        </SelectItem>
      ))}
      <SelectSeparator />
      <SelectItem value="__create_new__">+ Create new config...</SelectItem>
    </SelectContent>
  </Select>

  {/* Show threshold summary when a non-default config is selected */}
  {selectedConfig && (
    <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800">
      <span className="font-medium">{selectedConfig.name}: </span>
      {selectedConfig.summary}
    </div>
  )}

  <p className="text-xs text-muted-foreground">
    Sets the default scoring thresholds for this KPI across all assignments.
    Individual targets can further override this.
  </p>
</div>
```

When "Create new config..." is selected, open `ScoringConfigManager` in a `Dialog` (not a full navigation — keep the user in the KPI builder).

---

## 1.6 Update Existing: `src/features/targets/components/TargetSetPage.tsx`

For each KPI target row in the assignment form, add a collapsible "Scoring Override" section:

```tsx
// Add inside each target KPI row, below weight input:

<Collapsible>
  <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
    <Settings2 className="h-3 w-3" />
    Scoring override
    {target.scoring_config_id ? (
      <Badge variant="outline" className="ml-2 text-xs">Custom</Badge>
    ) : null}
  </CollapsibleTrigger>
  <CollapsibleContent className="mt-2 space-y-2">

    {/* Effective config display (read from getEffectiveScoringConfig) */}
    <div className="rounded border bg-muted/30 p-2 text-xs">
      <p className="font-medium text-foreground">Effective config:</p>
      <p className="text-muted-foreground">{effectiveConfig?.summary}</p>
      <p className="text-muted-foreground text-[10px] mt-0.5">
        source: {effectiveConfig?.source_name}
      </p>
    </div>

    {/* Override selector (managers and hr_admin only) */}
    <Select
      value={target.scoring_config_id ?? ''}
      onValueChange={(val) => updateTargetScoringConfig(target.id, val || null)}
    >
      <SelectTrigger className="h-8 text-xs">
        <SelectValue placeholder="Inherit from KPI / cycle" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="">Inherit (no override)</SelectItem>
        {scoringConfigs?.map(c => (
          <SelectItem key={c.id} value={c.id} className="text-xs">
            {c.name} — {c.summary}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>

  </CollapsibleContent>
</Collapsible>
```

---

## 1.7 Update Existing: `src/features/scoring/components/KPIScorecardTable.tsx`

Update the Rating column to show a tooltip explaining which config produced the rating:

```tsx
// Replace the Rating cell with:
<TableCell>
  <TooltipProvider>
    <Tooltip>
      <TooltipTrigger>
        <Badge className={RATING_COLOURS[score.rating]}>
          {RATING_LABELS[score.rating]}
        </Badge>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">
        <div className="space-y-1 text-xs">
          <p className="font-semibold">Scoring Config Used:</p>
          <p>{score.scoring_config_snapshot?.source_name ?? 'Standard'}</p>
          <p className="text-muted-foreground">
            Source: {score.scoring_config_snapshot?.source ?? 'cycle_default'}
          </p>
          <Separator className="my-1" />
          <p className="font-medium">Thresholds that applied:</p>
          {score.scoring_config_snapshot && (
            <ul className="space-y-0.5">
              <li>⭐ Exceptional: ≥{score.scoring_config_snapshot.exceptional_min}%</li>
              <li>✅ Exceeds: ≥{score.scoring_config_snapshot.exceeds_min}%</li>
              <li>✓ Meets: ≥{score.scoring_config_snapshot.meets_min}%</li>
              <li>⚠️ Partial: ≥{score.scoring_config_snapshot.partially_meets_min}%</li>
            </ul>
          )}
          <Separator className="my-1" />
          <p className="text-muted-foreground">
            Achievement {score.achievement_percentage?.toFixed(1)}% → {RATING_LABELS[score.rating]}
          </p>
        </div>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</TableCell>
```

---

# PART 2 — FRONTEND: ENHANCEMENT 2 (Formula Variables & Data Binding)

## 2.1 New File: `src/types/integration.types.ts`

```typescript
// ── Enums ─────────────────────────────────────────────────────────

export const VariableSourceType = {
  MANUAL:           'manual',
  REST_API:         'rest_api',
  DATABASE:         'database',
  INFLUXDB:         'influxdb',
  WEBHOOK_RECEIVE:  'webhook_receive',
  KPI_ACTUAL:       'kpi_actual',
  CSV_UPLOAD:       'csv_upload',
  FORMULA:          'formula',
} as const;
export type VariableSourceType = typeof VariableSourceType[keyof typeof VariableSourceType];

export const VariableDataType = {
  NUMBER:         'number',
  INTEGER:        'integer',
  PERCENTAGE:     'percentage',
  CURRENCY:       'currency',
  BOOLEAN:        'boolean',
  DURATION_HOURS: 'duration_hours',
} as const;
export type VariableDataType = typeof VariableDataType[keyof typeof VariableDataType];

export const SyncStatus = {
  NEVER_SYNCED: 'never_synced',
  SYNCING:      'syncing',
  SUCCESS:      'success',
  FAILED:       'failed',
  PARTIAL:      'partial',
} as const;
export type SyncStatus = typeof SyncStatus[keyof typeof SyncStatus];

// ── Core types ────────────────────────────────────────────────────

export interface KPIVariable {
  id: string;
  kpi_id: string;
  variable_name: string;        // uppercase: "REVENUE" — matches formula reference
  display_label: string;        // "Total Monthly Revenue (MYR)"
  description: string | null;
  data_type: VariableDataType;
  unit_label: string | null;    // "MYR", "units", "hours"
  source_type: VariableSourceType;
  source_config: Record<string, unknown> | null;
  is_required: boolean;
  default_value: number | null;
  auto_sync_enabled: boolean;
  last_synced_at: string | null;
  last_sync_status: SyncStatus;
  last_sync_error: string | null;
  display_order: number;
  organisation_id: string;
}

export interface KPIVariableWithValue extends KPIVariable {
  current_value: number | null;        // latest variable_actual.raw_value
  current_period: string | null;       // "2025-03"
  synced_minutes_ago: number | null;   // computed from last_synced_at
  needs_manual_entry: boolean;         // source_type === 'manual' && current_value === null
}

export interface VariableActualSubmit {
  variable_id: string;
  kpi_id: string;
  period_date: string;
  raw_value: number;
}

export interface VariableActualsBulk {
  entries: VariableActualSubmit[];
}

export interface VariableCurrentValues {
  kpi_id: string;
  period_date: string;
  values: Record<string, number | null>;  // { "REVENUE": 1200000, "EXPENSES": null }
  computed_result: number | null;          // formula evaluated with resolved values (null if any required missing)
  missing_variables: string[];            // variable names with no value
}

export interface AdapterField {
  name: string;
  type: 'string' | 'select' | 'number' | 'kvpairs' | 'list' | 'sql' | 'secret_ref' | 'readonly';
  label: string;
  required: boolean;
  hint?: string;
  options?: string[];
  default?: unknown;
}

export interface AdapterSchema {
  name: string;
  description: string;
  fields: AdapterField[];
}

export interface AdapterTestResult {
  success: boolean;
  value: number | null;
  error: string | null;
  response_time_ms: number;
  metadata: Record<string, unknown>;
}
```

---

## 2.2 New Mock Data: `src/mocks/kpi_variables.json`

```json
[
  {
    "id": "var-001",
    "kpi_id": "kpi-001",
    "variable_name": "REVENUE",
    "display_label": "Current Month Total Revenue (MYR)",
    "description": "Pulled from SAP ERP monthly sales close",
    "data_type": "currency",
    "unit_label": "MYR",
    "source_type": "rest_api",
    "source_config": {
      "adapter": "rest_api",
      "url": "https://erp.company.com/api/v1/revenue/monthly?month={period.iso}",
      "method": "GET",
      "headers": { "Authorization": "Bearer {SECRET:ERP_API_TOKEN}" },
      "response_path": "data.total_revenue",
      "timeout_seconds": 30
    },
    "is_required": true,
    "default_value": null,
    "auto_sync_enabled": true,
    "last_sync_status": "success",
    "last_synced_at": "2025-06-01T01:30:00Z",
    "last_sync_error": null,
    "display_order": 0,
    "kpi_id": "kpi-001",
    "organisation_id": "org-001"
  },
  {
    "id": "var-002",
    "kpi_id": "kpi-001",
    "variable_name": "PRIOR_REVENUE",
    "display_label": "Prior Month Total Revenue (MYR)",
    "description": "Previous month revenue — enter manually from finance report",
    "data_type": "currency",
    "unit_label": "MYR",
    "source_type": "manual",
    "source_config": null,
    "is_required": true,
    "default_value": null,
    "auto_sync_enabled": false,
    "last_sync_status": "never_synced",
    "last_synced_at": null,
    "last_sync_error": null,
    "display_order": 1,
    "organisation_id": "org-001"
  }
]
```

---

## 2.3 New RTK Query: `src/services/endpoints/variableEndpoints.ts`

```typescript
// Endpoints to implement with fakeBaseQuery + mock data:
//
// listKPIVariables(kpiId)         → GET /kpis/{id}/variables/
//   Returns KPIVariableWithValue[] — enriches with current_value from variable_actuals mock
//   providesTags: [{ type: 'KPIVariable', id: kpiId }]
//
// createKPIVariable({ kpiId, data }) → POST /kpis/{id}/variables/
//   Validate variable_name regex: /^[A-Z][A-Z0-9_]{0,49}$/
//   If fails: return error "Variable name must be uppercase letters and underscores"
//   invalidatesTags: [{ type: 'KPIVariable', id: kpiId }, { type: 'KPI', id: kpiId }]
//
// updateKPIVariable({ kpiId, varId, data }) → PUT /kpis/{id}/variables/{var_id}
// deleteKPIVariable({ kpiId, varId })       → DELETE /kpis/{id}/variables/{var_id}
// reorderKPIVariables({ kpiId, orderedIds }) → PATCH /kpis/{id}/variables/reorder
//
// testVariableSync({ kpiId, varId, periodDate }) → POST /kpis/{id}/variables/{var_id}/test-sync
//   Simulate: return { success: true, value: 1234567.89, response_time_ms: 342, metadata: {...} }
//   Add 1-2s delay to simulate real API call
//
// submitManualVariables({ kpiId, period, values }) → POST /actuals/variables/
//   values: Record<string, number>  e.g. { "PRIOR_REVENUE": 1050000 }
//   invalidatesTags: ['VariableActual', 'Actual']
//
// getVariableValues(kpiId, period) → GET /actuals/variables/{kpi_id}/{period}
//   Returns VariableCurrentValues with computed_result
//   Compute formula client-side using evaluateFormula() if all values present
//
// triggerBulkSync(kpiId)          → POST /actuals/variables/bulk-sync/{kpi_id}
//   Simulates syncing all auto-sync variables; returns count synced
//
// listAdapters()                  → GET /integrations/adapters/
//   Return hardcoded adapter schemas for: rest_api, database, webhook_receive, kpi_actual
//
// testAdapterConfig({ config, periodDate }) → POST /integrations/adapters/test
//   Simulate 1-2s delay; return AdapterTestResult with mock values
```

---

## 2.4 New Utility: `src/lib/formulaEvaluator.ts`

```typescript
/**
 * Client-side formula evaluator — mirrors backend FormulaEvaluator.
 * Used for live preview in the actuals entry form.
 *
 * Security: variable values are substituted BEFORE any eval-like call.
 * After substitution, only digits and arithmetic operators remain.
 *
 * Supported: + - * / ** % ( ) abs() round() min() max() IF(cond, a, b)
 * Variables: uppercase identifiers — REVENUE, EXPENSES
 */

export interface EvaluationResult {
  result: number | null;
  error: string | null;
  missing: string[];          // variable names with null values
}

const VARIABLE_REGEX = /\b([A-Z][A-Z0-9_]*)\b/g;
const SAFE_AFTER_SUBSTITUTION = /^[0-9+\-*/.()%, ]*$/;

export function extractVariableNames(expression: string): string[] {
  const FUNCTION_NAMES = new Set(['ABS', 'ROUND', 'MIN', 'MAX', 'IF']);
  const matches = [...expression.matchAll(VARIABLE_REGEX)].map(m => m[1]);
  return [...new Set(matches.filter(name => !FUNCTION_NAMES.has(name)))];
}

export function evaluateFormula(
  expression: string,
  variables: Record<string, number | null>,
): EvaluationResult {
  const required = extractVariableNames(expression);
  const missing = required.filter(name => variables[name] === null || variables[name] === undefined);

  if (missing.length > 0) {
    return { result: null, error: null, missing };
  }

  try {
    let expr = expression
      .replace(/\bIF\s*\(/gi, 'if_func(')
      .replace(/\bABS\s*\(/gi, 'Math.abs(')
      .replace(/\bROUND\s*\(/gi, 'Math.round(')
      .replace(/\bMIN\s*\(/gi, 'Math.min(')
      .replace(/\bMAX\s*\(/gi, 'Math.max(');

    // Substitute variable values
    for (const [name, value] of Object.entries(variables)) {
      if (value !== null) {
        expr = expr.replace(new RegExp(`\\b${name}\\b`, 'g'), String(value));
      }
    }

    // Inject if_func helper
    const ifFunc = (condition: boolean, trueVal: number, falseVal: number) =>
      condition ? trueVal : falseVal;

    // Safety check: after substitution, should only have safe chars
    const withoutMath = expr.replace(/Math\.(abs|round|min|max)/g, '').replace(/if_func/g, '');
    if (!SAFE_AFTER_SUBSTITUTION.test(withoutMath.replace(/[a-z_(),\s]/g, ''))) {
      return { result: null, error: 'Formula contains unsafe characters after variable substitution', missing: [] };
    }

    // eslint-disable-next-line no-new-func
    const fn = new Function('Math', 'if_func', `"use strict"; return (${expr});`);
    const result = fn(Math, ifFunc) as number;

    if (!isFinite(result)) {
      return { result: null, error: 'Result is not finite (possible division by zero)', missing: [] };
    }
    return { result: Math.round(result * 10000) / 10000, error: null, missing: [] };

  } catch (e) {
    return { result: null, error: `Evaluation error: ${e instanceof Error ? e.message : String(e)}`, missing: [] };
  }
}

export function validateFormulaClient(
  expression: string,
  definedVariableNames: string[],
): { valid: boolean; errors: string[]; referencedVariables: string[] } {
  const errors: string[] = [];
  if (!expression?.trim()) {
    errors.push('Formula expression cannot be empty');
    return { valid: false, errors, referencedVariables: [] };
  }

  const referenced = extractVariableNames(expression);
  const definedSet = new Set(definedVariableNames);
  const undefined_ = referenced.filter(name => !definedSet.has(name));

  if (undefined_.length > 0) {
    errors.push(`Undefined variables: ${undefined_.join(', ')}. Add them as KPI variables first.`);
  }

  // Basic syntax check: balanced parentheses
  let depth = 0;
  for (const ch of expression) {
    if (ch === '(') depth++;
    if (ch === ')') depth--;
    if (depth < 0) { errors.push('Unbalanced parentheses'); break; }
  }
  if (depth !== 0) errors.push('Unbalanced parentheses');

  return { valid: errors.length === 0, errors, referencedVariables: referenced };
}
```

---

## 2.5 New Component: `src/features/kpis/components/KPIVariableManager.tsx`

Build a panel used inside the KPI detail drawer and KPI builder Step 3.

### Layout:

```
FORMULA VARIABLES
────────────────────────────────────────────────────────────
[+ Add Variable]                              [🔄 Sync All]

  ⠿  REVENUE     Total Monthly Revenue    REST API  ✅ 5m ago  [⚙️ Config] [🗑]
  ⠿  PRIOR_REV   Prior Month Revenue      Manual    ⚠️ Needed  [⚙️ Config] [🗑]
  ⠿  HEADCOUNT   Active Employees         HRMS API  ✅ 2h ago  [⚙️ Config] [🗑]

────────────────────────────────────────────────────────────
Formula:  (REVENUE - PRIOR_REVENUE) / PRIOR_REVENUE * 100
          ✅ All variables defined   ✅ Syntax valid
```

Features:
- dnd-kit `SortableContext` for drag-to-reorder (updates display_order)
- Source type shown as a coloured badge:
  - `manual` → gray "Manual"
  - `rest_api` → blue "REST API"
  - `database` → purple "Database"
  - `webhook_receive` → orange "Webhook"
  - `kpi_actual` → green "KPI Reference"
- Status indicator next to each variable:
  - `✅ X min/hours ago` — last successful sync (non-manual)
  - `⚠️ Entry needed` — manual with no value this period
  - `❌ Sync failed` — last_sync_status === 'failed' — show error in tooltip
  - `—` — webhook_receive (passive)
- Formula analysis bar at the bottom: runs `validateFormulaClient()` on the KPI's formula and shows which defined variables are referenced, which are unused, and whether syntax is valid

### Add Variable Dialog:

```
Add Variable
──────────────────────────────────────────
Variable Name (uppercase):  [REVENUE      ]
  ℹ️ Used in formula as: (REVENUE - ...)

Display Label:  [Total Monthly Revenue (MYR)  ]
Data Type:      [Currency ▾]
Unit Label:     [MYR       ]
Required:       [✅ Yes ▾]
Default value:  [          ] (only if not required)

Source Type:    [REST API ▾]

  ← AdapterConfigForm renders here based on source type →

[Test Connection]  [Add Variable]  [Cancel]
```

---

## 2.6 New Component: `src/features/integrations/components/AdapterConfigForm.tsx`

A **dynamic form** that renders fields based on the `AdapterSchema` fetched from the adapter registry. Used inside the Add Variable dialog.

```typescript
// Props:
interface Props {
  adapterName: string;          // 'rest_api' | 'database' | 'webhook_receive' | 'kpi_actual'
  value: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  onTest?: (result: AdapterTestResult) => void;
}
```

Field type rendering:
- `string` → `Input` text field
- `select` → `Select` with options from schema
- `number` → `Input` type="number"
- `kvpairs` → dynamic key-value pairs (add/remove rows)
- `sql` → `Textarea` with monospace font
- `secret_ref` → `Input` with a lock icon, placeholder `{SECRET:MY_KEY_NAME}`, shows warning if user types a raw credential
- `readonly` → disabled `Input` (for webhook endpoint_key — auto-generated)

Always render a "[🔬 Test Connection]" button at the bottom (calls `testAdapterConfig`):
```
[🔬 Test Connection for March 2025]
  → Loading...
  → ✅ Connected — value: MYR 1,234,567.00  (342ms)
  → ❌ Failed: HTTP 403 from endpoint
```

---

## 2.7 Update Existing: `src/features/actuals/components/ActualEntryPage.tsx`

**This is the most important frontend change.** For formula KPIs, replace the single actual value input with a variable entry panel.

Add a helper hook:
```typescript
function useActualEntryMode(target: KPITarget) {
  const kpi = target.kpi;
  return kpi.data_source === 'formula' ? 'formula' : 'direct';
}
```

For `formula` mode, render:

```
┌─────────────────────────────────────────────────────────────────┐
│  Revenue Growth — March 2025                                    │
│  Formula: (REVENUE - PRIOR_REVENUE) / PRIOR_REVENUE × 100      │
│                                                                 │
│  ── INPUT VARIABLES ─────────────────────────────────────────   │
│                                                                 │
│  REVENUE  — Total Monthly Revenue (MYR)                         │
│  [🔄 REST API — SAP ERP]                                        │
│  ✅ MYR 1,200,000.00    Synced 5 min ago    [🔄 Refresh]        │
│                                                                 │
│  PRIOR_REVENUE  — Prior Month Revenue (MYR)  ← manual          │
│  MYR [___________________]                   ← type here        │
│  ⚠️ Required — enter the prior month's total revenue           │
│                                                                 │
│  ── COMPUTED RESULT ─────────────────────────────────────────   │
│                                                                 │
│  Formula preview:                                               │
│  (1,200,000 − PRIOR_REVENUE) ÷ PRIOR_REVENUE × 100             │
│                                                                 │
│  = [waiting for PRIOR_REVENUE...]                               │
│  ← updates live as user types →                                 │
│  = 14.29%   ← once PRIOR_REVENUE is entered                    │
│                                                                 │
│  vs Target: 15.0%    Achievement: 95.3%    ✓ Meets Expectations │
│  (using Sales Org config: Meets ≥85%)                           │
│                                                                 │
│  [Submit]   [Save Draft]                                        │
└─────────────────────────────────────────────────────────────────┘
```

Implementation details:
- Use `useState` for manual variable values keyed by `variable_name`
- Call `evaluateFormula()` from `formulaEvaluator.ts` on every keystroke (debounced 300ms)
- Achievement % = `result / target.target_value * 100` — compute client-side
- Rating preview uses `computeRatingFromConfig()` with the target's effective scoring config
- Refresh button calls `triggerBulkSync(kpiId)` mutation — shows spinner for 1-2s
- On Submit: call `submitManualVariables` for all manual values, then `submitActual` with the computed result

---

## 2.8 Update Existing: `src/features/kpis/components/KPIBuilderForm.tsx`

In **Step 3 — Data Source**, when user selects "Formula":

1. Show the formula expression textarea (already exists)
2. Below the textarea, render `KPIVariableManager` inline (not in a drawer — keep user in the form flow)
3. Below the variable manager, show the formula validation result from `validateFormulaClient()`
4. Show a live preview: "Test formula with sample values" — renders editable inputs for each variable and shows the computed result

---

## 2.9 Update Existing: `src/features/kpis/components/KPIDetailDrawer.tsx`

In the **Formula tab** (shown for data_source = 'formula'):

Replace the current stub with:
1. Formula expression display (syntax-highlighted, monospace)
2. `KPIVariableManager` component showing all variables with their current sync status
3. "Variable Actuals History" table: last 6 periods, each row shows values for all variables + computed result

---

# PART 3 — DOCUMENTATION CONSOLIDATION

## 3.1 Create `MASTER_USER_GUIDE.md` at Repo Root

**This replaces all of the following files** (do not delete them yet — reference them and then mark as deprecated at the top):
- `PART1-project-setup.md`
- `PART2-kpi-core.md`
- `PART3-targets-actuals.md`
- `PART4-scoring-dashboards.md`
- `PART5-notifications-tasks.md`
- `FRONTEND-pms-kpi-ui.md`
- `ENHANCE1-per-kpi-scoring.md`
- `ENHANCE2-formula-variables.md`
- `ENHANCE3-documentation-update.md`

The `MASTER_USER_GUIDE.md` must contain **all** of the following sections in order. Do not abbreviate any section — write it in full:

### Structure of `MASTER_USER_GUIDE.md`:

```markdown
# Performance Management System — KPI Module
## Master User Guide & Developer Reference
**Version**: 2.0 (includes scoring config enhancement + formula variables)
**Last updated**: [today's date]

---
> ⚠️ This is the single source of truth. Do not update any other .md file.
> All previous prompt files (PART1–5, FRONTEND, ENHANCE1–3) are archived.

---

## Table of Contents
1. [System Overview & Business Value](#1-system-overview)
2. [Architecture](#2-architecture)
3. [User Roles & Permissions](#3-user-roles)
4. [Onboarding Guide](#4-onboarding)
5. [Employee: Screen by Screen](#5-employee-guide)
6. [Manager: Screen by Screen](#6-manager-guide)
7. [HR Admin: Screen by Screen](#7-hr-admin-guide)
8. [Executive: Screen by Screen](#8-executive-guide)
9. [KPI Scoring System — How It Works](#9-scoring-system)
10. [Formula Variables & External Data](#10-formula-variables)
11. [Notifications & Alerts](#11-notifications)
12. [Backend Reference](#12-backend-reference)
13. [Frontend Reference](#13-frontend-reference)
14. [Database Schema](#14-database-schema)
15. [API Endpoint Reference](#15-api-reference)
16. [VS Code Copilot Context Prompt](#16-copilot-prompt)
17. [Changelog](#17-changelog)
```

### Section 9 — KPI Scoring System (this section is new/expanded)

Must include these exact sub-sections:

```markdown
## 9. KPI Scoring System — How It Works

### 9.1 Scoring Formula Reference

Achievement % (higher-is-better): `(actual / target) × 100`
Achievement % (lower-is-better):  `(target / actual) × 100`
Below minimum value:               `0.0` (hard floor — automatic)
Achievement cap:                   `min(result, achievement_cap)` (default: 200%)

Weighted Score: `achievement_pct × (kpi_weight / 100)`

Composite Score: `Σ(weighted_scores) / Σ(weights) × 100`

### 9.2 Rating Thresholds — System Presets

| Preset    | Exceptional | Exceeds | Meets | Partially | Best for         |
|-----------|-------------|---------|-------|-----------|------------------|
| Standard  | ≥120%       | ≥100%   | ≥80%  | ≥60%      | Most KPIs        |
| Strict    | ≥130%       | ≥110%   | ≥95%  | ≥80%      | Safety/Compliance|
| Lenient   | ≥110%       | ≥90%    | ≥70%  | ≥50%      | Innovation/R&D   |
| Binary    | ≥100%       | ≥100%   | ≥90%  | ≥0%       | Pass/Fail KPIs   |
| Sales Org | ≥120%       | ≥100%   | ≥85%  | ≥70%      | Sales teams      |

### 9.3 Scoring Config Precedence (3 Levels)

```
Level 3 — Target Override (HIGHEST)
  Individual employee's target has its own scoring config
  Set by: Manager or HR Admin when assigning the target
  Example: "Alice's Safety Compliance target uses Strict preset"

Level 2 — KPI Default
  A KPI definition has a default scoring config
  Set by: HR Admin when creating/editing a KPI
  Example: "All Safety Compliance KPI assignments default to Strict"

Level 1 — Cycle Default (LOWEST, always present)
  The review cycle has org-wide scoring thresholds
  Set by: HR Admin when creating the review cycle
  Example: "Q3 2025 cycle uses Standard thresholds"
```

Function: `resolve_scoring_config(target, cycle_config) → effective_config`

### 9.4 How to Configure Scoring for a KPI (Step by Step)

1. Navigate to **Settings → Scoring Configs**
2. Choose an existing preset or click **+ New Config**
3. Set threshold values (must be strictly descending)
4. Use **Preview** tab to test with sample achievement percentages
5. Assign to a KPI: **KPI Library → [KPI name] → Edit → Step 4 → Scoring Config**
6. Optionally override per-target: **Targets → [Employee] → [KPI row] → Scoring Override**

### 9.5 Business Examples

**Safety Compliance KPI — Strict preset**
  Target: 100% compliance | Actual: 97%
  Standard scoring: 97% → ✓ Meets Expectations (≥80%)
  Strict scoring:   97% → ⚠️ Partially Meets (needs ≥95% to Meet)
  Business reason: Even 3% non-compliance is unacceptable in safety context

**Innovation Index — Lenient preset**
  Target: Launch 5 experiments | Actual: 4
  Standard scoring: 80% → ✓ Meets Expectations (≥80%)
  Lenient scoring:  80% → ✅ Exceeds Expectations (≥70% is Meets, ≥90% Exceeds)
  Wait — 80% with lenient: still Meets (≥70%)
  At 75% with standard: ⚠️ Partially Meets. At 75% with lenient: ✓ Meets.
  Business reason: Innovation goals are inherently uncertain; penalising near-misses discourages risk
```

### Section 10 — Formula Variables (this section is entirely new)

Must include these exact sub-sections:

```markdown
## 10. Formula Variables & External Data Integration

### 10.1 What Are Formula Variables?

When a KPI's value is calculated from a formula (e.g. Revenue Growth = 
(Revenue - Prior Revenue) / Prior Revenue × 100), the variables in that formula 
(REVENUE, PRIOR_REVENUE) need values for each measurement period.

A KPI Variable is a named, typed slot that:
- Gives the variable a human-readable label
- Specifies where the value comes from (manual entry, ERP API, database, IoT, etc.)
- Stores every value with a full audit trail

### 10.2 Variable Source Types

| Source Type      | How it works                                    | Who enters data    |
|------------------|-------------------------------------------------|--------------------|
| Manual           | Employee types value on Actuals Entry screen     | Employee/Manager   |
| REST API         | PMS calls external HTTP endpoint automatically   | System (scheduled) |
| Database         | PMS runs SQL SELECT on external database          | System (scheduled) |
| InfluxDB         | PMS queries time-series database (IoT)           | System (scheduled) |
| Webhook Receive  | External system pushes data to PMS               | External system    |
| KPI Reference    | Pulls latest actual from another KPI             | System             |

### 10.3 How to Set Up a Formula Variable (HR Admin)

1. Go to **KPI Library → [Formula KPI] → Edit**
2. In **Step 3 — Data Source**, select Formula and enter the expression
3. Click **Manage Variables** below the formula textarea
4. Click **+ Add Variable**
5. Enter: Variable Name (e.g. `REVENUE`), Display Label, Data Type, Source Type
6. For non-manual sources: fill in the Adapter Config form
7. For REST API: enter URL, authentication (use `{SECRET:KEY_NAME}` for credentials), and response JSON path
8. Click **Test Connection** to verify the adapter works before saving
9. Save the variable — it now appears in the formula validation check

### 10.4 Security: Never Store Raw Credentials

All external credentials must use `{SECRET:KEY_NAME}` placeholders:

✅ CORRECT:   `"Authorization": "Bearer {SECRET:ERP_API_TOKEN}"`
❌ INCORRECT: `"Authorization": "Bearer eyJhbGci..."`

The placeholder is resolved at runtime from environment variables named `PMS_SECRET_ERP_API_TOKEN`.
Raw credentials are never stored in the database.

### 10.5 What the Employee Sees on Actuals Entry

For a formula KPI, the Actuals Entry screen shows:
- Auto-synced variables: value + last sync time + Refresh button
- Manual variables: input field with label and unit
- Live formula preview: computed result updates as user types
- Achievement % and rating preview against their target
- Submit button stores all variable values + computed result

### 10.6 Audit Trail

Every value that goes into a formula computation is stored in `variable_actuals`:
- Which variable, which period, what value
- Source (manual vs auto-sync)
- Full sync metadata (URL called, HTTP status, response time, timestamp)

This means you can always answer: "What exact numbers produced this KPI result?"
```

### Section 17 — Changelog

```markdown
## 17. Changelog

### v2.0 — [today's date]
**Enhancement 1: Per-KPI Scoring Configuration**
- Added `kpi_scoring_configs` table with 5 system presets + custom configs
- Added `scoring_config_id` FK on `kpis` (KPI-level default)
- Added `scoring_config_id` FK on `kpi_targets` (target-level override, highest precedence)
- Added `scoring_config_snapshot` JSON on `performance_scores` (audit trail)
- New frontend: `ScoringConfigManager` with List, Builder, and Preview tabs
- Updated KPI Builder Step 4 with scoring config selector
- Updated Target Assignment with per-target scoring override
- Updated Scorecard Table with config source tooltip on rating badges

**Enhancement 2: Formula Variables & External Data Binding**
- Added `kpi_variables` table (named formula variable definitions)
- Added `variable_actuals` table (per-period raw values, full audit)
- Added adapter system: REST API, Database, InfluxDB, Webhook, KPI Reference
- New frontend: `KPIVariableManager` with dnd-kit reordering
- New frontend: `AdapterConfigForm` with dynamic field rendering
- Updated Actuals Entry: formula KPIs show variable inputs + live preview
- Updated KPI Builder Step 3: integrated variable manager
- New utility: `formulaEvaluator.ts` (client-side, mirrors backend)

### v1.0 — Initial release
- KPI library, review cycles, target setting, actuals entry
- Scoring engine, calibration, dashboards
- Notifications and background tasks
```

---

## 3.2 Mark Old Files as Deprecated

At the very **top** of each of these existing files, add a deprecation banner. Do NOT delete the files — they may be in git history and referenced in commit messages:

```markdown
> ⛔ DEPRECATED — This file is superseded by `MASTER_USER_GUIDE.md` at the repo root.
> Do not update this file. It is kept for historical reference only.
> Last active version: see git history.
```

Files to add the banner to:
- `PART1-project-setup.md`
- `PART2-kpi-core.md`
- `PART3-targets-actuals.md`
- `PART4-scoring-dashboards.md`
- `PART5-notifications-tasks.md`
- `FRONTEND-pms-kpi-ui.md`
- `ENHANCE1-per-kpi-scoring.md`
- `ENHANCE2-formula-variables.md`
- `ENHANCE3-documentation-update.md`

---

## 3.3 Update `ARCHITECTURE.md`

The `ARCHITECTURE.md` file (created by Enhancement 3) needs one new section added at the end:

```markdown
## Documentation Policy

There is ONE living document: `MASTER_USER_GUIDE.md` at the repo root.

Rules:
1. When any feature is added or changed, update MASTER_USER_GUIDE.md ONLY.
2. Never create a new .md file for feature documentation — add a section to the master guide.
3. New Copilot prompts go in MASTER_USER_GUIDE.md Section 16 (VS Code Copilot Context Prompt).
4. The Changelog in Section 17 must be updated with every meaningful change.
5. All other .md files in the repo root are archived (deprecated banner at top).

Why single document?
- Prevents outdated info spread across multiple files
- Copilot @workspace can reference one file instead of hunting across 9+
- New team members have one place to start
- Version control diffs are easier to review
```

---

# PART 4 — FINAL CHECKLIST

After completing all parts, verify:

**Frontend — Enhancement 1 (Scoring Config):**
- [ ] `src/types/scoring-config.types.ts` exists with all types and utility functions
- [ ] `src/mocks/scoring_configs.json` exists with 6 entries (5 system + 1 custom)
- [ ] `scoringConfigEndpoints.ts` implements all 10 endpoints
- [ ] `ScoringConfigManager.tsx` has 3 working tabs: List, Builder, Preview
- [ ] Builder form validates threshold order client-side (zod schema)
- [ ] Preview tab slider works and shows comparison against Standard
- [ ] KPI Builder Step 4 shows scoring config dropdown with summary badge
- [ ] Target assignment shows scoring override section (collapsible)
- [ ] Scorecard table rating column has tooltip with config source + thresholds
- [ ] System presets show lock icon — no edit/delete actions rendered

**Frontend — Enhancement 2 (Formula Variables):**
- [ ] `src/types/integration.types.ts` exists with all types
- [ ] `src/mocks/kpi_variables.json` exists with 2 variables for kpi-001
- [ ] `variableEndpoints.ts` implements all RTK Query endpoints
- [ ] `src/lib/formulaEvaluator.ts` exists with `evaluateFormula()` and `validateFormulaClient()`
- [ ] `evaluateFormula()` handles: normal case, missing variables, division by zero, IF() function
- [ ] `KPIVariableManager.tsx` shows all variables with source badges and sync status
- [ ] Variable drag-to-reorder works via dnd-kit
- [ ] "Add Variable" dialog opens with `AdapterConfigForm` for non-manual sources
- [ ] Test Connection button simulates adapter call and shows result
- [ ] `AdapterConfigForm.tsx` renders dynamic fields from adapter schema
- [ ] `secret_ref` fields show warning if user types a raw-looking credential
- [ ] Actuals Entry: formula KPIs show variable inputs (auto-synced + manual)
- [ ] Live formula preview updates as user types manual variable values
- [ ] Achievement % and rating preview shown below computed result
- [ ] KPI Builder Step 3: variable manager renders inline for formula KPIs
- [ ] KPI Detail Drawer Formula tab shows variable manager + history table

**Documentation:**
- [ ] `MASTER_USER_GUIDE.md` exists at repo root (not inside a subdirectory)
- [ ] All 17 sections present with complete content (not stubs)
- [ ] Section 9 covers scoring system with all 5 presets and 3-level precedence
- [ ] Section 10 covers formula variables with setup steps and security rules
- [ ] Section 17 has v1.0 and v2.0 changelog entries
- [ ] Deprecation banner added to all 9 old .md files
- [ ] `ARCHITECTURE.md` has documentation policy section added
- [ ] `npm run build` produces zero TypeScript errors