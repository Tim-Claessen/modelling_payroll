# Payroll Data Model — Business / Semantic Layer

A modular, source-agnostic dimensional model for payroll and workforce data. Designed to sit between raw/staged data and analytical consumers (control testing, workforce analytics, reporting).

---

## Design Rationale

### Why Dimensional Modelling (Star Schema)?

This is a **semantic/business layer** — its job is to present clean, queryable data to downstream consumers. The modelling approach was chosen to match that purpose:

| Approach | Fit for Semantic Layer | Notes |
|---|---|---|
| **Star Schema** ✅ | Excellent | Optimised for query simplicity, business readability, and BI tool compatibility |
| Data Vault | Poor | Designed for integration/staging — introduces unnecessary join complexity at consumption layer |
| Anchor Modelling | Poor | Even more decomposed than Data Vault — valuable for flexibility, not for consumption |
| Hybrid (DV → Star) | Ideal end-state | Data Vault feeds the integration layer; star schema serves the business layer. This model covers the latter half |

**Key insight:** A well-designed enterprise platform often uses Data Vault *below* this layer and star schema *at* this layer. This model is scoped for the semantic layer only.

### Design Principles

- **Source-agnostic** — Canonical naming only. No vendor-specific column names or assumptions about upstream systems. Grain reflects business processes, not source schemas.
- **Modular** — Six subject areas, each independently queryable. Shared (conformed) dimensions link them together when cross-domain analysis is needed.
- **SCD Type 2 on dimensions** — Dimensions that change over time (Employee, Organisation, Job, Location) carry full SCD2 columns: `effective_from_date`, `effective_to_date`, and `is_current_flag`. Current rows have `effective_to_date = 9999-12-31`. This captures the complete history of dimensional changes (promotions, transfers, re-orgs) and allows fact records to be associated with the *correct version* of a dimension at the time of the event. For current-state queries, simply filter `is_current_flag = TRUE`.
- **Temporal facts** — Fact tables are inherently time-series. Each pay run, leave record, timesheet entry, and roster assignment is anchored to specific dates. Fact-to-dimension joins use surrogate keys that point to the *version* of the dimension that was active when the event occurred — preserving historical accuracy.
- **For Period / In Period** — Pay runs use the SAP-originated concept of separating *when work was performed* (For Period) from *when the pay run was processed* (In Period). This is essential for correctly handling back-pays, corrections, and off-cycle runs.
- **No streaming / CDC concerns** — The model assumes batch-loaded data. It does not prescribe ingestion patterns, change capture mechanisms, or real-time processing. Those are upstream infrastructure concerns.
- **Extensible** — Conformed dimensions (Employee, Organisation, Calendar) are integration points for adjacent domains (Risk, Process, Finance).

---

## Subject Areas

| Module | Fact Table | Description |
|---|---|---|
| **Payroll** | `fact_payslip_line` | Individual earnings/deduction lines per employee per pay run |
| **Salary** | `fact_salary_assignment` | Contracted/agreed pay rates and salary history per employee |
| **Leave** | `fact_leave_record` | Leave requests, approvals, and balances |
| **Timesheet** | `fact_timesheet_entry` | Submitted time entries against cost centres or projects |
| **Roster** | `fact_roster_assignment` | Planned shift assignments |
| **Workforce** | *(dimension-only)* | Employee master, organisation hierarchy, job classification — consumed by all other modules |

### Conformed Dimensions (Shared)

| Dimension | Key | Role |
|---|---|---|
| `dim_employee` | `employee_key` | Canonical employee record — demographics, employment details, classification |
| `dim_organisation` | `organisation_key` | Cost centres, departments, business units, legal entities |
| `dim_calendar` | `calendar_date` | Standard date dimension — fiscal periods, pay periods, public holidays |
| `dim_job` | `job_key` | Job titles, classifications, bands/grades |
| `dim_location` | `location_key` | Work sites, regions, countries |

### Subject-Specific Dimensions

| Dimension | Used By | Role |
|---|---|---|
| `dim_pay_category` | Payroll | Earnings types, deduction types, allowance codes |
| `dim_pay_run` | Payroll | Pay run metadata — period, frequency, status, For/In period dates |
| `dim_leave_type` | Leave | Leave categories (annual, sick, parental, etc.) |
| `dim_shift_type` | Roster | Shift definitions, standard hours, break rules |

### Standalone Dimensions

| Dimension | Linked To | Role |
|---|---|---|
| `dim_bank_account` | `dim_employee` | Employee bank/payment details — separated for access control |

---

## Entity-Relationship Diagram

See [`model.mermaid`](model.mermaid) — renders natively on GitHub.

## Schema Reference

See [`schema.md`](schema.md) — full column-level documentation with data types, descriptions, and constraints.

## Model Validation

Run `python validate_model.py` to check the mermaid diagram for structural integrity. See [`validate_model.py`](validate_model.py).

---

## Column Conventions

| Convention | Example | Purpose |
|---|---|---|
| `*_key` | `employee_key` | Surrogate key (integer or hash). Decouples from source natural keys |
| `*_code` | `pay_category_code` | Business/natural code — human-readable, source-mapped upstream |
| `*_name` | `department_name` | Display label |
| `*_date` | `effective_from_date` | Date typed |
| `*_amount` | `gross_amount` | Monetary (decimal) |
| `*_quantity` | `hours_quantity` | Numeric measure |
| `*_flag` | `is_current_flag` | Boolean |

All monetary amounts assume a single reporting currency at this layer. Multi-currency support would add `currency_code` and `*_local_amount` / `*_reporting_amount` pairs.

---

## Temporal Design — SCD Type 2

### How Dimension History Works

Dimensions that change over time (Employee, Organisation, Job, Location) use **SCD Type 2** — each change creates a new row with its own surrogate key:

| employee_key | employee_code | job_title | organisation_name | effective_from_date | effective_to_date | is_current_flag |
|---|---|---|---|---|---|---|
| 1001 | EMP-042 | Analyst | Finance | 2023-01-15 | 2024-06-30 | FALSE |
| 1002 | EMP-042 | Senior Analyst | Finance | 2024-07-01 | 2025-02-28 | FALSE |
| 1003 | EMP-042 | Senior Analyst | Risk | 2025-03-01 | 9999-12-31 | TRUE |

### For Period / In Period

Pay runs carry two temporal anchors:

| Field | Meaning | Example |
|---|---|---|
| `for_period_start_date` / `for_period_end_date` | The period the pay *relates to* (when work was done) | 2024-01-01 to 2024-01-31 |
| `in_period_start_date` / `in_period_end_date` | The period the pay run was *processed in* | 2024-03-01 to 2024-03-31 |

For a normal scheduled run, these are identical. They diverge for back-pays, corrections, and off-cycle adjustments.

### Adjustments and Corrections

Handled within the existing pay run model via `pay_run_type` and `adjusted_pay_run_key` on `dim_pay_run`. All adjustment payslip lines flow through `fact_payslip_line` — no separate tables needed.

### Querying Patterns

- **Current state only:** `WHERE is_current_flag = TRUE` on dimension joins
- **Point-in-time:** `WHERE effective_from_date <= @target_date AND effective_to_date >= @target_date`
- **What was paid for a period:** Join on `for_period_start_date` / `for_period_end_date`
- **What was processed in a period:** Join on `in_period_start_date` / `in_period_end_date`

### Future: Bi-Temporal Extension

Add `recorded_from_datetime` and `recorded_to_datetime` columns alongside existing effective dates to separate "what was true in the real world" from "what was known in the system." The current SCD2 structure supports this without schema-breaking changes.

---

## Extensibility — Adjacent Domains

The conformed dimensions are designed as integration points:

- **Risk / Controls** — Join on `employee_key` + `organisation_key` + `calendar_date` to link payroll facts to control test results
- **Finance / GL** — Join on `organisation_key` (cost centre) + `calendar_date` to reconcile payroll accruals against general ledger
- **Process Mining** — Join on `employee_key` + timestamps to correlate payroll events with process flows

### Future State: Position Management

A `dim_position` and `fact_position_assignment` module would capture funded headcount, vacancy tracking, and position-to-employee mapping. The conformed dimensions are ready for it.

---

## How to Use This Model

1. **Understand the grain** — Each fact table's grain is documented in the diagram and schema reference.
2. **Pick your subject area** — Each module works independently.
3. **Map your sources** — Upstream ETL maps source-system fields to the canonical columns. The model prescribes the target shape, not the ingestion method.
4. **Query current state** — Filter SCD2 dimensions on `is_current_flag = TRUE`.
5. **Query historically** — Facts point to the correct dimension version via surrogate keys.
6. **Validate** — Run `python validate_model.py` to check structural integrity.

---

## Repository Structure

```
├── README.md              ← You are here
├── model.mermaid          ← Full ER diagram (renders on GitHub)
├── schema.md              ← Column-level documentation
└── validate_model.py      ← Model integrity checks
```
