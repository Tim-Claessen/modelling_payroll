# Payroll Data Model

A source-agnostic semantic layer for payroll and workforce data. Sits between raw source data and downstream reporting, control testing, and analytics.

Uses a **star schema**: transaction tables (facts) joined to reference tables (dimensions).

---

## Modules

The model is split into a required core and optional modules. Each module is a self-contained block in both `payroll_model.mermaid` and `payroll_model.md` — toggle one in or out by editing the same-named block in both files.

### core _(required)_

| Table               | What it holds                                                     |
| ------------------- | ----------------------------------------------------------------- |
| `fact_payslip_line` | Individual earnings and deduction lines per employee per pay run  |
| `dim_employee`      | Employee record — name, status, type, hire/termination dates      |
| `dim_pay_run`       | Pay run metadata — dates, frequency, status, correction links     |
| `dim_pay_category`  | Pay codes — earnings, deductions, allowances, tax                 |
| `dim_organisation`  | Departments, business units, and hierarchy                        |
| `dim_job`           | Job titles, classifications, salary bands                         |
| `dim_location`      | Work sites, cities, states, countries                             |
| `dim_calendar`      | Every date with week, month, fiscal period, and pay period labels |

### Optional modules

| Module           | Tables                                | What it adds                                  |
| ---------------- | ------------------------------------- | --------------------------------------------- |
| `SALARY`         | `fact_salary_assignment`              | Contracted pay rates and salary history       |
| `LEAVE`          | `fact_leave_record`, `dim_leave_type` | Leave requests, approvals, and balances       |
| `TIMESHEETS`     | `fact_timesheet_entry`                | Time entries against cost centres or projects |
| `ROSTERS`        | `fact_roster_assignment`              | Planned and actual shift assignments          |
| `BANK ACCOUNT`   | `dim_bank_account`                    | Employee payment details (access-controlled)  |
| `PUBLIC HOLIDAY` | `dim_public_holiday`                  | Location-specific public holidays             |

---

## Key design decisions

### History tracking

Most reference tables track change over time — a new row is created per change, with `effective_from_date` / `effective_to_date` / `is_current_flag`. The surrogate key (`*_key`) identifies a _version_ of a record; the business key (`*_code`) identifies the _entity_ across versions.

- **Current state:** `WHERE is_current_flag = TRUE`
- **Point-in-time:** `WHERE effective_from_date <= @date AND effective_to_date >= @date`

Tables that track history: `dim_employee`, `dim_organisation`, `dim_job`, `dim_location`.

### For-period vs. in-period

`dim_pay_run` carries two date ranges:

- `for_period_*` — the period the pay _relates to_ (when the work was done)
- `in_period_*` — the period the pay run was _processed_

These diverge for back-pays, corrections, and off-cycle runs. Correction runs link back to the original via `adjusted_pay_run_key`.

### Organisation vs. cost centre

An employee's home org flows through all transaction tables via the employee key — join through `dim_employee` to get to `dim_organisation`. Never put `organisation_key` directly on a fact table.

Cost allocation (where costs are charged) is a flat `cost_centre_code` text attribute on `fact_payslip_line` and `fact_timesheet_entry`. If cost centre hierarchies or display names are needed later, a `dim_cost_centre` can be added.

### Salary as a fact table

`fact_salary_assignment` is a fact table (not a dimension) because its primary use is variance analysis — comparing contracted rates against actual amounts paid. It holds measurable values (`annual_salary_amount`, `hourly_rate_amount`, `fte_ratio`) that consumers aggregate and trend.

---

## Column naming conventions

| Pattern      | Example                | Meaning                                                    |
| ------------ | ---------------------- | ---------------------------------------------------------- |
| `*_key`      | `employee_key`         | Surrogate key — unique per version, used for joins         |
| `*_code`     | `employee_code`        | Business key — stable, from source system, used in filters |
| `*_name`     | `department_name`      | Display label                                              |
| `*_date`     | `effective_from_date`  | Date value                                                 |
| `*_amount`   | `annual_salary_amount` | Monetary value                                             |
| `*_quantity` | `hours_quantity`       | Numeric measure                                            |
| `*_flag`     | `is_current_flag`      | Boolean                                                    |

---

## Validation

```bash
python validate_model.py                    # checks payroll_model.md
python validate_model.py path/to/model.md  # specify a path
```

Checks: foreign key integrity, primary keys, history column completeness, naming conventions, no orphaned tables, no duplicate column names.

---

## TODO

- Include data quality tests based on the model
