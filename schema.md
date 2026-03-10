# Schema Reference — Payroll Data Model

Column-level documentation for all tables. Data types use generic SQL types — adapt to your platform (e.g. Snowflake `NUMBER`, `VARCHAR`, `DATE`).

---

## Conformed Dimensions

### dim_employee

Canonical employee record. SCD Type 2 — each change to an employee's attributes creates a new row with a new surrogate key.

**Grain:** One row per employee per version (effective date range).

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `employee_key` | `INTEGER` | No | Surrogate key (PK). Unique per version — not stable across changes. |
| `employee_code` | `VARCHAR(50)` | No | Business/natural key. Stable identifier across SCD2 versions. |
| `first_name` | `VARCHAR(100)` | No | Employee first/given name. |
| `last_name` | `VARCHAR(100)` | No | Employee surname/family name. |
| `date_of_birth` | `DATE` | Yes | Date of birth. Nullable for privacy-restricted records. |
| `gender` | `VARCHAR(20)` | Yes | Gender identity. Free-text to accommodate non-binary values. |
| `employment_status` | `VARCHAR(30)` | No | Current status: `active`, `terminated`, `on_leave`, `suspended`. |
| `employment_type` | `VARCHAR(30)` | No | Employment basis: `full_time`, `part_time`, `casual`, `contractor`. |
| `hire_date` | `DATE` | No | Original hire date (does not change across SCD2 versions). |
| `termination_date` | `DATE` | Yes | Termination date. NULL if currently employed. |
| `job_key` | `INTEGER` | No | FK → `dim_job.job_key`. The job held during this version. |
| `organisation_key` | `INTEGER` | No | FK → `dim_organisation.organisation_key`. The org unit during this version. |
| `location_key` | `INTEGER` | No | FK → `dim_location.location_key`. The work location during this version. |
| `effective_from_date` | `DATE` | No | SCD2: Start of this version's validity. |
| `effective_to_date` | `DATE` | No | SCD2: End of this version's validity. `9999-12-31` for current row. |
| `is_current_flag` | `BOOLEAN` | No | SCD2: `TRUE` for the active version. |

---

### dim_organisation

Organisational hierarchy. SCD Type 2 — captures restructures, renames, and re-parenting.

**Grain:** One row per org unit per version.

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `organisation_key` | `INTEGER` | No | Surrogate key (PK). |
| `organisation_code` | `VARCHAR(50)` | No | Business/natural key. Stable across versions. |
| `organisation_name` | `VARCHAR(200)` | No | Display name of the org unit. |
| `organisation_type` | `VARCHAR(50)` | No | Type: `cost_centre`, `department`, `business_unit`, `legal_entity`, `division`. |
| `cost_centre_code` | `VARCHAR(50)` | Yes | Cost centre code if applicable. |
| `cost_centre_name` | `VARCHAR(200)` | Yes | Cost centre display name. |
| `department_name` | `VARCHAR(200)` | Yes | Department name. |
| `business_unit_name` | `VARCHAR(200)` | Yes | Business unit name. |
| `legal_entity_name` | `VARCHAR(200)` | Yes | Legal entity name. |
| `parent_organisation_key` | `INTEGER` | Yes | FK → `dim_organisation.organisation_key`. Self-referencing hierarchy. NULL for root. |
| `effective_from_date` | `DATE` | No | SCD2: Start of validity. |
| `effective_to_date` | `DATE` | No | SCD2: End of validity. `9999-12-31` for current. |
| `is_current_flag` | `BOOLEAN` | No | SCD2: `TRUE` for active version. |

---

### dim_calendar

Standard date dimension. Immutable — no SCD2.

**Grain:** One row per calendar date.

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `calendar_date` | `DATE` | No | Natural key (PK). The date itself. |
| `day_of_week` | `INTEGER` | No | ISO day of week (1=Monday, 7=Sunday). |
| `day_name` | `VARCHAR(10)` | No | Day name: `Monday` through `Sunday`. |
| `week_of_year` | `INTEGER` | No | ISO week number (1–53). |
| `calendar_month` | `INTEGER` | No | Month number (1–12). |
| `calendar_year` | `INTEGER` | No | Four-digit year. |
| `fiscal_month` | `INTEGER` | No | Fiscal month number. Configurable per organisation. |
| `fiscal_year` | `INTEGER` | No | Fiscal year. |
| `fiscal_period_name` | `VARCHAR(20)` | No | Display label, e.g. `FY25-Q2`. |
| `pay_period_identifier` | `VARCHAR(30)` | Yes | Identifier linking this date to a pay period. NULL if not within a pay period. |
| `is_public_holiday_flag` | `BOOLEAN` | No | `TRUE` if a gazetted public holiday. |
| `public_holiday_name` | `VARCHAR(100)` | Yes | Holiday name. NULL if not a holiday. |

---

### dim_job

Job titles and classifications. SCD Type 2.

**Grain:** One row per job per version.

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `job_key` | `INTEGER` | No | Surrogate key (PK). |
| `job_code` | `VARCHAR(50)` | No | Business/natural key. Stable across versions. |
| `job_title` | `VARCHAR(200)` | No | Job title. |
| `job_classification` | `VARCHAR(100)` | Yes | Classification (e.g. award category, ANZSCO code). |
| `job_band` | `VARCHAR(50)` | Yes | Salary band or level. |
| `job_grade` | `VARCHAR(50)` | Yes | Grade within band. |
| `job_family` | `VARCHAR(100)` | Yes | Job family grouping (e.g. `Engineering`, `Finance`, `Operations`). |
| `effective_from_date` | `DATE` | No | SCD2: Start of validity. |
| `effective_to_date` | `DATE` | No | SCD2: End of validity. |
| `is_current_flag` | `BOOLEAN` | No | SCD2: `TRUE` for active version. |

---

### dim_location

Work sites and geographic hierarchy. SCD Type 2.

**Grain:** One row per location per version.

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `location_key` | `INTEGER` | No | Surrogate key (PK). |
| `location_code` | `VARCHAR(50)` | No | Business/natural key. |
| `location_name` | `VARCHAR(200)` | No | Display name. |
| `site_name` | `VARCHAR(200)` | Yes | Physical site or building name. |
| `city` | `VARCHAR(100)` | Yes | City. |
| `state_province` | `VARCHAR(100)` | Yes | State, province, or territory. |
| `country` | `VARCHAR(100)` | No | Country name. |
| `region` | `VARCHAR(100)` | Yes | Business region grouping. |
| `effective_from_date` | `DATE` | No | SCD2: Start of validity. |
| `effective_to_date` | `DATE` | No | SCD2: End of validity. |
| `is_current_flag` | `BOOLEAN` | No | SCD2: `TRUE` for active version. |

---

## Standalone Dimensions

### dim_bank_account

Employee bank/payment details. Deliberately separated from `dim_employee` for access control — this table can have restricted permissions independently.

**Grain:** One row per bank account per employee. Multiple accounts per employee supported (split pay).

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `bank_account_key` | `INTEGER` | No | Surrogate key (PK). |
| `employee_key` | `INTEGER` | No | FK → `dim_employee.employee_key`. The employee who holds this account. |
| `bank_name` | `VARCHAR(200)` | No | Name of the financial institution. |
| `bsb_code` | `VARCHAR(20)` | Yes | Branch/routing code. Format varies by country. |
| `account_number_masked` | `VARCHAR(50)` | No | Masked account number (e.g. `****1234`). Full number should not be stored at this layer. |
| `account_name` | `VARCHAR(200)` | No | Name on the account. |
| `account_type` | `VARCHAR(30)` | No | Account type: `savings`, `cheque`, `superannuation`, `other`. |
| `is_primary_flag` | `BOOLEAN` | No | `TRUE` if this is the primary/default payment account. |
| `split_percentage` | `DECIMAL(5,2)` | Yes | Percentage of net pay directed to this account. NULL if fixed-amount split. |
| `valid_from_date` | `DATE` | No | Date this account became active for the employee. |
| `valid_to_date` | `DATE` | No | Date this account was deactivated. `9999-12-31` if active. |
| `is_current_flag` | `BOOLEAN` | No | `TRUE` for currently active accounts. |

---

## Subject-Specific Dimensions

### dim_pay_run

Pay run metadata. Not SCD2 — each pay run is a distinct event.

**Grain:** One row per pay run.

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `pay_run_key` | `INTEGER` | No | Surrogate key (PK). |
| `pay_run_code` | `VARCHAR(50)` | No | Business identifier for the pay run. |
| `pay_frequency` | `VARCHAR(20)` | No | Frequency: `weekly`, `fortnightly`, `monthly`, `ad_hoc`. |
| `pay_run_type` | `VARCHAR(30)` | No | Type: `scheduled`, `off_cycle`, `correction`, `back_pay`. |
| `for_period_start_date` | `DATE` | No | For Period: Start of the period the pay *relates to*. |
| `for_period_end_date` | `DATE` | No | For Period: End of the period the pay *relates to*. |
| `in_period_start_date` | `DATE` | No | In Period: Start of the period the pay run was *processed in*. |
| `in_period_end_date` | `DATE` | No | In Period: End of the period the pay run was *processed in*. |
| `payment_date` | `DATE` | No | Date funds were/will be disbursed. |
| `pay_run_status` | `VARCHAR(30)` | No | Status: `draft`, `approved`, `processing`, `completed`, `reversed`. |
| `adjusted_pay_run_key` | `INTEGER` | Yes | FK → `dim_pay_run.pay_run_key`. Self-reference to the original pay run being corrected. NULL for non-adjustment runs. |

---

### dim_pay_category

Pay category reference. Static — no SCD2.

**Grain:** One row per pay category.

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `pay_category_key` | `INTEGER` | No | Surrogate key (PK). |
| `pay_category_code` | `VARCHAR(50)` | No | Business code. |
| `pay_category_name` | `VARCHAR(200)` | No | Display name (e.g. `Base Salary`, `Overtime`, `Tax Withholding`). |
| `pay_category_type` | `VARCHAR(30)` | No | Type: `earning`, `deduction`, `allowance`, `employer_contribution`, `tax`. |
| `pay_category_group` | `VARCHAR(50)` | Yes | Higher-level grouping for reporting (e.g. `Gross Pay`, `Statutory Deductions`). |

---

### dim_leave_type

Leave category reference. Static — no SCD2.

**Grain:** One row per leave type.

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `leave_type_key` | `INTEGER` | No | Surrogate key (PK). |
| `leave_type_code` | `VARCHAR(50)` | No | Business code. |
| `leave_type_name` | `VARCHAR(200)` | No | Display name (e.g. `Annual Leave`, `Sick Leave`, `Parental Leave`). |
| `leave_category` | `VARCHAR(50)` | No | Category: `statutory`, `contractual`, `discretionary`. |
| `is_paid_flag` | `BOOLEAN` | No | `TRUE` if paid leave. |

---

### dim_shift_type

Shift definitions for rostering. Static — no SCD2.

**Grain:** One row per shift type.

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `shift_type_key` | `INTEGER` | No | Surrogate key (PK). |
| `shift_type_code` | `VARCHAR(50)` | No | Business code. |
| `shift_type_name` | `VARCHAR(200)` | No | Display name (e.g. `Day Shift`, `Night Shift`, `Split Shift`). |
| `standard_hours_quantity` | `DECIMAL(5,2)` | No | Standard hours for this shift type. |
| `planned_start_time` | `TIME` | No | Planned start time. |
| `planned_end_time` | `TIME` | No | Planned end time. |
| `break_duration_minutes` | `DECIMAL(5,2)` | No | Standard break duration in minutes. |

---

## Fact Tables

### fact_payslip_line

Individual earnings/deduction lines from payroll processing.

**Grain:** One row per employee × pay run × pay category. Each line represents a single earnings, deduction, or contribution item on a payslip.

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `payslip_line_key` | `INTEGER` | No | Surrogate key (PK). |
| `employee_key` | `INTEGER` | No | FK → `dim_employee.employee_key`. Points to the SCD2 version active at time of pay run. |
| `pay_run_key` | `INTEGER` | No | FK → `dim_pay_run.pay_run_key`. The pay run this line belongs to. |
| `pay_category_key` | `INTEGER` | No | FK → `dim_pay_category.pay_category_key`. The earnings/deduction type. |
| `organisation_key` | `INTEGER` | No | FK → `dim_organisation.organisation_key`. Org unit the cost is charged to. |
| `calendar_date` | `DATE` | No | FK → `dim_calendar.calendar_date`. Payment date (aligns to `dim_pay_run.payment_date`). |
| `gross_amount` | `DECIMAL(18,2)` | No | Gross amount for this line. Positive for earnings, negative for deductions. |
| `net_amount` | `DECIMAL(18,2)` | No | Net amount after applicable withholdings for this line. |
| `units_quantity` | `DECIMAL(10,2)` | Yes | Units (e.g. hours, days) associated with this line. NULL for fixed amounts. |
| `rate_amount` | `DECIMAL(18,4)` | Yes | Rate applied (e.g. hourly rate). NULL for fixed amounts or percentages. |

---

### fact_salary_assignment

Contracted/agreed pay rates and salary history. Enables variance analysis between what was *agreed* (this table) and what was *paid* (`fact_payslip_line`).

**Grain:** One row per employee × effective date range. A new row is created when the contracted salary or rate changes.

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `salary_assignment_key` | `INTEGER` | No | Surrogate key (PK). |
| `employee_key` | `INTEGER` | No | FK → `dim_employee.employee_key`. |
| `job_key` | `INTEGER` | No | FK → `dim_job.job_key`. The job the salary relates to. |
| `organisation_key` | `INTEGER` | No | FK → `dim_organisation.organisation_key`. |
| `salary_basis` | `VARCHAR(20)` | No | Basis: `annual`, `hourly`, `daily`, `per_unit`. |
| `annual_salary_amount` | `DECIMAL(18,2)` | Yes | Annualised salary. NULL if hourly/daily basis. |
| `hourly_rate_amount` | `DECIMAL(18,4)` | Yes | Hourly rate. NULL if annual basis. |
| `currency_code` | `VARCHAR(3)` | No | ISO 4217 currency code (e.g. `AUD`, `USD`). |
| `fte_ratio` | `DECIMAL(5,4)` | No | Full-time equivalent ratio (e.g. `1.0000` = full-time, `0.6000` = 3 days/week). |
| `effective_from_date` | `DATE` | No | Start date of this salary arrangement. |
| `effective_to_date` | `DATE` | No | End date. `9999-12-31` for current. |
| `is_current_flag` | `BOOLEAN` | No | `TRUE` for the active salary arrangement. |
| `change_reason` | `VARCHAR(100)` | Yes | Reason for change: `new_hire`, `promotion`, `annual_review`, `reclassification`, `transfer`. |

---

### fact_leave_record

Leave requests, approvals, and balances.

**Grain:** One row per leave request/booking.

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `leave_record_key` | `INTEGER` | No | Surrogate key (PK). |
| `employee_key` | `INTEGER` | No | FK → `dim_employee.employee_key`. |
| `leave_type_key` | `INTEGER` | No | FK → `dim_leave_type.leave_type_key`. |
| `organisation_key` | `INTEGER` | No | FK → `dim_organisation.organisation_key`. |
| `start_date` | `DATE` | No | FK → `dim_calendar.calendar_date`. First day of leave. |
| `end_date` | `DATE` | No | Last day of leave. |
| `hours_quantity` | `DECIMAL(10,2)` | No | Total leave hours. |
| `days_quantity` | `DECIMAL(10,2)` | No | Total leave days. |
| `approval_status` | `VARCHAR(30)` | No | Status: `pending`, `approved`, `rejected`, `cancelled`. |
| `balance_quantity` | `DECIMAL(10,2)` | Yes | Leave balance remaining after this record. NULL if not tracked at this layer. |

---

### fact_timesheet_entry

Submitted time entries.

**Grain:** One row per employee × date × project/task combination.

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `timesheet_entry_key` | `INTEGER` | No | Surrogate key (PK). |
| `employee_key` | `INTEGER` | No | FK → `dim_employee.employee_key`. |
| `organisation_key` | `INTEGER` | No | FK → `dim_organisation.organisation_key`. Cost centre charged. |
| `calendar_date` | `DATE` | No | FK → `dim_calendar.calendar_date`. The date worked. |
| `project_code` | `VARCHAR(50)` | Yes | Degenerate dimension: project code. NULL if not project-based. |
| `task_code` | `VARCHAR(50)` | Yes | Degenerate dimension: task/activity code within a project. |
| `hours_quantity` | `DECIMAL(10,2)` | No | Hours worked. |
| `approval_status` | `VARCHAR(30)` | No | Status: `draft`, `submitted`, `approved`, `rejected`. |
| `entry_type` | `VARCHAR(30)` | No | Type: `standard`, `overtime`, `on_call`, `training`, `travel`. |

---

### fact_roster_assignment

Planned and actual shift assignments.

**Grain:** One row per employee × date × shift. Captures both the planned roster and actual attendance.

| Column | Data Type | Nullable | Description |
|---|---|---|---|
| `roster_assignment_key` | `INTEGER` | No | Surrogate key (PK). |
| `employee_key` | `INTEGER` | No | FK → `dim_employee.employee_key`. |
| `shift_type_key` | `INTEGER` | No | FK → `dim_shift_type.shift_type_key`. |
| `organisation_key` | `INTEGER` | No | FK → `dim_organisation.organisation_key`. |
| `location_key` | `INTEGER` | No | FK → `dim_location.location_key`. Physical work location. |
| `calendar_date` | `DATE` | No | FK → `dim_calendar.calendar_date`. The rostered date. |
| `actual_start_time` | `TIME` | Yes | Actual clock-in time. NULL if not yet worked or no-show. |
| `actual_end_time` | `TIME` | Yes | Actual clock-out time. NULL if not yet worked or no-show. |
| `actual_hours_quantity` | `DECIMAL(10,2)` | Yes | Actual hours worked. NULL if not yet worked. |
| `roster_status` | `VARCHAR(30)` | No | Status: `planned`, `confirmed`, `worked`, `no_show`, `cancelled`. |
