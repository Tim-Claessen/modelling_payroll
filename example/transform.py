#!/usr/bin/env python3
"""
transform.py — SAP source data → payroll semantic model

Reads:  example/source/*.csv
Writes: example/modelled/*.csv  (one file per target table)

Run from the repo root:
    python example/transform.py

Surrogate key strategy: MD5 hash of natural key components, truncated to a
positive 32-bit integer. Deterministic — the same inputs always produce the
same key, so re-runs are safe and foreign keys stay consistent across tables.

Tables NOT populated (no source data available):
  - fact_roster_assignment : PA0007 gives schedule templates, not dated shifts
  - dim_public_holiday      : no holiday data in source
"""

import csv
import hashlib
from datetime import date, timedelta
from pathlib import Path


# ─── Paths ────────────────────────────────────────────────────────────────────

BASE   = Path(__file__).parent          # example/
SOURCE = BASE / "source"
OUT    = BASE / "modelled"
OUT.mkdir(exist_ok=True)


# ─── Constants ────────────────────────────────────────────────────────────────

SAP_MAX_DATE = "99991231"               # SAP's "no end date" sentinel value


# ─── Helpers ──────────────────────────────────────────────────────────────────

def sap_date(d):
    """
    Convert a SAP DATS field (YYYYMMDD string) to ISO format (YYYY-MM-DD).
    SAP's max date 99991231 becomes the model's convention 9999-12-31.
    Returns None for blank/null fields.
    """
    if not d or not d.strip():
        return None
    if d == SAP_MAX_DATE:
        return "9999-12-31"
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def surrogate_key(*parts):
    """
    Generate a stable integer surrogate key from any number of natural-key parts.

    Joins the parts with '|', hashes with MD5, and returns the first 8 hex
    digits as a positive integer (~4 billion possible values — plenty for samples).

    Why MD5 + truncate? It's fast, built-in, and deterministic. We're not
    using it for security — purely for stable ID generation.

    Example:
        surrogate_key("employee", "00001001", "20230115")
        surrogate_key("pay_run",  "AB", "20240301", "20240331", "S")
    """
    raw = "|".join(str(p) for p in parts)
    return int(hashlib.md5(raw.encode()).hexdigest()[:8], 16)


def read(filename):
    """Read a source CSV and return a list of row dicts."""
    with open(SOURCE / filename, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(filename, rows, fieldnames):
    """Write a list of row dicts to a modelled output CSV."""
    path = OUT / filename
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {len(rows):>3} rows  ->  {filename}")


# ─── Load all source tables ───────────────────────────────────────────────────

print("\nLoading source tables...")
pa0000 = read("PA0000.csv")    # Actions          (hire, terminate, status changes)
pa0001 = read("PA0001.csv")    # Org Assignment   (SCD2 driver for dim_employee)
pa0002 = read("PA0002.csv")    # Personal Data    (name, DOB, gender)
pa0006 = read("PA0006.csv")    # Home Addresses   (not used — work location comes from PA0001)
pa0007 = read("PA0007.csv")    # Working Time     (schedule rules → dim_shift_type)
pa0008 = read("PA0008.csv")    # Basic Pay        (salary assignments)
pa0009 = read("PA0009.csv")    # Bank Details     (bank accounts)
pa2001 = read("PA2001.csv")    # Absences         (leave records)
pa2002 = read("PA2002.csv")    # Attendances      (timesheet entries)
pa2007 = read("PA2007.csv")    # Leave Quotas     (leave balances)
wtr    = read("WAGE_TYPE_REPORT.csv")

print(f"\nBuilding modelled tables...\n")


# ─────────────────────────────────────────────────────────────────────────────
# REFERENCE TABLES (dimensions)
# ─────────────────────────────────────────────────────────────────────────────

# ─── dim_calendar ─────────────────────────────────────────────────────────────
# Generate one row per calendar date covering the full range of source data.
# Fiscal year = calendar year (simple assumption — adjust if org uses a
# non-calendar fiscal year, e.g. July–June).

calendar_rows = []
start = date(2022, 1, 1)
end   = date(2025, 12, 31)
d = start
while d <= end:
    calendar_rows.append({
        "calendar_date":         d.isoformat(),
        "day_of_week":           d.isoweekday(),          # ISO: 1=Monday, 7=Sunday
        "day_name":              d.strftime("%A"),
        "week_of_year":          d.isocalendar()[1],
        "calendar_month":        d.month,
        "calendar_year":         d.year,
        "fiscal_month":          d.month,                  # Same as calendar month here
        "fiscal_year":           d.year,
        "fiscal_period_name":    f"FY{str(d.year)[2:]}-M{str(d.month).zfill(2)}",
        "pay_period_identifier": None,                     # Not derived in this pass
    })
    d += timedelta(days=1)

write("dim_calendar.csv", calendar_rows, [
    "calendar_date", "day_of_week", "day_name", "week_of_year",
    "calendar_month", "calendar_year", "fiscal_month", "fiscal_year",
    "fiscal_period_name", "pay_period_identifier",
])


# ─── dim_organisation ─────────────────────────────────────────────────────────
# Derived from PA0001.
# In a real system you'd load from SAP's org management tables (HRP1000/HRP1001)
# which carry full hierarchy and descriptions. Here we derive what we can:
#   - BUKRS (company code) → root-level legal entity rows
#   - ORGEH (org unit)     → department rows, parented to their BUKRS
# Names are constructed from codes since we have no description table.
# One row per unique ORGEH — no SCD2 versioning at this level (no source history).

org_rows = {}

# Step 1: add company codes as root-level legal entities
for row in pa0001:
    bukrs = row["BUKRS"]
    key   = surrogate_key("org", bukrs)
    if key not in org_rows:
        org_rows[key] = {
            "organisation_key":         key,
            "organisation_code":        bukrs,
            "organisation_name":        f"Company {bukrs}",
            "organisation_type":        "legal_entity",
            "cost_centre_code":         None,
            "cost_centre_name":         None,
            "department_name":          None,
            "business_unit_name":       None,
            "legal_entity_name":        f"Company {bukrs}",
            "parent_organisation_code": None,              # Root — no parent
            "effective_from_date":      "2022-01-01",
            "effective_to_date":        "9999-12-31",
            "is_current_flag":          True,
        }

# Step 2: add org units (ORGEH) as children of their company code
for row in pa0001:
    orgeh = row["ORGEH"]
    bukrs = row["BUKRS"]
    kostl = row["KOSTL"]
    key   = surrogate_key("org", orgeh)
    if key not in org_rows:
        org_rows[key] = {
            "organisation_key":         key,
            "organisation_code":        orgeh,
            "organisation_name":        f"Org Unit {orgeh}",
            "organisation_type":        "department",
            "cost_centre_code":         kostl,
            "cost_centre_name":         f"Cost Centre {kostl}",
            "department_name":          f"Org Unit {orgeh}",
            "business_unit_name":       None,
            "legal_entity_name":        f"Company {bukrs}",
            "parent_organisation_code": bukrs,             # Stable code reference to parent
            "effective_from_date":      "2022-01-01",
            "effective_to_date":        "9999-12-31",
            "is_current_flag":          True,
        }

write("dim_organisation.csv", list(org_rows.values()), [
    "organisation_key", "organisation_code", "organisation_name", "organisation_type",
    "cost_centre_code", "cost_centre_name", "department_name", "business_unit_name",
    "legal_entity_name", "parent_organisation_code",
    "effective_from_date", "effective_to_date", "is_current_flag",
])


# ─── dim_job ──────────────────────────────────────────────────────────────────
# Derived from PA0001.STELL (job key) and PERSK (employee subgroup → classification).
# In a real system you'd load from SAP's T513S table for job descriptions.
# One row per unique STELL — no SCD2 versioning here.

PERSK_LABEL = {
    "DK": "Full-time employee",
    "SK": "Part-time employee",
}

job_rows = {}
for row in pa0001:
    stell = row["STELL"]
    persk = row["PERSK"]
    key   = surrogate_key("job", stell)
    if key not in job_rows:
        job_rows[key] = {
            "job_key":             key,
            "job_code":            stell,
            "job_title":           f"Job {stell}",         # No description table in source
            "job_classification":  PERSK_LABEL.get(persk, persk),
            "job_band":            None,
            "job_grade":           None,
            "job_family":          None,
            "effective_from_date": "2022-01-01",
            "effective_to_date":   "9999-12-31",
            "is_current_flag":     True,
        }

write("dim_job.csv", list(job_rows.values()), [
    "job_key", "job_code", "job_title", "job_classification",
    "job_band", "job_grade", "job_family",
    "effective_from_date", "effective_to_date", "is_current_flag",
])


# ─── dim_location ─────────────────────────────────────────────────────────────
# Work location comes from PA0001.WERKS (Personnel Area) + BTRTL (Personnel Subarea).
# Note: PA0006 is the employee's home address — not used here.
# Location code = "WERKS-BTRTL" (e.g. "1100-1110").
# City/state hard-coded based on known WERKS values in this dataset.
# In a real system you'd load from SAP's T500P and T001P tables.

WERKS_GEO = {
    # WERKS : city, state, country
    "1100": ("Perth",     "WA",  "Australia"),
    "1200": ("Perth",     "WA",  "Australia"),
    "2100": ("Melbourne", "VIC", "Australia"),
}

location_rows = {}
for row in pa0001:
    werks = row["WERKS"]
    btrtl = row["BTRTL"]
    code  = f"{werks}-{btrtl}"
    key   = surrogate_key("location", code)
    if key not in location_rows:
        city, state, country = WERKS_GEO.get(werks, ("Unknown", None, "Australia"))
        location_rows[key] = {
            "location_key":        key,
            "location_code":       code,
            "location_name":       f"Site {btrtl}",
            "site_name":           f"Site {btrtl}",
            "city":                city,
            "state_province":      state,
            "country":             country,
            "region":              state,
            "effective_from_date": "2022-01-01",
            "effective_to_date":   "9999-12-31",
            "is_current_flag":     True,
        }

write("dim_location.csv", list(location_rows.values()), [
    "location_key", "location_code", "location_name", "site_name",
    "city", "state_province", "country", "region",
    "effective_from_date", "effective_to_date", "is_current_flag",
])


# ─── dim_employee ─────────────────────────────────────────────────────────────
# PA0001 drives SCD2 history — one row per PA0001 record (PERNR × validity period).
# Joined with PA0002 (personal data) and PA0000 (for hire/termination dates).
#
# Surrogate key: hash(PERNR, BEGDA) — unique per person × version.
# All fact table FKs must use this same formula to find the right version.
#
# Employment status derived from PA0000.STAT2 on the most recent action
# at or before the start of each PA0001 version.

# Index PA0002 by PERNR (one personal data record per employee)
pa0002_by_pernr = {r["PERNR"]: r for r in pa0002}

# Index PA0007 by PERNR for employment percentage (used to derive employment_type)
pa0007_by_pernr = {r["PERNR"]: r for r in pa0007}

# Derive hire date (earliest MASSN=01 action) and termination date (MASSN=07) from PA0000
hire_dates = {}
term_dates = {}
for row in sorted(pa0000, key=lambda r: r["BEGDA"]):
    pernr = row["PERNR"]
    if row["MASSN"] == "01" and pernr not in hire_dates:
        hire_dates[pernr] = row["BEGDA"]
    if row["MASSN"] == "07":
        term_dates[pernr] = row["BEGDA"]

# SAP STAT2 → semantic model employment_status
STAT2_MAP = {"3": "active", "0": "terminated", "1": "on_leave", "2": "suspended"}

# Derive employment_type from PA0007.EMPCT (employment percentage)
def employment_type(pernr):
    empct = float(pa0007_by_pernr.get(pernr, {}).get("EMPCT", "100") or "100")
    return "full_time" if empct >= 100 else "part_time"

employee_rows = []
for row in pa0001:
    pernr = row["PERNR"]
    begda = row["BEGDA"]
    endda = row["ENDDA"]
    p2    = pa0002_by_pernr.get(pernr, {})

    # Find the most recent PA0000 action covering this PA0001 version's start date
    stat2 = "3"   # default: active
    for action in sorted(pa0000, key=lambda r: r["BEGDA"]):
        if action["PERNR"] == pernr and action["BEGDA"] <= begda:
            stat2 = action["STAT2"]

    # FK keys — must use the same surrogate_key formula as the target tables above
    emp_key = surrogate_key("employee", pernr, begda)
    job_key = surrogate_key("job",      row["STELL"])
    org_key = surrogate_key("org",      row["ORGEH"])
    loc_key = surrogate_key("location", f"{row['WERKS']}-{row['BTRTL']}")

    employee_rows.append({
        "employee_key":        emp_key,
        "employee_code":       pernr,
        "first_name":          p2.get("VORNA", ""),
        "last_name":           p2.get("NACHN", ""),
        "date_of_birth":       sap_date(p2.get("GBDAT", "")),
        "gender":              {"1": "Male", "2": "Female"}.get(p2.get("GESCH", ""), None),
        "employment_status":   STAT2_MAP.get(stat2, "active"),
        "employment_type":     employment_type(pernr),
        "hire_date":           sap_date(hire_dates.get(pernr, begda)),
        "termination_date":    sap_date(term_dates[pernr]) if pernr in term_dates else None,
        "job_key":             job_key,
        "organisation_key":    org_key,
        "location_key":        loc_key,
        "effective_from_date": sap_date(begda),
        "effective_to_date":   sap_date(endda),
        "is_current_flag":     endda == SAP_MAX_DATE,
    })

write("dim_employee.csv", employee_rows, [
    "employee_key", "employee_code", "first_name", "last_name",
    "date_of_birth", "gender", "employment_status", "employment_type",
    "hire_date", "termination_date",
    "job_key", "organisation_key", "location_key",
    "effective_from_date", "effective_to_date", "is_current_flag",
])


# ─── dim_bank_account ─────────────────────────────────────────────────────────
# Directly from PA0009. SUBTY=0 = primary account; SUBTY=1 = secondary account.
# BETRG on secondary accounts is a fixed payment amount (not a percentage);
# BETRG=0 on the primary means "receive the remainder of net pay".
# employee_key points to the current version of the employee record.

# Build a quick lookup: PERNR → employee_key of the current version
current_emp_key = {
    row["PERNR"]: surrogate_key("employee", row["PERNR"], row["BEGDA"])
    for row in pa0001
    if row["ENDDA"] == SAP_MAX_DATE
}

bank_rows = []
for row in pa0009:
    pernr = row["PERNR"]
    bank_rows.append({
        "bank_account_key":      surrogate_key("bank", pernr, row["SUBTY"], row["BEGDA"]),
        "employee_key":          current_emp_key.get(pernr),
        "bank_name":             f"Bank {row['BANKL'].split('-')[0]}",  # BSB prefix as bank name
        "bsb_code":              row["BANKL"],
        "account_number_masked": row["BANKN"],
        "account_name":          row["EMFTX"],
        "account_type":          "savings",             # Not in source — default
        "is_primary_flag":       row["SUBTY"] == "0",
        "valid_from_date":       sap_date(row["BEGDA"]),
        "valid_to_date":         sap_date(row["ENDDA"]),
        "is_current_flag":       row["ENDDA"] == SAP_MAX_DATE,
    })

write("dim_bank_account.csv", bank_rows, [
    "bank_account_key", "employee_key", "bank_name", "bsb_code",
    "account_number_masked", "account_name", "account_type",
    "is_primary_flag", "valid_from_date", "valid_to_date", "is_current_flag",
])


# ─── dim_pay_category ─────────────────────────────────────────────────────────
# Unique wage types from WAGE_TYPE_REPORT.
# pay_category_type inferred from LGART code range (standard SAP AU convention):
#   1000–1999 = earnings
#   3000–3499 = tax
#   3500–3999 = employer contributions (e.g. superannuation)
# Hard-code group labels to match the pay_category_group convention.

def pay_cat_type(lgart):
    n = int(lgart) if lgart.isdigit() else 9999
    if 1000 <= n <= 1999: return "earning"
    if 3000 <= n <= 3499: return "tax"
    if 3500 <= n <= 3999: return "employer_contribution"
    return "deduction"

GROUP_LABEL = {
    "earning":              "Gross Pay",
    "tax":                  "Statutory Deductions",
    "employer_contribution":"Employer Costs",
    "deduction":            "Deductions",
}

pay_cat_rows = {}
for row in wtr:
    lgart = row["LGART"]
    key   = surrogate_key("pay_category", lgart)
    if key not in pay_cat_rows:
        cat_type = pay_cat_type(lgart)
        pay_cat_rows[key] = {
            "pay_category_key":   key,
            "pay_category_code":  lgart,
            "pay_category_name":  row["LGTXT"],
            "pay_category_type":  cat_type,
            "pay_category_group": GROUP_LABEL.get(cat_type),
        }

write("dim_pay_category.csv", list(pay_cat_rows.values()), [
    "pay_category_key", "pay_category_code", "pay_category_name",
    "pay_category_type", "pay_category_group",
])


# ─── dim_pay_run ──────────────────────────────────────────────────────────────
# A pay run is a unique combination of payroll area + for period + in period + type.
# Multiple employees share the same pay run — PERNR is NOT part of the identity.
#
# adjusted_pay_run_key: for back-pay runs (PAYTY=B), link to the scheduled run
# that covers the same for-period. Simplified: find a matching S run for the same
# ABKRS and for-period dates.

PAYTY_MAP  = {"S": "scheduled", "B": "back_pay", "O": "off_cycle", "C": "correction"}
ABKRS_FREQ = {"AB": "monthly", "MN": "monthly"}

# First pass: collect all pay runs
pay_run_rows = {}
for row in wtr:
    key = surrogate_key("pay_run", row["ABKRS"], row["FPPER_BEG"], row["FPPER_END"],
                        row["IPPER_BEG"], row["IPPER_END"], row["PAYTY"])
    if key not in pay_run_rows:
        pay_run_rows[key] = {
            "pay_run_key":           key,
            "pay_run_code":          f"{row['ABKRS']}-{row['FPPER_BEG']}-{row['PAYTY']}",
            "pay_frequency":         ABKRS_FREQ.get(row["ABKRS"], "monthly"),
            "pay_run_type":          PAYTY_MAP.get(row["PAYTY"], "scheduled"),
            "for_period_start_date": sap_date(row["FPPER_BEG"]),
            "for_period_end_date":   sap_date(row["FPPER_END"]),
            "in_period_start_date":  sap_date(row["IPPER_BEG"]),
            "in_period_end_date":    sap_date(row["IPPER_END"]),
            "payment_date":          sap_date(row["PAYDT"]),
            "pay_run_status":        "completed",          # All historical runs are completed
            "adjusted_pay_run_key":  None,                 # Populated in second pass below
            "_abkrs":                row["ABKRS"],         # Temp — removed before writing
            "_fpper_beg":            row["FPPER_BEG"],
            "_fpper_end":            row["FPPER_END"],
            "_payty":                row["PAYTY"],
        }

# Second pass: link back-pay runs to their original scheduled run
for key, run in pay_run_rows.items():
    if run["_payty"] == "B":
        # Find the scheduled (S) run for the same payroll area and for-period
        original_key = surrogate_key(
            "pay_run", run["_abkrs"], run["_fpper_beg"], run["_fpper_end"],
            run["_fpper_beg"], run["_fpper_end"],    # For scheduled runs, for=in period
            "S"
        )
        if original_key in pay_run_rows:
            run["adjusted_pay_run_key"] = original_key

# Remove temp fields before writing
for run in pay_run_rows.values():
    for f in ("_abkrs", "_fpper_beg", "_fpper_end", "_payty"):
        run.pop(f, None)

write("dim_pay_run.csv", list(pay_run_rows.values()), [
    "pay_run_key", "pay_run_code", "pay_frequency", "pay_run_type",
    "for_period_start_date", "for_period_end_date",
    "in_period_start_date", "in_period_end_date",
    "payment_date", "pay_run_status", "adjusted_pay_run_key",
])


# ─── dim_leave_type ───────────────────────────────────────────────────────────
# Derived from unique AWART codes in PA2001.
# In a real system you'd load descriptions from SAP's T554S table.
# Hard-coded names and categories for the AWART codes in this dataset.

AWART_META = {
    "0100": {"name": "Annual Leave",   "category": "statutory",    "is_paid": True},
    "0200": {"name": "Sick Leave",     "category": "statutory",    "is_paid": True},
    "0400": {"name": "Parental Leave", "category": "statutory",    "is_paid": False},
}

leave_type_rows = {}
for row in pa2001:
    awart = row["AWART"]
    key   = surrogate_key("leave_type", awart)
    if key not in leave_type_rows:
        meta = AWART_META.get(awart, {
            "name":     f"Leave Type {awart}",
            "category": "discretionary",
            "is_paid":  False,
        })
        leave_type_rows[key] = {
            "leave_type_key":  key,
            "leave_type_code": awart,
            "leave_type_name": meta["name"],
            "leave_category":  meta["category"],
            "is_paid_flag":    meta["is_paid"],
        }

write("dim_leave_type.csv", list(leave_type_rows.values()), [
    "leave_type_key", "leave_type_code", "leave_type_name",
    "leave_category", "is_paid_flag",
])


# ─── dim_shift_type ───────────────────────────────────────────────────────────
# Derived from PA0007 (planned working time / work schedule rules).
# PA0007.SCHKZ = work schedule key → the shift type code.
# Standard hours come from ARBST (daily hours).
# Start/end times are not in PA0007 — hard-coded to standard office hours.

shift_type_rows = {}
for row in pa0007:
    schkz = row["SCHKZ"]
    key   = surrogate_key("shift_type", schkz)
    if key not in shift_type_rows:
        shift_type_rows[key] = {
            "shift_type_key":          key,
            "shift_type_code":         schkz,
            "shift_type_name":         {"NORM": "Normal Day Shift", "PART": "Part-time Shift"}.get(schkz, f"Shift {schkz}"),
            "standard_hours_quantity": float(row["ARBST"] or 0),
            "planned_start_time":      "08:00:00",         # Not in source — standard office default
            "planned_end_time":        "16:00:00",
            "break_duration_minutes":  30,
        }

write("dim_shift_type.csv", list(shift_type_rows.values()), [
    "shift_type_key", "shift_type_code", "shift_type_name",
    "standard_hours_quantity", "planned_start_time", "planned_end_time",
    "break_duration_minutes",
])


# ─────────────────────────────────────────────────────────────────────────────
# FACT TABLES
# ─────────────────────────────────────────────────────────────────────────────

# ─── Shared helper: find employee version active on a given date ───────────────
# Used by all fact tables to resolve the correct SCD2 version of the employee.

def find_employee_key(pernr, target_date_iso):
    """
    Return the employee_key for the dim_employee version active on target_date_iso
    (ISO format: YYYY-MM-DD).

    Scans PA0001 for a record where:
        BEGDA (converted) <= target_date <= ENDDA (converted)

    Falls back to the most recent version if no exact match (shouldn't happen
    with clean data, but guards against edge cases).
    """
    for p1 in pa0001:
        if p1["PERNR"] != pernr:
            continue
        if sap_date(p1["BEGDA"]) <= target_date_iso <= sap_date(p1["ENDDA"]):
            return surrogate_key("employee", pernr, p1["BEGDA"])
    # Fallback: most recent version
    matches = [p1 for p1 in pa0001 if p1["PERNR"] == pernr]
    if matches:
        latest = max(matches, key=lambda r: r["BEGDA"])
        return surrogate_key("employee", pernr, latest["BEGDA"])
    return None


# ─── fact_salary_assignment ───────────────────────────────────────────────────
# One row per PA0008 record — each represents one salary arrangement period.
# employee_key: resolved by matching PERNR + BEGDA to the PA0001 version.
# job_key: from the PA0001 record for the same PERNR and BEGDA.
# change_reason: inferred from the PA0000 action on the same start date.

pa0001_by_pernr_begda = {(r["PERNR"], r["BEGDA"]): r for r in pa0001}

PA0000_REASON = {"01": "new_hire", "06": "promotion", "07": "transfer"}

pa0000_by_pernr_begda = {}
for row in pa0000:
    pa0000_by_pernr_begda[(row["PERNR"], row["BEGDA"])] = row

salary_rows = []
for row in pa0008:
    pernr   = row["PERNR"]
    begda   = row["BEGDA"]
    endda   = row["ENDDA"]
    ansal   = float(row["ANSAL"])
    divgv   = float(row.get("DIVGV") or 2080)    # Hours divisor for annual → hourly
    bsgrd   = float(row.get("BSGRD") or 100)

    # Resolve FKs
    emp_key = surrogate_key("employee", pernr, begda)
    p1      = pa0001_by_pernr_begda.get((pernr, begda), {})
    job_key = surrogate_key("job", p1.get("STELL", ""))

    # Infer change reason from PA0000 action on the same date
    action       = pa0000_by_pernr_begda.get((pernr, begda), {})
    change_reason = PA0000_REASON.get(action.get("MASSN"))

    salary_rows.append({
        "salary_assignment_key": surrogate_key("salary", pernr, begda),
        "employee_key":          emp_key,
        "job_key":               job_key,
        "salary_basis":          "annual",
        "annual_salary_amount":  ansal,
        "hourly_rate_amount":    round(ansal / divgv, 4),
        "currency_code":         row.get("WAERS", "AUD"),
        "fte_ratio":             round(bsgrd / 100, 4),
        "effective_from_date":   sap_date(begda),
        "effective_to_date":     sap_date(endda),
        "is_current_flag":       endda == SAP_MAX_DATE,
        "change_reason":         change_reason,
    })

write("fact_salary_assignment.csv", salary_rows, [
    "salary_assignment_key", "employee_key", "job_key", "salary_basis",
    "annual_salary_amount", "hourly_rate_amount", "currency_code", "fte_ratio",
    "effective_from_date", "effective_to_date", "is_current_flag", "change_reason",
])


# ─── fact_payslip_line ────────────────────────────────────────────────────────
# One row per WAGE_TYPE_REPORT record.
# amount is positive for earnings/employer contributions, negative for deductions/tax
# (the source already encodes this — e.g. PAYG Tax has a negative BETRG).
# employee_key: resolved to the version active on the payment date (PAYDT).

payslip_rows = []
for row in wtr:
    pernr  = row["PERNR"]
    paydt  = sap_date(row["PAYDT"])

    emp_key = find_employee_key(pernr, paydt)
    run_key = surrogate_key("pay_run", row["ABKRS"], row["FPPER_BEG"], row["FPPER_END"],
                            row["IPPER_BEG"], row["IPPER_END"], row["PAYTY"])
    cat_key = surrogate_key("pay_category", row["LGART"])

    # Payslip line natural key: person + run + wage type + cost centre
    line_key = surrogate_key("payslip_line", pernr, row["ABKRS"],
                             row["FPPER_BEG"], row["LGART"], row["KOSTL"])

    payslip_rows.append({
        "payslip_line_key": line_key,
        "employee_key":     emp_key,
        "pay_run_key":      run_key,
        "pay_category_key": cat_key,
        "calendar_date":    paydt,                         # Payment date = FK to dim_calendar
        "cost_centre_code": row["KOSTL"] or None,
        "amount":           float(row["BETRG"]),
        "units_quantity":   float(row["ANZHL"]) if row.get("ANZHL") else None,
        "rate_amount":      float(row["RATE"])  if row.get("RATE")  else None,
    })

write("fact_payslip_line.csv", payslip_rows, [
    "payslip_line_key", "employee_key", "pay_run_key", "pay_category_key",
    "calendar_date", "cost_centre_code", "amount", "units_quantity", "rate_amount",
])


# ─── fact_leave_record ────────────────────────────────────────────────────────
# From PA2001 (absence records). Each row = one leave request.
# balance_quantity: joined from PA2007 (leave quotas) where quota type matches
# the absence type. The balance represents remaining quota at the time of the record.
#
# AWART → KTART mapping: absence type code to quota type code.
# Simplified — in SAP these are separate configuration tables (T554S, T556A).

AWART_TO_KTART = {
    "0100": "01",   # Annual leave absence → annual leave quota
    "0200": "02",   # Sick leave absence → sick leave quota
    "0400": "01",   # Parental leave — no quota type; mapped to annual leave as approximation
}

pa2007_by_pernr_ktart = {(r["PERNR"], r["KTART"]): r for r in pa2007}

leave_rows = []
for row in pa2001:
    pernr = row["PERNR"]
    begda = row["BEGDA"]
    awart = row["AWART"]

    emp_key       = find_employee_key(pernr, sap_date(begda))
    leave_type_key = surrogate_key("leave_type", awart)

    # Look up the remaining quota balance from PA2007
    ktart   = AWART_TO_KTART.get(awart)
    quota   = pa2007_by_pernr_ktart.get((pernr, ktart), {})
    balance = float(quota["QUESTI"]) if quota.get("QUESTI") else None

    leave_rows.append({
        "leave_record_key": surrogate_key("leave_record", pernr, begda, awart),
        "employee_key":     emp_key,
        "leave_type_key":   leave_type_key,
        "start_date":       sap_date(begda),
        "end_date":         sap_date(row["ENDDA"]),
        "hours_quantity":   float(row["ABSSTD"] or 0),
        "days_quantity":    float(row["ABWTG"]  or 0),
        "approval_status":  "approved",                    # PA2001 = confirmed absences
        "balance_quantity": balance,
    })

write("fact_leave_record.csv", leave_rows, [
    "leave_record_key", "employee_key", "leave_type_key",
    "start_date", "end_date", "hours_quantity", "days_quantity",
    "approval_status", "balance_quantity",
])


# ─── fact_timesheet_entry ─────────────────────────────────────────────────────
# From PA2002 (attendance records). Each row = one confirmed attendance entry.
# entry_type: inferred from AWART (attendance type code).
# cost_centre_code: not available in PA2002 — would need project assignment data.

AWART_ENTRY_TYPE = {
    "0800": "overtime",
    "0810": "overtime",
    "0900": "training",
}

timesheet_rows = []
for row in pa2002:
    pernr = row["PERNR"]
    begda = row["BEGDA"]
    timesheet_rows.append({
        "timesheet_entry_key": surrogate_key("timesheet", pernr, begda, row["AWART"]),
        "employee_key":        find_employee_key(pernr, sap_date(begda)),
        "calendar_date":       sap_date(begda),
        "cost_centre_code":    None,                       # Not in PA2002
        "project_code":        None,                       # Not in PA2002
        "task_code":           None,                       # Not in PA2002
        "hours_quantity":      float(row["STDAZ"] or 0),
        "approval_status":     "approved",                 # PA2002 = confirmed attendances
        "entry_type":          AWART_ENTRY_TYPE.get(row["AWART"], "standard"),
    })

write("fact_timesheet_entry.csv", timesheet_rows, [
    "timesheet_entry_key", "employee_key", "calendar_date",
    "cost_centre_code", "project_code", "task_code",
    "hours_quantity", "approval_status", "entry_type",
])


# ─────────────────────────────────────────────────────────────────────────────
print("\nNot populated (no source data):")
print("  dim_public_holiday     - no holiday source file")
print("  fact_roster_assignment - PA0007 gives schedule rules, not dated shift records")
print(f"\nOutput: {OUT.resolve()}\n")
