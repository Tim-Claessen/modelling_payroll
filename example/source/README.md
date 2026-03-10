# SAP Source Data — Mapping to Payroll Data Model

This directory contains the SAP HCM/HR source tables required to feed the payroll semantic data model. Schemas are based on the standard SAP PA (Personnel Administration) and PT (Time Management) infotype tables.

---

## Source System Assumptions

- **SAP HCM (ECC or S/4HANA)** — Standard PA infotype tables for master data, PT infotype tables for time management
- **Wage Type Reporter** — Assumed available as a pre-built report/extract. This provides the payroll results (earnings, deductions, allowances per employee per pay period) and maps directly to `fact_payslip_line` in the semantic model. We do not need to rebuild wage type aggregation from the payroll cluster (PCL2).

---

## Source Tables

| SAP Table | Infotype | Description | Feeds Target |
|---|---|---|---|
| `PA0000` | IT0000 | Actions (hire, terminate, status changes) | `dim_employee` (employment_status, hire/termination events) |
| `PA0001` | IT0001 | Organisational Assignment | `dim_employee`, `dim_organisation`, `dim_job` |
| `PA0002` | IT0002 | Personal Data | `dim_employee` (name, DOB, gender) |
| `PA0006` | IT0006 | Home Addresses (personal data) | Not directly mapped — work location comes from `WERKS`/`BTRTL` on PA0001 |
| `PA0007` | IT0007 | Planned Working Time | `dim_shift_type` (work schedule template; not individual shift records) |
| `PA0008` | IT0008 | Basic Pay | `fact_salary_assignment` |
| `PA0009` | IT0009 | Bank Details | `dim_bank_account` |
| `PA2001` | IT2001 | Absences | `fact_leave_record` |
| `PA2002` | IT2002 | Attendances | `fact_timesheet_entry` |
| `PA2007` | IT2007 | Attendance Quotas (Leave Balances) | `fact_leave_record` (balance_quantity) |
| — | Wage Type Report | Payroll results by wage type | `fact_payslip_line`, `dim_pay_category`, `dim_pay_run` |

### Tables Not Required (Covered by Wage Type Report)

The Wage Type Report consolidates payroll results from the payroll cluster tables (PCL1/PCL2). This means we do **not** need to extract from:

- `PCL2` (Payroll cluster) — complex binary cluster, difficult to extract directly
- `PA0014` (Recurring Payments/Deductions) — wage type report includes these in results
- `PA0015` (Additional Payments) — included in wage type report output

---

## Common Infotype Key Fields

All PA infotype tables share a common key structure:

| Field | Type | Length | Description |
|---|---|---|---|
| `MANDT` | CLNT | 3 | SAP Client |
| `PERNR` | NUMC | 8 | Personnel Number (employee identifier) |
| `SUBTY` | CHAR | 4 | Subtype |
| `OBJPS` | CHAR | 2 | Object Identification |
| `SPRPS` | CHAR | 1 | Lock Indicator |
| `ENDDA` | DATS | 8 | End Date (validity period end) |
| `BEGDA` | DATS | 8 | Start Date (validity period start) |
| `SEQNR` | NUMC | 3 | Sequence number (for records with same key) |

These fields support SAP's time-constraint model — equivalent to SCD2 in our semantic layer. `BEGDA`/`ENDDA` define the validity period; `SEQNR` handles multiple records with the same key within the same period.

---

## Entity-Relationship Diagram

See [`source-model.mermaid`](source-model.mermaid) — renders natively on GitHub.

## Example Datasets

See the `examples/` directory for small sample datasets in CSV format, one per source table, using the exact SAP schema.

---

## Reference

Full SAP table schemas and field documentation available at:

- **[sapdatasheet.org](https://www.sapdatasheet.org/abap/tabl/)** — authoritative SAP table reference
  - [PA0000](https://www.sapdatasheet.org/abap/tabl/pa0000.html) — Actions
  - [PA0001](https://www.sapdatasheet.org/abap/tabl/pa0001.html) — Organisational Assignment
  - [PA0002](https://www.sapdatasheet.org/abap/tabl/pa0002.html) — Personal Data
  - [PA0006](https://www.sapdatasheet.org/abap/tabl/pa0006.html) — Addresses
  - [PA0007](https://www.sapdatasheet.org/abap/tabl/pa0007.html) — Planned Working Time
  - [PA0008](https://www.sapdatasheet.org/abap/tabl/pa0008.html) — Basic Pay
  - [PA0009](https://www.sapdatasheet.org/abap/tabl/pa0009.html) — Bank Details
  - [PA2001](https://www.sapdatasheet.org/abap/tabl/pa2001.html) — Absences
  - [PA2002](https://www.sapdatasheet.org/abap/tabl/pa2002.html) — Attendances
  - [PA2007](https://www.sapdatasheet.org/abap/tabl/pa2007.html) — Attendance Quotas

---

## Mapping Notes

### SAP → Semantic Model Key Concepts

| SAP Concept | Semantic Model Equivalent |
|---|---|
| `PERNR` (Personnel Number) | `employee_code` on `dim_employee` |
| `BEGDA` / `ENDDA` (Validity Period) | `effective_from_date` / `effective_to_date` (SCD2) |
| `BUKRS` (Company Code) | `legal_entity_name` on `dim_organisation` |
| `WERKS` (Personnel Area) | Maps to `dim_location` or `dim_organisation` depending on config |
| `BTRTL` (Personnel Subarea) | Subdivision of Personnel Area — maps to `dim_location` |
| `ORGEH` (Org Unit) | `organisation_code` on `dim_organisation` |
| `PLANS` (Position) | Future state: `dim_position` |
| `STELL` (Job Key) | `job_code` on `dim_job` |
| `KOSTL` (Cost Center) | `cost_centre_code` (degenerate dim on fact tables) |
| `ABKRS` (Payroll Area) | `pay_frequency` on `dim_pay_run` |
| `LGART` (Wage Type) | `pay_category_code` on `dim_pay_category` |
| `AWART` (Absence Type) | `leave_type_code` on `dim_leave_type` |
