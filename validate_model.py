#!/usr/bin/env python3
"""
validate_model.py — Structural integrity checks for the payroll data model.

Parses payroll_model.mermaid and validates:
  1. Every FK has a "Ref: <table>" comment pointing to a table that exists
  2. Every FK references a PK in the target table
  3. FK and PK data types match
  4. Every table has a primary key
  5. Every relationship references tables that exist
  6. Column naming conventions (_key, _code, _name, _date, _amount, _quantity, _flag)
  7. SCD2 completeness (effective_from_date, effective_to_date, is_current_flag)
  8. payroll_model.md sync: warns if tables or columns are out of step

Usage:
    python validate_model.py                       # defaults to payroll_model.mermaid
    python validate_model.py path/to/model.mermaid
"""

import re
import sys
from pathlib import Path
from dataclasses import dataclass, field


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class Column:
    name: str
    data_type: str
    is_pk: bool = False
    is_fk: bool = False
    fk_ref_table: str | None = None


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)

    def pk_columns(self):
        return [c for c in self.columns if c.is_pk]

    def fk_columns(self):
        return [c for c in self.columns if c.is_fk]


@dataclass
class Relationship:
    left_table: str
    right_table: str
    label: str
    raw_line: str


# ─── Parser ───────────────────────────────────────────────────────────────────

def parse_mermaid(filepath: Path) -> tuple[dict[str, Table], list[Relationship]]:
    """Parse an erDiagram mermaid file into tables and relationships."""
    text = filepath.read_text()
    tables: dict[str, Table] = {}
    relationships: list[Relationship] = []

    table_pattern = re.compile(r'((?:dim|fact)_\w+)\s*\{([^}]*)\}', re.DOTALL)
    col_pattern = re.compile(
        r'^\s*(\w+)\s+(\w+)(?:\s+(PK|FK))?(?:\s+"([^"]*)")?',
        re.MULTILINE
    )

    for table_match in table_pattern.finditer(text):
        table_name = table_match.group(1)
        table = Table(name=table_name)
        for col_match in col_pattern.finditer(table_match.group(2)):
            data_type, col_name = col_match.group(1), col_match.group(2)
            pk_fk = col_match.group(3) or ""
            comment = col_match.group(4) or ""
            ref = re.search(r'Ref:\s*(\w+)', comment)
            table.columns.append(Column(
                name=col_name,
                data_type=data_type,
                is_pk="PK" in pk_fk,
                is_fk="FK" in pk_fk,
                fk_ref_table=ref.group(1) if ref else None,
            ))
        tables[table_name] = table

    rel_pattern = re.compile(
        r'((?:dim|fact)_\w+)\s+[|}{o]+--[|}{o]+\s+((?:dim|fact)_\w+)\s*:\s*"([^"]*)"'
    )
    for m in rel_pattern.finditer(text):
        relationships.append(Relationship(m.group(1), m.group(2), m.group(3), m.group(0).strip()))

    return tables, relationships


# ─── Validators ───────────────────────────────────────────────────────────────

def validate_pk_exists(tables):
    return [
        f"[PK_MISSING] `{name}` has no primary key."
        for name, t in tables.items() if not t.pk_columns()
    ]


def validate_fk_refs(tables):
    """FK must have a Ref comment, and the referenced table must exist."""
    errors = []
    for name, table in tables.items():
        for col in table.fk_columns():
            if not col.fk_ref_table:
                errors.append(f"[FK_NO_REF] `{name}.{col.name}` is marked FK but has no \"Ref: <table>\" comment.")
            elif col.fk_ref_table not in tables:
                errors.append(f"[FK_REF_MISSING] `{name}.{col.name}` references `{col.fk_ref_table}` which does not exist.")
    return errors


def validate_fk_pk_type_match(tables):
    errors = []
    for name, table in tables.items():
        for col in table.fk_columns():
            if not col.fk_ref_table or col.fk_ref_table not in tables:
                continue
            ref_pks = tables[col.fk_ref_table].pk_columns()
            if ref_pks and col.data_type != ref_pks[0].data_type:
                errors.append(
                    f"[TYPE_MISMATCH] `{name}.{col.name}` is `{col.data_type}` "
                    f"but `{col.fk_ref_table}.{ref_pks[0].name}` PK is `{ref_pks[0].data_type}`."
                )
    return errors


def validate_fk_target_is_pk(tables):
    errors = []
    for name, table in tables.items():
        for col in table.fk_columns():
            if not col.fk_ref_table or col.fk_ref_table not in tables:
                continue
            ref_pk_names = [pk.name for pk in tables[col.fk_ref_table].pk_columns()]
            # Candidate matches: the column name itself, stripped prefixes, and dim_calendar shortcut
            candidates = {col.name, col.name.removeprefix("adjusted_")}
            if col.fk_ref_table == "dim_calendar":
                candidates.add("calendar_date")
            if not candidates & set(ref_pk_names):
                errors.append(
                    f"[FK_TARGET_NOT_PK] `{name}.{col.name}` references `{col.fk_ref_table}` "
                    f"but no PK matches (PKs: {ref_pk_names})."
                )
    return errors


def validate_relationships(tables, relationships):
    errors = []
    for rel in relationships:
        for t in (rel.left_table, rel.right_table):
            if t not in tables:
                errors.append(f"[REL_TABLE_MISSING] `{rel.raw_line}` references unknown table `{t}`.")
    return errors


def validate_scd2_completeness(tables):
    """Flag tables that have some but not all SCD2 columns for either naming pattern."""
    errors = []
    # Two accepted patterns; triggers are date columns only (is_current_flag is shared)
    patterns = [
        {"effective_from_date", "effective_to_date", "is_current_flag"},
        {"valid_from_date",     "valid_to_date",     "is_current_flag"},
    ]
    triggers = [
        {"effective_from_date", "effective_to_date"},
        {"valid_from_date",     "valid_to_date"},
    ]
    for name, table in tables.items():
        cols = {c.name for c in table.columns}
        for trigger, pattern in zip(triggers, patterns):
            if cols & trigger:                          # table uses this date pattern
                missing = sorted(pattern - cols)
                if missing:
                    errors.append(f"[SCD2_INCOMPLETE] `{name}` is missing {missing} for complete SCD2 support.")
                break                                   # don't check the other pattern
    return errors


def validate_duplicate_columns(tables):
    errors = []
    for name, table in tables.items():
        seen = set()
        for col in table.columns:
            if col.name in seen:
                errors.append(f"[DUPLICATE_COLUMN] `{name}.{col.name}` appears more than once.")
            seen.add(col.name)
    return errors


def validate_naming_conventions(tables):
    type_hints = {
        "_key":      ["int", "integer", "bigint"],
        "_flag":     ["boolean", "bool"],
        "_date":     ["date"],
        "_amount":   ["decimal", "numeric", "number"],
        "_quantity": ["decimal", "numeric", "number"],
    }
    warnings = []
    for name, table in tables.items():
        for col in table.columns:
            for suffix, expected in type_hints.items():
                if col.name.endswith(suffix) and col.data_type.lower() not in expected:
                    warnings.append(
                        f"[NAMING_CONVENTION] `{name}.{col.name}` ends with `{suffix}` "
                        f"but has type `{col.data_type}` (expected: {expected})."
                    )
    return warnings


def validate_orphan_tables(tables, relationships):
    referenced = {t for rel in relationships for t in (rel.left_table, rel.right_table)}
    return [
        f"[ORPHAN_TABLE] `{name}` is not in any relationship."
        for name in tables if name not in referenced
    ]


def parse_schema_md(filepath: Path) -> dict[str, list[str]]:
    """Return {table_name: [column_names]} from payroll_model.md."""
    tables: dict[str, list[str]] = {}
    current = None
    for line in filepath.read_text(encoding="utf-8").splitlines():
        m = re.match(r'^###\s+((?:dim|fact)_\w+)', line)
        if m:
            current = m.group(1)
            tables[current] = []
        elif current and line.strip().startswith("|") and not re.match(r'^\s*\|[\s\-:|]+\|\s*$', line):
            cells = line.split("|")
            if len(cells) >= 2:
                col_m = re.match(r'`(\w+)`', cells[1].strip())
                if col_m and col_m.group(1).lower() != "column":
                    tables[current].append(col_m.group(1))
    return tables


def validate_schema_md_sync(tables, mermaid_path: Path):
    schema_path = mermaid_path.parent / "payroll_model.md"
    if not schema_path.exists():
        return [f"[SCHEMA_MD_MISSING] payroll_model.md not found — cannot check sync."]

    schema_tables = parse_schema_md(schema_path)
    warnings = []
    mermaid_names = set(tables)
    schema_names  = set(schema_tables)

    for t in sorted(mermaid_names - schema_names):
        warnings.append(f"[SCHEMA_MD_DRIFT] `{t}` is in model.mermaid but missing from payroll_model.md.")
    for t in sorted(schema_names - mermaid_names):
        warnings.append(f"[SCHEMA_MD_DRIFT] `{t}` is in payroll_model.md but not in model.mermaid.")
    for t in sorted(mermaid_names & schema_names):
        mermaid_cols = {c.name for c in tables[t].columns}
        schema_cols  = set(schema_tables[t])
        for col in sorted(mermaid_cols - schema_cols):
            warnings.append(f"[SCHEMA_MD_DRIFT] `{t}.{col}` is in model.mermaid but not in payroll_model.md.")
        for col in sorted(schema_cols - mermaid_cols):
            warnings.append(f"[SCHEMA_MD_DRIFT] `{t}.{col}` is in payroll_model.md but not in model.mermaid.")
    return warnings


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    filepath = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "payroll_model.mermaid"
    if not filepath.exists():
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)

    print(f"Validating: {filepath}\n{'=' * 60}")
    tables, relationships = parse_mermaid(filepath)
    print(f"Parsed {len(tables)} tables, {len(relationships)} relationships.\n")

    errors, warnings = [], []
    errors  += validate_pk_exists(tables)
    errors  += validate_fk_refs(tables)
    errors  += validate_fk_pk_type_match(tables)
    errors  += validate_fk_target_is_pk(tables)
    errors  += validate_relationships(tables, relationships)
    errors  += validate_scd2_completeness(tables)
    errors  += validate_duplicate_columns(tables)
    warnings += validate_naming_conventions(tables)
    warnings += validate_orphan_tables(tables, relationships)
    warnings += validate_schema_md_sync(tables, filepath)

    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  FAIL {e}")
        print()
    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  WARN {w}")
        print()

    if not errors and not warnings:
        print("PASS All checks passed.")
    elif not errors:
        print(f"PASS No errors. {len(warnings)} warning(s).")
    else:
        print(f"FAIL {len(errors)} error(s), {len(warnings)} warning(s).")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
