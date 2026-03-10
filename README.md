# Payroll Data Model

A source-agnostic data model for payroll and workforce data. Sits between raw source data and downstream reporting tools, control testing, and workforce analytics.

---

## Table of Contents

- [Payroll Data Model](#payroll-data-model)
  - [Table of Contents](#table-of-contents)
  - [What is this?](#what-is-this)
  - [How the model is structured](#how-the-model-is-structured)
  - [Subject areas](#subject-areas)
    - [Shared reference tables](#shared-reference-tables)
    - [Subject-specific reference tables](#subject-specific-reference-tables)
    - [Standalone reference tables](#standalone-reference-tables)
  - [Key design decisions](#key-design-decisions)
    - [Tracking history over time](#tracking-history-over-time)
    - [When pay relates to vs. when it was processed](#when-pay-relates-to-vs-when-it-was-processed)
    - [Organisation vs. cost centre](#organisation-vs-cost-centre)
    - [Salary as a transaction table](#salary-as-a-transaction-table)
  - [Common query patterns](#common-query-patterns)
  - [Column naming conventions](#column-naming-conventions)
  - [Validation](#validation)
  - [Implementation notes](#implementation-notes)
    - [Surrogate key strategy](#surrogate-key-strategy)
    - [Late-arriving data](#late-arriving-data)
    - [Grain discipline](#grain-discipline)
    - [Shared reference table governance](#shared-reference-table-governance)
  - [Extending the model](#extending-the-model)
  - [TODO](#todo)

---

## What is this?

This model defines the structure of a payroll data warehouse — specifically the **semantic layer**: the clean, business-ready tables that sit above raw source data and below reporting and analytics tools.

It covers six subject areas: payroll, salary, leave, timesheets, rosters, and workforce (employee master data). Each area can be queried independently, or joined to others through shared reference tables.

**What this model is not:**

- It does not prescribe how data gets loaded (ETL/ELT is out of scope)
- It does not assume a specific source system (Workday, SAP, ADP, etc.)
- It does not handle real-time data — it assumes batch loads

---

## How the model is structured

The model uses a **star schema** — the standard pattern for analytical data models. If you're new to this:

- **Transaction tables** (called _fact tables_) store the actual events: payslip lines, leave requests, timesheet entries, shift assignments, salary changes.
- **Reference tables** (called _dimensions_) store the descriptive context: who the employee is, what department they're in, which pay category was applied, and so on.

A query typically starts from a transaction table and joins to reference tables to add the labels and groupings needed for reporting. This pattern is fast to query, easy to read, and works well with BI tools.

---

## Subject areas

| Area          | Transaction table         | What it captures                                                               |
| ------------- | ------------------------- | ------------------------------------------------------------------------------ |
| **Payroll**   | `fact_payslip_line`       | Individual earnings and deduction lines per employee per pay run               |
| **Salary**    | `fact_salary_assignment`  | Contracted pay rates and salary history                                        |
| **Leave**     | `fact_leave_record`       | Leave requests, approvals, and balances                                        |
| **Timesheet** | `fact_timesheet_entry`    | Time entries against cost centres or projects                                  |
| **Roster**    | `fact_roster_assignment`  | Planned and actual shift assignments                                           |
| **Workforce** | _(reference tables only)_ | Employee master data, org hierarchy, jobs, locations — used by all other areas |

### Shared reference tables

These are used across all subject areas. Any table that needs employee, date, or org context uses these.

| Table              | What it holds                                                                     |
| ------------------ | --------------------------------------------------------------------------------- |
| `dim_employee`     | Canonical employee record — name, employment status, type, hire/termination dates |
| `dim_organisation` | Departments, business units, legal entities, and their hierarchy                  |
| `dim_calendar`     | Every calendar date, with week, month, year, fiscal period, and pay period labels |
| `dim_job`          | Job titles, classifications, and salary bands                                     |
| `dim_location`     | Work sites, cities, states, and countries                                         |

### Subject-specific reference tables

| Table                | Used by             | What it holds                                                             |
| -------------------- | ------------------- | ------------------------------------------------------------------------- |
| `dim_pay_run`        | Payroll             | Pay run metadata — dates, frequency, status, and links to correction runs |
| `dim_pay_category`   | Payroll             | Pay codes — earnings types, deductions, allowances, and tax               |
| `dim_leave_type`     | Leave               | Leave categories (annual, sick, parental, etc.)                           |
| `dim_shift_type`     | Roster              | Shift definitions including standard hours and break rules                |
| `dim_public_holiday` | Calendar / Location | Location-specific public holidays by date                                 |

### Standalone reference tables

| Table              | What it holds                                                                                         |
| ------------------ | ----------------------------------------------------------------------------------------------------- |
| `dim_bank_account` | Employee bank and payment details — deliberately separated from the employee table for access control |

---

## Key design decisions

### Tracking history over time

Most reference tables change over time — employees get promoted, departments get renamed, jobs get reclassified. Rather than overwriting old values (which would break historical reports), this model tracks history: each change creates a new row with date ranges showing when that version was valid.

| employee_key | employee_code | job_title      | department | effective_from_date | effective_to_date | is_current_flag |
| ------------ | ------------- | -------------- | ---------- | ------------------- | ----------------- | --------------- |
| 1001         | EMP-042       | Analyst        | Finance    | 2023-01-15          | 2024-06-30        | FALSE           |
| 1002         | EMP-042       | Senior Analyst | Finance    | 2024-07-01          | 2025-02-28        | FALSE           |
| 1003         | EMP-042       | Senior Analyst | Risk       | 2025-03-01          | 9999-12-31        | TRUE            |

Key points:

- The surrogate key (`employee_key`) changes with each version — it uniquely identifies a _version_ of the record, not the person
- The business code (`employee_code`) stays the same across all versions — it identifies the _person_
- The current row always has `effective_to_date = 9999-12-31` and `is_current_flag = TRUE`
- Transaction tables store the surrogate key of the version that was active _at the time of the event_, preserving historical accuracy

**To query current state:** filter on `is_current_flag = TRUE`
**To query at a point in time:** filter on `effective_from_date <= @date AND effective_to_date >= @date`

Reference tables that track history: `dim_employee`, `dim_organisation`, `dim_job`, `dim_location`.

> **A note on leave records spanning a role change:** If an employee takes leave from Jan 15 to Feb 15, and was promoted on Feb 1, the leave record points to the version active when the leave was _approved_. If you need day-by-day attribution (e.g. how many leave days were taken at each grade), that requires exploding the record into daily rows — a reporting-layer concern, not a model change.

### When pay relates to vs. when it was processed

Pay runs carry two separate date ranges:

| Field                                           | What it means                                            | Example  |
| ----------------------------------------------- | -------------------------------------------------------- | -------- |
| `for_period_start_date` / `for_period_end_date` | The period the pay _relates to_ — when the work was done | Jan 1–31 |
| `in_period_start_date` / `in_period_end_date`   | The period the pay run was _processed in_                | Mar 1–31 |

For a normal scheduled pay run these are identical. They diverge for:

- **Back-pays** — work done in January, paid in March
- **Corrections** — a payroll error from last month corrected this month
- **Off-cycle runs** — termination payment processed outside the normal schedule

This split makes it possible to answer both "what did we pay for work done in Q1?" and "what payroll costs were processed in Q1?" Adjustment and correction runs are linked back to the original via `adjusted_pay_run_key` on `dim_pay_run` — no separate tables needed.

### Organisation vs. cost centre

An employee's home organisation (their department or business unit) is stored on the employee record and flows through to all transaction tables via the employee key. No transaction table carries an organisation key directly — you always get to the org by joining through the employee.

Cost allocation is handled separately as a **flat text attribute** on the two tables where costs may be charged somewhere other than the employee's home org:

| Table                  | When cost centre differs     |
| ---------------------- | ---------------------------- |
| `fact_payslip_line`    | Secondments, shared services |
| `fact_timesheet_entry` | Project-based costing        |

`cost_centre_code` is stored as plain text (not a foreign key to a dimension table). This keeps cost allocation simple and avoids unnecessary join complexity. If cost centre reporting later needs hierarchies or display names, a `dim_cost_centre` can be added, or `dim_organisation` can be joined on `cost_centre_code`.

The same principle applies in two other places:

- **Public holidays** (`dim_public_holiday`) reference `location_code` rather than `location_key` — a stable business identifier that doesn't change when a location record is updated, avoiding any version-binding issues
- **Organisation hierarchy** (`dim_organisation`) uses `parent_organisation_code` rather than a surrogate key for the same reason — the parent reference stays valid across restructures

### Salary as a transaction table

`fact_salary_assignment` is modelled as a transaction (fact) table rather than a reference table, even though it has effective date ranges like a slowly-changing record.

This is deliberate: the primary use case is **variance analysis** — comparing contracted rates against actual amounts paid in `fact_payslip_line`. The table contains measurable values (`annual_salary_amount`, `hourly_rate_amount`, `fte_ratio`) that consumers need to aggregate, compare, and trend over time.

Think of it as: "what _should_ have been paid" vs. "what _was_ paid".

---

## Common query patterns

```sql
-- Current employee with their current job and department
SELECT e.first_name, e.last_name, j.job_title, o.organisation_name
FROM dim_employee e
JOIN dim_job j        ON e.job_key          = j.job_key
JOIN dim_organisation o ON e.organisation_key = o.organisation_key
WHERE e.is_current_flag = TRUE

-- Point-in-time: what was this employee's role on a specific date?
WHERE e.effective_from_date <= '2024-06-30'
  AND e.effective_to_date   >= '2024-06-30'

-- What was paid for work done in a period (For Period)?
SELECT e.employee_code, SUM(f.amount)
FROM fact_payslip_line f
JOIN dim_pay_run  pr ON f.pay_run_key  = pr.pay_run_key
JOIN dim_employee e  ON f.employee_key = e.employee_key
WHERE pr.for_period_start_date >= '2024-01-01'
  AND pr.for_period_end_date   <= '2024-01-31'
GROUP BY e.employee_code

-- What payroll costs were processed in a period (In Period)?
WHERE pr.in_period_start_date >= '2024-01-01'
  AND pr.in_period_end_date   <= '2024-01-31'

-- Employee's department: always join through dim_employee
SELECT e.first_name, o.organisation_name
FROM fact_payslip_line f
JOIN dim_employee     e ON f.employee_key    = e.employee_key
JOIN dim_organisation o ON e.organisation_key = o.organisation_key

-- Cost centre on a payslip line: use the attribute directly on the fact
SELECT f.cost_centre_code, SUM(f.amount)
FROM fact_payslip_line f
GROUP BY f.cost_centre_code
```

---

## Column naming conventions

| Pattern      | Example                | Meaning                                                               |
| ------------ | ---------------------- | --------------------------------------------------------------------- |
| `*_key`      | `employee_key`         | Surrogate key — internal to the model, unique per version             |
| `*_code`     | `employee_code`        | Business/natural key — stable, human-readable, maps to source systems |
| `*_name`     | `department_name`      | Display label                                                         |
| `*_date`     | `effective_from_date`  | Date value                                                            |
| `*_amount`   | `annual_salary_amount` | Monetary value (decimal)                                              |
| `*_quantity` | `hours_quantity`       | Numeric measure                                                       |
| `*_flag`     | `is_current_flag`      | Boolean (true/false)                                                  |

**Surrogate vs. business keys:** Every reference table has both. The surrogate key (`*_key`) is generated by the model and changes with each history version — it's what foreign keys reference for joins. The business key (`*_code`) comes from the source system and is stable across versions — it's what you use to look up a specific person, org unit, or job in a report. Use `*_code` in report filters; use `*_key` for table joins.

All monetary amounts assume a single reporting currency at this layer. Multi-currency support would add `currency_code` and separate local/reporting amount columns.

---

## Validation

Run the structural validator to check the model diagram for integrity:

```bash
python validate_model.py                              # uses payroll_model.mermaid in the same directory
python validate_model.py path/to/model.mermaid        # specify a different path
```

Checks run:

- Every foreign key points to a table that exists in the model
- Foreign key data types match their target primary key types
- Every table has a primary key defined
- History-tracking columns are complete (all three of `effective_from_date`, `effective_to_date`, `is_current_flag`)
- Column naming conventions are consistent
- No orphaned tables (every table appears in at least one relationship)
- No duplicate column names within a table

---

## Implementation notes

### Surrogate key strategy

Choose one approach and apply it consistently across all tables:

- **Hash keys** (recommended) — generated from the natural key + effective date. Deterministic, so pipeline re-runs are safe.
- **Auto-increment** — simpler, but requires controlled load ordering and is non-deterministic.

### Late-arriving data

If a payslip line arrives before the employee record has loaded, two options:

- **Load-order dependency** — always load reference tables before transaction tables. Simple, but creates pipeline coupling.
- **Unknown member row** — seed each reference table with a default "Unknown" row (`*_key = -1`). Late-arriving facts point to this row temporarily and are reprocessed when the reference data catches up. More resilient.

### Grain discipline

The stated grain of `fact_payslip_line` is one row per employee × pay run × pay category. Some source systems produce multiple lines for the same combination (e.g. two overtime entries for different cost centres on the same payslip). The same applies to `fact_timesheet_entry` (employee × date × project). If this occurs, either aggregate at load time or add a `line_sequence_number` to preserve source granularity.

### Shared reference table governance

Since `dim_employee`, `dim_organisation`, `dim_calendar`, `dim_job`, and `dim_location` are shared across all subject areas, one pipeline should own each. All other pipelines consume them read-only.

---

## Extending the model

The shared reference tables are designed as integration points for adjacent domains:

- **Risk / Controls** — join on `employee_key` + `calendar_date` to link payroll facts to control test results
- **Finance / GL** — join on `cost_centre_code` + `calendar_date` to reconcile payroll accruals against the general ledger
- **Process Mining** — join on `employee_key` + timestamps to correlate payroll events with process flows

**Future: Position management**
A `dim_position` and `fact_position_assignment` module would add funded headcount tracking, vacancy management, and position-to-employee mapping. The shared reference tables are already ready for it.

**Future: Bi-temporal tracking**
The current model tracks when things were _true in the real world_ (effective dates). Adding `recorded_from_datetime` / `recorded_to_datetime` columns would also capture when the _system first knew about it_ — useful for audit trails and late-correction analysis. The current structure supports this without breaking changes.

**Future: Cost centre dimension**
If cost centre reporting needs hierarchies, display names, or independent history tracking, a `dim_cost_centre` table can be added. The `cost_centre_code` flat attribute on fact tables becomes a foreign key. Alternatively, if cost centres align with org units, `dim_organisation` can serve this purpose by joining on `cost_centre_code`.

---

## TODO

- Inlcude leave balances in model
- Make clearer how to remove entities from the model
- Include some 'tests' that we would want to build based on the data model to continue to validate it's appropraiteness
- consider overaly of timesheet and roster
