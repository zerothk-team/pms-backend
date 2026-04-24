# Frontend Prompt — PMS KPI Module (React + TypeScript)
> **For**: Lovable AI / GitHub Copilot (Claude Sonnet 4.6)
> **Stack**: React 18 · TypeScript · Vite · Tailwind CSS · shadcn/ui · Redux Toolkit · RTK Query · Recharts · Framer Motion · dnd-kit · Lucide React

---

## 0. READ THIS FIRST — Guiding Principles

You are building a **production-grade Performance Management System (PMS) frontend** with a KPI module as the core. The FastAPI backend is already designed (referenced throughout this prompt). Do not connect to a real backend — use RTK Query with `fakeBaseQuery` and mock JSON files.

**Architectural rules (non-negotiable):**
1. Every TypeScript type mirrors the backend Pydantic schema exactly — same field names, same enum values.
2. Every RTK Query endpoint mirrors a backend router path exactly — same HTTP method, same URL pattern.
3. No component directly imports mock data — all data flows through RTK Query hooks.
4. Role-based rendering: a `useRole()` hook gates every UI section. Three roles: `hr_admin`, `manager`, `employee`.
5. All loading and error states must be handled visibly — no silent failures.

---

## 1. Project Scaffold

### 1.1 Create the project

```bash
npm create vite@latest pms-frontend -- --template react-ts
cd pms-frontend
```

### 1.2 Install all dependencies

```bash
# UI
npm install tailwindcss @tailwindcss/vite postcss autoprefixer
npm install @shadcn/ui class-variance-authority clsx tailwind-merge
npx shadcn@latest init

# State + Data
npm install @reduxjs/toolkit react-redux

# Routing
npm install react-router-dom

# Charts
npm install recharts

# Animation
npm install framer-motion

# Drag and Drop
npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities

# Theming
npm install next-themes

# Icons
npm install lucide-react

# Dates
npm install date-fns

# Form
npm install react-hook-form @hookform/resolvers zod

# UUID
npm install uuid
npm install -D @types/uuid
```

### 1.3 Install shadcn/ui components

```bash
npx shadcn@latest add button card badge dialog drawer dropdown-menu
npx shadcn@latest add form input label select separator sheet skeleton
npx shadcn@latest add table tabs tooltip popover command
npx shadcn@latest add progress scroll-area avatar switch slider
npx shadcn@latest add alert alert-dialog toast sonner
npx shadcn@latest add collapsible navigation-menu breadcrumb
```

---

## 2. Directory Structure

Generate **exactly** this structure:

```
src/
├── app/
│   ├── store.ts                  ← Redux store
│   └── hooks.ts                  ← typed useAppDispatch, useAppSelector
│
├── features/
│   ├── theme/
│   │   ├── themeSlice.ts
│   │   └── ThemeConfigPanel.tsx
│   │
│   ├── auth/
│   │   ├── authSlice.ts          ← current user + role
│   │   ├── useRole.ts            ← hook: useRole(), useIsAdmin(), etc.
│   │   ├── RoleGuard.tsx         ← wrapper component
│   │   ├── LoginPage.tsx
│   │   └── RoleSwitcher.tsx      ← DEV ONLY: switch role without auth
│   │
│   ├── kpis/
│   │   ├── kpiSlice.ts
│   │   ├── components/
│   │   │   ├── KPILibraryPage.tsx
│   │   │   ├── KPIBuilderForm.tsx
│   │   │   ├── KPIDetailDrawer.tsx
│   │   │   ├── KPITemplateGallery.tsx
│   │   │   ├── KPIFormulaEditor.tsx
│   │   │   ├── KPIStatusBadge.tsx
│   │   │   └── KPICategoryFilter.tsx
│   │
│   ├── review-cycles/
│   │   ├── cycleSice.ts
│   │   └── components/
│   │       ├── CycleListPage.tsx
│   │       ├── CycleCreateForm.tsx
│   │       └── CycleStatusStepper.tsx
│   │
│   ├── targets/
│   │   ├── targetSlice.ts
│   │   └── components/
│   │       ├── TargetSetPage.tsx
│   │       ├── TargetCascadeTree.tsx      ← dnd-kit drag & drop
│   │       ├── BulkTargetAssignForm.tsx
│   │       ├── WeightDistributionBar.tsx
│   │       └── TargetAcknowledgeCard.tsx
│   │
│   ├── actuals/
│   │   ├── actualSlice.ts
│   │   └── components/
│   │       ├── ActualEntryPage.tsx
│   │       ├── ActualEntryForm.tsx
│   │       ├── ActualTimeline.tsx
│   │       ├── EvidenceUploader.tsx
│   │       ├── PendingApprovalsPage.tsx
│   │       └── ActualReviewModal.tsx
│   │
│   ├── scoring/
│   │   ├── scoringSlice.ts
│   │   └── components/
│   │       ├── ScorecardPage.tsx
│   │       ├── KPIScorecardTable.tsx      ← dnd-kit sortable
│   │       ├── CompositeScoreCard.tsx
│   │       ├── ScoreAdjustmentForm.tsx
│   │       ├── CalibrationSessionPage.tsx
│   │       └── RatingBadge.tsx
│   │
│   ├── dashboards/
│   │   └── components/
│   │       ├── EmployeeDashboard.tsx
│   │       ├── ManagerDashboard.tsx
│   │       ├── OrgDashboard.tsx
│   │       ├── KPISummaryCard.tsx
│   │       ├── AchievementGauge.tsx
│   │       ├── TeamProgressTable.tsx
│   │       ├── PerformanceHeatmap.tsx
│   │       ├── AtRiskAlert.tsx
│   │       └── TrendSparkline.tsx
│   │
│   └── notifications/
│       ├── notificationSlice.ts
│       └── components/
│           ├── NotificationBell.tsx
│           ├── NotificationPanel.tsx
│           └── NotificationItem.tsx
│
├── services/
│   ├── api.ts                    ← RTK Query apiService (fakeBaseQuery)
│   ├── endpoints/
│   │   ├── kpiEndpoints.ts
│   │   ├── cycleEndpoints.ts
│   │   ├── targetEndpoints.ts
│   │   ├── actualEndpoints.ts
│   │   ├── scoringEndpoints.ts
│   │   ├── dashboardEndpoints.ts
│   │   └── notificationEndpoints.ts
│   └── transformers.ts           ← response normalisation helpers
│
├── mocks/
│   ├── employees.json
│   ├── organisations.json
│   ├── kpi_templates.json
│   ├── kpis.json
│   ├── review_cycles.json
│   ├── targets.json
│   ├── actuals.json
│   ├── performance_scores.json
│   ├── composite_scores.json
│   └── notifications.json
│
├── types/
│   ├── index.ts                  ← re-exports all types
│   ├── enums.ts                  ← all enums from backend
│   ├── kpi.types.ts
│   ├── cycle.types.ts
│   ├── target.types.ts
│   ├── actual.types.ts
│   ├── scoring.types.ts
│   ├── user.types.ts
│   └── notification.types.ts
│
├── components/
│   ├── layout/
│   │   ├── AppShell.tsx          ← root layout
│   │   ├── Sidebar.tsx           ← collapsible with nested nav
│   │   ├── TopBar.tsx
│   │   ├── Breadcrumbs.tsx
│   │   └── PageTransition.tsx    ← Framer Motion wrapper
│   ├── ui-custom/
│   │   ├── DataTable.tsx         ← sortable, paginated table
│   │   ├── EmptyState.tsx
│   │   ├── LoadingSkeleton.tsx
│   │   ├── ErrorBoundary.tsx
│   │   ├── ProgressRing.tsx      ← SVG animated ring
│   │   ├── StatCard.tsx
│   │   └── ConfirmDialog.tsx
│   └── index.ts
│
├── hooks/
│   ├── useDebounce.ts
│   ├── usePagination.ts
│   └── useLocalStorage.ts
│
├── lib/
│   ├── utils.ts                  ← shadcn cn() utility
│   ├── formatters.ts             ← currency, %, date formatters
│   └── constants.ts
│
├── router/
│   └── index.tsx                 ← react-router-dom routes
│
├── main.tsx
└── App.tsx
```

---

## 3. TypeScript Types — `src/types/`

### 3.1 `src/types/enums.ts`

Mirror **exactly** the backend Python enums. Use `const` enums for tree-shaking:

```typescript
export const MeasurementUnit = {
  PERCENTAGE: 'percentage',
  CURRENCY: 'currency',
  COUNT: 'count',
  SCORE: 'score',
  RATIO: 'ratio',
  DURATION_HOURS: 'duration_hours',
  CUSTOM: 'custom',
} as const;
export type MeasurementUnit = typeof MeasurementUnit[keyof typeof MeasurementUnit];

export const MeasurementFrequency = {
  DAILY: 'daily',
  WEEKLY: 'weekly',
  MONTHLY: 'monthly',
  QUARTERLY: 'quarterly',
  YEARLY: 'yearly',
  ON_DEMAND: 'on_demand',
} as const;
export type MeasurementFrequency = typeof MeasurementFrequency[keyof typeof MeasurementFrequency];

export const DataSourceType = {
  MANUAL: 'manual',
  FORMULA: 'formula',
  INTEGRATION: 'integration',
} as const;
export type DataSourceType = typeof DataSourceType[keyof typeof DataSourceType];

export const ScoringDirection = {
  HIGHER_IS_BETTER: 'higher_is_better',
  LOWER_IS_BETTER: 'lower_is_better',
} as const;
export type ScoringDirection = typeof ScoringDirection[keyof typeof ScoringDirection];

export const KPIStatus = {
  DRAFT: 'draft',
  PENDING_APPROVAL: 'pending_approval',
  ACTIVE: 'active',
  DEPRECATED: 'deprecated',
  ARCHIVED: 'archived',
} as const;
export type KPIStatus = typeof KPIStatus[keyof typeof KPIStatus];

export const DepartmentCategory = {
  SALES: 'sales',
  MARKETING: 'marketing',
  FINANCE: 'finance',
  HR: 'hr',
  OPERATIONS: 'operations',
  ENGINEERING: 'engineering',
  CUSTOMER_SUCCESS: 'customer_success',
  PRODUCT: 'product',
  LEGAL: 'legal',
  GENERAL: 'general',
} as const;
export type DepartmentCategory = typeof DepartmentCategory[keyof typeof DepartmentCategory];

export const TargetLevel = {
  ORGANISATION: 'organisation',
  DEPARTMENT: 'department',
  TEAM: 'team',
  INDIVIDUAL: 'individual',
} as const;
export type TargetLevel = typeof TargetLevel[keyof typeof TargetLevel];

export const TargetStatus = {
  DRAFT: 'draft',
  PENDING_ACKNOWLEDGEMENT: 'pending_acknowledgement',
  ACKNOWLEDGED: 'acknowledged',
  APPROVED: 'approved',
  LOCKED: 'locked',
} as const;
export type TargetStatus = typeof TargetStatus[keyof typeof TargetStatus];

export const CycleStatus = {
  DRAFT: 'draft',
  ACTIVE: 'active',
  CLOSED: 'closed',
  ARCHIVED: 'archived',
} as const;
export type CycleStatus = typeof CycleStatus[keyof typeof CycleStatus];

export const ScoreStatus = {
  COMPUTED: 'computed',
  MANAGER_REVIEWED: 'manager_reviewed',
  ADJUSTED: 'adjusted',
  CALIBRATED: 'calibrated',
  FINAL: 'final',
} as const;
export type ScoreStatus = typeof ScoreStatus[keyof typeof ScoreStatus];

export const RatingLabel = {
  EXCEPTIONAL: 'exceptional',
  EXCEEDS_EXPECTATIONS: 'exceeds_expectations',
  MEETS_EXPECTATIONS: 'meets_expectations',
  PARTIALLY_MEETS: 'partially_meets',
  DOES_NOT_MEET: 'does_not_meet',
  NOT_RATED: 'not_rated',
} as const;
export type RatingLabel = typeof RatingLabel[keyof typeof RatingLabel];

export const UserRole = {
  HR_ADMIN: 'hr_admin',
  EXECUTIVE: 'executive',
  MANAGER: 'manager',
  EMPLOYEE: 'employee',
} as const;
export type UserRole = typeof UserRole[keyof typeof UserRole];
```

---

### 3.2 `src/types/kpi.types.ts`

```typescript
import { MeasurementUnit, MeasurementFrequency, DataSourceType, ScoringDirection, KPIStatus, DepartmentCategory } from './enums';

export interface KPICategory {
  id: string;
  name: string;
  description: string | null;
  department: DepartmentCategory;
  colour_hex: string;
  organisation_id: string | null;
  created_at: string;
}

export interface KPITag {
  id: string;
  name: string;
}

export interface KPI {
  id: string;
  name: string;
  code: string;
  description: string | null;
  unit: MeasurementUnit;
  unit_label: string | null;
  currency_code: string | null;
  frequency: MeasurementFrequency;
  data_source: DataSourceType;
  formula_expression: string | null;
  scoring_direction: ScoringDirection;
  min_value: number | null;
  max_value: number | null;
  decimal_places: number;
  status: KPIStatus;
  is_template: boolean;
  is_organisation_wide: boolean;
  version: number;
  category: KPICategory | null;
  tags: KPITag[];
  organisation_id: string;
  created_by_id: string;
  approved_by_id: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface KPITemplate {
  id: string;
  name: string;
  description: string | null;
  department: DepartmentCategory;
  unit: MeasurementUnit;
  frequency: MeasurementFrequency;
  scoring_direction: ScoringDirection;
  suggested_formula: string | null;
  tags: string[];
  usage_count: number;
}

export interface KPICreate {
  name: string;
  code: string;
  description?: string;
  unit: MeasurementUnit;
  frequency: MeasurementFrequency;
  data_source: DataSourceType;
  formula_expression?: string;
  scoring_direction: ScoringDirection;
  category_id?: string;
  tag_ids?: string[];
  decimal_places?: number;
  is_organisation_wide?: boolean;
}

export interface PaginatedKPIs {
  items: KPI[];
  total: number;
  page: number;
  size: number;
  pages: number;
}
```

---

### 3.3 `src/types/target.types.ts`

```typescript
import { TargetLevel, TargetStatus } from './enums';
import { KPI } from './kpi.types';

export interface TargetMilestone {
  id: string;
  target_id: string;
  milestone_date: string;
  expected_value: number;
  label: string | null;
}

export interface KPITarget {
  id: string;
  kpi_id: string;
  kpi: KPI;
  review_cycle_id: string;
  assignee_type: TargetLevel;
  assignee_user_id: string | null;
  target_value: number;
  stretch_target_value: number | null;
  minimum_value: number | null;
  weight: number;
  status: TargetStatus;
  cascade_parent_id: string | null;
  notes: string | null;
  milestones: TargetMilestone[];
  set_by_id: string;
  acknowledged_at: string | null;
  locked_at: string | null;
  created_at: string;
  // Computed (populated by dashboard endpoint)
  current_actual_value?: number | null;
  achievement_percentage?: number | null;
  is_at_risk?: boolean;
}
```

---

### 3.4 `src/types/scoring.types.ts`

```typescript
import { ScoreStatus, RatingLabel } from './enums';

export interface PerformanceScore {
  id: string;
  target_id: string;
  user_id: string;
  kpi_id: string;
  review_cycle_id: string;
  achievement_percentage: number;
  weighted_score: number;
  rating: RatingLabel;
  computed_score: number;
  adjusted_score: number | null;
  final_score: number;
  status: ScoreStatus;
  computed_at: string;
}

export interface CompositeScore {
  id: string;
  user_id: string;
  review_cycle_id: string;
  organisation_id: string;
  weighted_average: number;
  rating: RatingLabel;
  kpi_count: number;
  kpis_with_actuals: number;
  status: ScoreStatus;
  manager_comment: string | null;
  calibration_note: string | null;
  final_weighted_average: number;
  computed_at: string;
}
```

---

## 4. Mock Data — `src/mocks/`

### 4.1 `kpis.json` — generate 12 realistic KPI objects covering 4 departments:

```json
[
  {
    "id": "kpi-001",
    "name": "Monthly Revenue Growth",
    "code": "SALES_REVENUE_GROWTH",
    "description": "Month-over-month revenue growth as a percentage",
    "unit": "percentage",
    "frequency": "monthly",
    "data_source": "manual",
    "formula_expression": null,
    "scoring_direction": "higher_is_better",
    "status": "active",
    "is_template": false,
    "is_organisation_wide": false,
    "version": 1,
    "decimal_places": 2,
    "category": { "id": "cat-001", "name": "Sales Performance", "department": "sales", "colour_hex": "#0F6E56" },
    "tags": [{ "id": "tag-001", "name": "revenue" }],
    "organisation_id": "org-001",
    "created_by_id": "user-001",
    "approved_by_id": "user-001",
    "approved_at": "2025-01-01T00:00:00Z",
    "created_at": "2025-01-01T00:00:00Z",
    "updated_at": "2025-01-01T00:00:00Z",
    "min_value": null, "max_value": null,
    "unit_label": null, "currency_code": null
  }
  // ... 11 more covering HR, Finance, Engineering departments
]
```

### 4.2 `targets.json` — generate 8 targets (mix of individual + team level):

Include targets with:
- `achievement_percentage` ranging from 45% to 135% (to show at-risk and exceeded states)
- `is_at_risk: true` on 2 records
- At least 2 targets with `cascade_parent_id` set (child of another target)
- At least 2 targets with `milestones` arrays

### 4.3 `actuals.json` — generate monthly time-series data:

For each target, generate 6 monthly actual entries (Jan–Jun 2025) with realistic values that show a trend (improving or declining).

### 4.4 `performance_scores.json` + `composite_scores.json`:

Generate scores for 8 employees in Q2 2025 cycle. Mix of ratings: 2 exceptional, 3 meets_expectations, 2 partially_meets, 1 does_not_meet.

### 4.5 `employees.json` — 8 employees:

```json
[
  {
    "id": "user-001",
    "email": "sarah.chen@company.com",
    "full_name": "Sarah Chen",
    "role": "hr_admin",
    "is_active": true,
    "organisation_id": "org-001",
    "manager_id": null,
    "department": "hr",
    "avatar_url": null,
    "last_login_at": "2025-06-15T09:00:00Z",
    "created_at": "2024-01-01T00:00:00Z"
  }
  // 7 more: 1 executive, 2 managers, 4 employees
]
```

---

## 5. RTK Query API Service — `src/services/`

### 5.1 `src/services/api.ts` — Base service with simulated latency

```typescript
import { createApi, fakeBaseQuery } from '@reduxjs/toolkit/query/react';

export const apiService = createApi({
  reducerPath: 'api',
  baseQuery: fakeBaseQuery(),
  tagTypes: [
    'KPI', 'KPITemplate', 'KPICategory',
    'ReviewCycle', 'Target', 'Actual',
    'PerformanceScore', 'CompositeScore',
    'Dashboard', 'Notification', 'User',
  ],
  endpoints: () => ({}),
});

// Simulated async fetch from mock JSON with 300-600ms latency
export async function mockFetch<T>(dataFn: () => T, latencyMs = 400): Promise<T> {
  await new Promise(resolve => setTimeout(resolve, latencyMs + Math.random() * 200));
  return dataFn();
}

// Simulated mutation with optimistic latency
export async function mockMutate<T>(dataFn: () => T, latencyMs = 600): Promise<T> {
  await new Promise(resolve => setTimeout(resolve, latencyMs));
  return dataFn();
}
```

### 5.2 `src/services/endpoints/kpiEndpoints.ts`

Inject into `apiService`. Mirror backend routes exactly:

```typescript
import { apiService, mockFetch, mockMutate } from '../api';
import kpisData from '../../mocks/kpis.json';
import templatesData from '../../mocks/kpi_templates.json';
import type { KPI, KPICreate, PaginatedKPIs, KPITemplate } from '../../types/kpi.types';

export const kpiApi = apiService.injectEndpoints({
  endpoints: (build) => ({
    // GET /api/v1/kpis/ → list KPIs paginated + filtered
    listKPIs: build.query<PaginatedKPIs, {
      page?: number; size?: number;
      status?: string; category_id?: string;
      department?: string; search?: string;
    }>({
      queryFn: async (params) => {
        const data = await mockFetch(() => {
          let items = [...kpisData] as KPI[];
          if (params.status) items = items.filter(k => k.status === params.status);
          if (params.search) items = items.filter(k =>
            k.name.toLowerCase().includes(params.search!.toLowerCase()) ||
            k.code.toLowerCase().includes(params.search!.toLowerCase())
          );
          const page = params.page || 1;
          const size = params.size || 20;
          const start = (page - 1) * size;
          return {
            items: items.slice(start, start + size),
            total: items.length,
            page,
            size,
            pages: Math.ceil(items.length / size),
          };
        });
        return { data };
      },
      providesTags: ['KPI'],
    }),

    // GET /api/v1/kpis/{kpi_id} → single KPI
    getKPI: build.query<KPI, string>({
      queryFn: async (id) => {
        const data = await mockFetch(() =>
          (kpisData as KPI[]).find(k => k.id === id) ?? null
        );
        if (!data) return { error: { status: 404, error: 'KPI not found' } };
        return { data };
      },
      providesTags: (_result, _err, id) => [{ type: 'KPI', id }],
    }),

    // POST /api/v1/kpis/ → create KPI
    createKPI: build.mutation<KPI, KPICreate>({
      queryFn: async (body) => {
        const data = await mockMutate(() => ({
          ...body,
          id: crypto.randomUUID(),
          status: 'draft',
          version: 1,
          is_template: false,
          tags: [],
          category: null,
          organisation_id: 'org-001',
          created_by_id: 'user-001',
          approved_by_id: null,
          approved_at: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        } as KPI));
        return { data };
      },
      invalidatesTags: ['KPI'],
    }),

    // PATCH /api/v1/kpis/{kpi_id}/status → update status
    updateKPIStatus: build.mutation<KPI, { id: string; status: string; reason?: string }>({
      queryFn: async ({ id, status }) => {
        const data = await mockMutate(() => {
          const kpi = (kpisData as KPI[]).find(k => k.id === id);
          if (!kpi) throw new Error('Not found');
          return { ...kpi, status: status as KPI['status'], updated_at: new Date().toISOString() };
        });
        return { data };
      },
      invalidatesTags: (_result, _err, { id }) => [{ type: 'KPI', id }, 'KPI'],
    }),

    // POST /api/v1/kpis/validate-formula → validate formula
    validateFormula: build.mutation<{ valid: boolean; referenced_codes: string[]; errors: string[] }, { expression: string }>({
      queryFn: async ({ expression }) => {
        const data = await mockMutate(() => {
          // Simple client-side validation mock
          const refs = expression.match(/[A-Z][A-Z0-9_]+/g) || [];
          const hasInvalidChars = /[^A-Z0-9_+\-*/(). ,]/.test(expression);
          return {
            valid: !hasInvalidChars && expression.length > 0,
            referenced_codes: refs,
            errors: hasInvalidChars ? ['Invalid characters in expression'] : [],
          };
        }, 300);
        return { data };
      },
    }),

    // GET /api/v1/kpis/templates/ → list templates
    listKPITemplates: build.query<KPITemplate[], { department?: string; search?: string }>({
      queryFn: async (params) => {
        const data = await mockFetch(() => {
          let items = [...templatesData] as KPITemplate[];
          if (params.department) items = items.filter(t => t.department === params.department);
          if (params.search) items = items.filter(t =>
            t.name.toLowerCase().includes(params.search!.toLowerCase())
          );
          return items;
        });
        return { data };
      },
      providesTags: ['KPITemplate'],
    }),
  }),
});

export const {
  useListKPIsQuery,
  useGetKPIQuery,
  useCreateKPIMutation,
  useUpdateKPIStatusMutation,
  useValidateFormulaMutation,
  useListKPITemplatesQuery,
} = kpiApi;
```

Generate equivalent endpoint files for:
- `targetEndpoints.ts` — `listTargets`, `getTarget`, `createTarget`, `bulkCreateTargets`, `cascadeTarget`, `acknowledgeTarget`, `getTargetWithProgress`
- `actualEndpoints.ts` — `listActuals`, `submitActual`, `bulkSubmitActuals`, `reviewActual`, `getTimeSeries`, `getPendingApprovals`
- `scoringEndpoints.ts` — `getUserScore`, `getTeamScores`, `getOrgDistribution`, `adjustScore`, `finaliseScores`
- `cycleEndpoints.ts` — `listCycles`, `createCycle`, `getActiveCycle`, `updateCycleStatus`
- `dashboardEndpoints.ts` — `getEmployeeDashboard`, `getManagerDashboard`, `getOrgDashboard`
- `notificationEndpoints.ts` — `listNotifications`, `getUnreadCount`, `markRead`, `markAllRead`

---

## 6. State Management — Redux Slices

### 6.1 `src/features/auth/authSlice.ts`

```typescript
import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import type { UserRole } from '../../types/enums';

interface User {
  id: string;
  full_name: string;
  email: string;
  role: UserRole;
  organisation_id: string;
  manager_id: string | null;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
}

const initialState: AuthState = {
  // Default to hr_admin for development
  user: {
    id: 'user-001',
    full_name: 'Sarah Chen',
    email: 'sarah.chen@company.com',
    role: 'hr_admin',
    organisation_id: 'org-001',
    manager_id: null,
  },
  isAuthenticated: true,
};

export const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    setUser: (state, action: PayloadAction<User>) => {
      state.user = action.payload;
      state.isAuthenticated = true;
    },
    switchRole: (state, action: PayloadAction<UserRole>) => {
      // DEV ONLY — swaps to a different mock user by role
      if (state.user) state.user.role = action.payload;
    },
    logout: (state) => {
      state.user = null;
      state.isAuthenticated = false;
    },
  },
});
```

### 6.2 `src/features/auth/useRole.ts`

```typescript
export function useRole() {
  const user = useAppSelector(s => s.auth.user);
  return {
    role: user?.role,
    isAdmin: user?.role === 'hr_admin',
    isManager: user?.role === 'manager' || user?.role === 'hr_admin',
    isEmployee: true, // all roles have employee-level access
    isExecutive: user?.role === 'executive' || user?.role === 'hr_admin',
    can: (action: string) => checkPermission(user?.role, action),
  };
}
```

### 6.3 `src/features/theme/themeSlice.ts`

```typescript
interface ThemeState {
  colorScheme: 'light' | 'dark' | 'system';
  primaryColor: string;        // HSL CSS variable value
  accentColor: string;
  borderRadius: 'none' | 'sm' | 'md' | 'lg' | 'full';
  fontFamily: 'sans' | 'serif' | 'mono';
  density: 'default' | 'compact';
  sidebarCollapsed: boolean;
  layoutMode: 'sidebar' | 'topnav';
}
```

Apply theme changes by updating CSS variables on `:root` in a `useThemeEffect` hook.

---

## 7. Layout Components — `src/components/layout/`

### 7.1 `AppShell.tsx`

```typescript
// Root layout wrapper
// - Reads themeSlice for sidebar collapsed state, layout mode
// - Renders: Sidebar | main content area
// - Wraps page content in PageTransition (Framer Motion)
// - ThemeConfigPanel floating button (bottom-right)
// - RoleSwitcher banner (top, DEV mode only)
```

### 7.2 `Sidebar.tsx` — Collapsible multi-level navigation

Navigation items (with Lucide icons) and role visibility:

```typescript
const navItems = [
  {
    label: 'Dashboard',
    icon: LayoutDashboard,
    path: '/',
    roles: ['hr_admin', 'executive', 'manager', 'employee'],
  },
  {
    label: 'KPI Library',
    icon: Target,
    roles: ['hr_admin', 'manager'],
    children: [
      { label: 'All KPIs', path: '/kpis', icon: List },
      { label: 'Templates', path: '/kpis/templates', icon: BookOpen },
      { label: 'Categories', path: '/kpis/categories', icon: Tag },
    ],
  },
  {
    label: 'Review Cycles',
    icon: Calendar,
    path: '/cycles',
    roles: ['hr_admin'],
  },
  {
    label: 'Targets',
    icon: Crosshair,
    roles: ['hr_admin', 'manager'],
    children: [
      { label: 'Set Targets', path: '/targets', icon: PlusCircle },
      { label: 'Cascade', path: '/targets/cascade', icon: GitBranch },
    ],
  },
  {
    label: 'My Targets',
    icon: ClipboardList,
    path: '/my-targets',
    roles: ['employee', 'manager'],
  },
  {
    label: 'Actuals Entry',
    icon: PenLine,
    path: '/actuals',
    roles: ['employee', 'manager'],
  },
  {
    label: 'Approvals',
    icon: CheckSquare,
    path: '/approvals',
    roles: ['manager', 'hr_admin'],
  },
  {
    label: 'Scorecards',
    icon: BarChart2,
    roles: ['hr_admin', 'manager', 'executive'],
    children: [
      { label: 'Team Scores', path: '/scoring/team', icon: Users },
      { label: 'Calibration', path: '/scoring/calibration', icon: SlidersHorizontal },
      { label: 'Org Overview', path: '/scoring/org', icon: Building2 },
    ],
  },
  {
    label: 'Reports',
    icon: FileBarChart,
    path: '/reports',
    roles: ['hr_admin', 'executive'],
  },
  {
    label: 'Settings',
    icon: Settings,
    path: '/settings',
    roles: ['hr_admin'],
  },
];
```

Sidebar collapse animation using Framer Motion `width` transition:
- Expanded: 240px — shows icon + label
- Collapsed: 64px — shows icon only, tooltip on hover
- Toggle button at bottom of sidebar
- `CollapsibleSection` for nested items with chevron icon

### 7.3 `TopBar.tsx`

- Left: Breadcrumbs (auto-generated from route)
- Right: NotificationBell, avatar dropdown (profile, role switcher in dev, logout)
- Active cycle pill: shows current cycle name + status badge

### 7.4 `PageTransition.tsx`

```typescript
// Framer Motion AnimatePresence wrapper
// variants: { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0 } }
// transition: { duration: 0.2, ease: 'easeOut' }
```

---

## 8. Theme Configuration Panel — `src/features/theme/ThemeConfigPanel.tsx`

A `Sheet` (shadcn) sliding from the right, triggered by a floating `Settings2` icon button.

**Sections inside the panel:**

1. **Color Mode** — `ToggleGroup` for Light / Dark / System
2. **Primary Color** — 6 preset swatches (Slate, Blue, Emerald, Violet, Rose, Amber) + custom hex input. On change: update `--primary` CSS variable.
3. **Border Radius** — `Slider` from 0 to 12 mapped to Tailwind values. Updates `--radius` CSS variable.
4. **Font Family** — 3 radio cards: Sans (DM Sans), Serif (Playfair Display), Mono (JetBrains Mono)
5. **Layout** — Toggle: Sidebar / Top Navigation
6. **Density** — Toggle: Default / Compact (adjusts global padding via CSS variable)
7. **Reset** button — back to defaults

---

## 9. Feature Pages — Detailed Specifications

### 9.1 Dashboard — `src/features/dashboards/components/`

**Role-aware routing:**
```typescript
// Dashboard index auto-routes by role:
// hr_admin / executive → OrgDashboard
// manager → ManagerDashboard
// employee → EmployeeDashboard
```

#### `EmployeeDashboard.tsx`

Layout: 2-column grid (2/3 left + 1/3 right on desktop, stacked mobile)

**Left column:**
- Welcome header: avatar, name, active cycle name + days remaining pill
- Row of 4 `StatCard` components: Total KPIs, Actuals Due, Overall Achievement %, Overall Rating badge
- `KPISummaryTable`: Each row = one KPI with columns: Name, Target, Latest Actual, Achievement % (progress bar), Trend (sparkline), Status (at-risk badge or on-track badge)

**Right column:**
- `ProgressRing` — animated SVG ring showing overall achievement %
- `AtRiskAlert` list — expandable cards for at-risk KPIs with "Enter Actual" CTA
- `UpcomingDeadlines` — next 3 required actuals with period label

#### `ManagerDashboard.tsx`

Layout: full-width with card rows

**Row 1 — Stats:**
- Team size, At-risk count, Pending approvals count, Team avg achievement %

**Row 2 — Team Progress Table:**
- Columns: Employee, KPIs, Submitted, Achievement %, Rating, At-risk, Actions
- Clicking a row opens `KPIScorecardTable` in a drawer

**Row 3 — Charts (2 columns):**
- `PerformanceHeatmap` — grid of employees × KPIs, colour-coded by achievement %
- `TeamDistributionChart` — bar chart of rating distribution

#### `OrgDashboard.tsx`

- Cycle selector at top
- Row of 6 KPI stat cards
- `DepartmentBreakdownChart` — grouped bar chart by department
- `TopPerformers` leaderboard list + `AtRiskKPIs` list side-by-side
- `ScoreDistributionChart` — bell curve / histogram of composite scores

---

### 9.2 KPI Library — `src/features/kpis/components/KPILibraryPage.tsx`

**Header:**
- Title + count badge
- Filters: Status tabs (All / Draft / Active / Deprecated) + Department dropdown + Search input
- View toggle: Grid cards / List table
- "New KPI" button (hr_admin, manager only)

**Grid View:**
- `KPICard` component: coloured left border (category colour), name, code badge, unit + frequency pills, status badge, scoring direction icon (TrendingUp / TrendingDown), tags, action menu (Edit, Change Status, View History, Clone)
- Framer Motion `staggerChildren` on load

**List View:**
- DataTable with columns: Code, Name, Unit, Frequency, Data Source, Status, Version, Actions
- Sortable by any column header
- Row click → opens `KPIDetailDrawer`

**KPIDetailDrawer:**
- `Sheet` component sliding from right, 520px wide
- Tabs: Overview | Formula | History | Targets
- Overview tab: all KPI fields in 2-column detail layout
- Formula tab (only if data_source=formula): syntax-highlighted formula display + dependency chain visualisation
- History tab: version timeline with `KPIHistoryItem` cards

---

### 9.3 KPI Builder Form — `src/features/kpis/components/KPIBuilderForm.tsx`

A multi-step form using react-hook-form + zod. Steps shown as a stepper at top.

**Step 1 — Basic Info:**
- Name (required)
- Code (auto-generated from name, uppercase + underscores, editable)
- Description (textarea)
- Category (select with colour preview)
- Tags (multi-select combobox)

**Step 2 — Measurement:**
- Unit (radio group with icon previews for each unit type)
- Custom unit label (shown only when unit=custom)
- Currency code (shown only when unit=currency)
- Frequency (radio group: Daily, Weekly, Monthly, Quarterly, Yearly)
- Decimal places (0–6 slider)

**Step 3 — Data Source:**
- Data source (radio: Manual / Formula / Integration)
- **Formula section** (shown only when formula selected):
  - `KPIFormulaEditor` — a `Textarea` with syntax highlighting via CSS
  - Live "Validate Formula" button → calls `useValidateFormulaMutation`
  - Shows referenced KPI codes as chips
  - Shows validation errors inline in red

**Step 4 — Scoring:**
- Scoring direction (toggle: Higher is Better / Lower is Better) with visual example
- Min value / Max value inputs (optional)
- Organisation-wide toggle

**Step 5 — Review:**
- Summary of all entered values
- "Save as Draft" + "Submit for Approval" buttons

---

### 9.4 Target Setting — `src/features/targets/components/TargetSetPage.tsx`

**Two sub-views toggled by tabs:**

**Tab 1 — Individual Assignment:**
- Cycle selector
- Employee selector (searchable dropdown)
- KPI multi-select
- For each selected KPI: target value, stretch target, minimum value, weight input
- `WeightDistributionBar` — visual bar showing weight allocation across all KPIs (must sum to 100%)
- Add Milestones accordion per KPI

**Tab 2 — Cascade View — `TargetCascadeTree.tsx`:**
Using dnd-kit drag and drop:
- Tree layout: Org target → Department targets → Individual targets
- Each node is a draggable card showing: KPI name, assignee, target value, weight
- Drag a child node to a different parent to re-assign
- Click a node → inline edit target value + weight
- "Auto-distribute" button: proportionally split parent target to children
- Visual connection lines between parent and child nodes
- At the bottom: cascade summary table

---

### 9.5 Actuals Entry — `src/features/actuals/components/ActualEntryPage.tsx`

**Layout:**
- Left panel (1/3): list of user's targets for active cycle, grouped by frequency
  - Each item shows KPI name + period status chips (green=submitted, orange=pending, grey=future)
  - Click a target to select it

- Right panel (2/3): entry area for selected target
  - `ActualEntryForm`: period selector, value input with unit hint, notes textarea
  - Evidence section: drag-drop file upload area
  - Submit / Save Draft buttons
  - `ActualTimeline`: Recharts line chart showing target line vs actual dots over time

---

### 9.6 Scorecard — `src/features/scoring/components/KPIScorecardTable.tsx`

Using dnd-kit sortable for row reordering:

Columns:
- Drag handle (GripVertical icon)
- KPI Name + code
- Weightage % + visual progress bar
- Target value
- Actual value
- Achievement % (coloured: green ≥100%, amber 60–99%, red <60%)
- Weighted Score
- Rating badge (coloured chip)
- Manager Adjustment button (pencil icon, only for managers)

Features:
- Drag rows to reorder KPI priority
- `ScoreAdjustmentForm` inline or in modal: new score input + mandatory reason textarea
- Locked state: all inputs disabled + lock icon when status=FINAL

---

### 9.7 Performance Heatmap — `src/features/dashboards/components/PerformanceHeatmap.tsx`

```typescript
// Grid: rows = employees, columns = KPIs
// Each cell: coloured square (Tailwind bg classes based on achievement %)
//   ≥120%: bg-emerald-600   exceeds stretch
//   ≥100%: bg-emerald-400   on target
//   ≥80%:  bg-amber-300     close
//   ≥60%:  bg-orange-400    at risk
//   <60%:  bg-red-500       critical
// Tooltip on hover: employee name, KPI name, value, achievement %
// No library needed — pure CSS grid
```

---

### 9.8 Notifications — `src/features/notifications/components/`

**NotificationBell.tsx:**
- Bell icon in TopBar with unread count badge
- Popover on click showing last 5 notifications
- "View all" link to full NotificationPanel

**NotificationPanel.tsx:**
- Full-page or drawer listing all notifications
- Grouped by: Today / This week / Older
- Each item: type icon (colour-coded), title, body snippet, timestamp, read/unread indicator
- Mark all read button
- Filter tabs: All / Unread / At-risk / Reminders

---

## 10. Charts — Recharts Specifications

All charts must use `ResponsiveContainer` and respect the current theme colours via CSS variables.

### 10.1 `AchievementGauge.tsx` — Radial gauge
```typescript
// RadialBarChart with single bar
// Colour: gradient from primary at 100% to red at 0%
// Centre text: achievement % (large, bold) + "of target" (small, muted)
// Animated: bars grow on mount
```

### 10.2 `TrendSparkline.tsx` — Mini line chart
```typescript
// 60x24px inline sparkline using LineChart
// No axes, no tooltip (just visual trend)
// Color: green if upward, red if downward
```

### 10.3 `TargetVsActualChart.tsx` — Bar + line combo
```typescript
// BarChart: actual values per period
// ReferenceLine: target value (dashed)
// LineChart overlay: achievement % (right Y-axis)
// Tooltip: period label, actual, target, achievement %
```

### 10.4 `ScoreDistributionChart.tsx` — Bell curve histogram
```typescript
// BarChart grouped by rating label
// X-axis: rating labels (Does Not Meet → Exceptional)
// Y-axis: count of employees
// Colors: mapped to rating (red → amber → green → emerald)
```

---

## 11. Routing — `src/router/index.tsx`

```typescript
const routes = [
  { path: '/', element: <DashboardIndex /> },            // auto-routes by role
  { path: '/kpis', element: <KPILibraryPage /> },
  { path: '/kpis/templates', element: <KPITemplateGallery /> },
  { path: '/kpis/new', element: <KPIBuilderForm /> },
  { path: '/kpis/:id', element: <KPILibraryPage /> },   // opens detail drawer
  { path: '/cycles', element: <CycleListPage /> },
  { path: '/targets', element: <TargetSetPage /> },
  { path: '/targets/cascade', element: <TargetCascadeTree /> },
  { path: '/my-targets', element: <EmployeeTargetPage /> },
  { path: '/actuals', element: <ActualEntryPage /> },
  { path: '/approvals', element: <PendingApprovalsPage /> },
  { path: '/scoring/team', element: <ScorecardPage /> },
  { path: '/scoring/calibration', element: <CalibrationSessionPage /> },
  { path: '/scoring/org', element: <OrgDashboard /> },
  { path: '/reports', element: <ReportsPage /> },
  { path: '/notifications', element: <NotificationPanel /> },
  { path: '/settings', element: <SettingsPage /> },
];

// All routes wrapped in: ProtectedRoute → AppShell → PageTransition
```

---

## 12. Dev Utilities

### `RoleSwitcher.tsx` — visible only in development

A floating banner at the very top of the screen (above everything):
```
[Viewing as: HR Admin ▾] [Switch to: Manager | Employee | Executive]
```
Clicking a role dispatches `authSlice.switchRole()` and re-renders all role-gated UI instantly.

---

## 13. Design System Tokens

Define in `tailwind.config.ts` and as CSS variables in `src/index.css`:

```css
:root {
  --primary: 221 83% 53%;         /* blue-600 */
  --primary-foreground: 0 0% 98%;
  --radius: 0.5rem;
  --sidebar-width: 240px;
  --sidebar-width-collapsed: 64px;
  --density-spacing: 1;           /* multiplier: compact = 0.75 */
}
```

**Colour meanings (apply consistently):**
- Achievement ≥ 120%: `emerald-500` (exceptional)
- Achievement ≥ 100%: `green-500` (on target)
- Achievement ≥ 80%: `yellow-500` (close)
- Achievement ≥ 60%: `orange-500` (at risk)
- Achievement < 60%: `red-500` (critical)
- Draft status: `slate-400`
- Active status: `green-500`
- Locked status: `blue-500`
- Final status: `purple-500`

---

## 14. Error & Loading States

Every RTK Query-powered component must handle all three states:

```typescript
const { data, isLoading, isError, error } = useListKPIsQuery({});

if (isLoading) return <LoadingSkeleton rows={5} />;
if (isError) return <ErrorState message="Failed to load KPIs" retry={refetch} />;
if (!data?.items.length) return <EmptyState
  icon={Target}
  title="No KPIs yet"
  description="Create your first KPI to get started"
  action={{ label: 'Create KPI', href: '/kpis/new' }}
/>;
```

`LoadingSkeleton` uses shadcn `Skeleton` with pulse animation, matching the shape of the content it replaces.

---

## 15. Accessibility & Performance

1. All interactive elements have `aria-label` attributes.
2. All tables have proper `<thead>`, `<th scope="col">` markup.
3. Color indicators always have a secondary indicator (icon or text) — never colour alone.
4. Keyboard navigation for all dropdowns, modals, and sidebars.
5. `React.lazy()` + `Suspense` for route-level code splitting.
6. `useMemo` on expensive list filters and chart data transformations.
7. Virtualise lists with more than 50 rows using `@tanstack/react-virtual`.

---

## 16. Final Checklist Before Delivering

Verify all of the following work before considering the build complete:

- [ ] All 3 roles render correct navigation and page content
- [ ] Theme panel changes apply in real-time (colors, radius, font, density)
- [ ] Dark mode toggles correctly across all components
- [ ] KPI builder completes all 5 steps and creates a mock KPI
- [ ] Formula validation runs and shows referenced codes + errors
- [ ] Target cascade tree renders parent → child hierarchy with drag-to-reorder
- [ ] Weight distribution bar shows warning when weights ≠ 100%
- [ ] Actuals timeline chart renders with mock data
- [ ] Scorecard table rows are draggable and manager adjustment form works
- [ ] Performance heatmap renders all employees × KPIs with correct colours
- [ ] Notifications panel shows unread count and marks as read
- [ ] All RTK Query hooks show loading skeleton then data (300–600ms delay)
- [ ] All RTK Query hooks show error state when `isError` is simulated
- [ ] Page transitions animate on route change (Framer Motion)
- [ ] Sidebar collapses smoothly on toggle
- [ ] RoleSwitcher banner switches UI correctly in dev mode
- [ ] `npm run build` produces zero TypeScript errors
