#!/usr/bin/env python3
"""
validate_model.py — Structural integrity checks for the payroll data model.

Parses payroll_model.mermaid and validates:
  1. Every FK column has a "Ref: <table>" comment pointing to a table that exists
  2. Every FK references a column that is a PK in the target table
  3. FK and PK data types match
  4. Every PK column is present and marked correctly
  5. Every relationship line references tables that exist in the diagram
  6. Naming convention checks (_key, _code, _name, _date, _amount, _quantity, _flag)
  7. SCD2 completeness: tables with effective_from_date also have effective_to_date and is_current_flag
  8. payroll_model.md sync: warns if tables or columns in payroll_model.mermaid are missing from payroll_model.md, or vice versa

Usage:
    python validate_model.py                       # defaults to payroll_model.mermaid in same directory
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
    raw_line: str = ""


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)

    def pk_columns(self) -> list[Column]:
        return [c for c in self.columns if c.is_pk]

    def fk_columns(self) -> list[Column]:
        return [c for c in self.columns if c.is_fk]

    def column_by_name(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)


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

    # Parse tables — names must start with dim_ or fact_
    table_pattern = re.compile(
        r'((?:dim|fact)_\w+)\s*\{([^}]*)\}',
        re.DOTALL
    )

    col_pattern = re.compile(
        r'^\s*(\w+)\s+(\w+)'
        r'(?:\s+(PK|FK))?'
        r'(?:\s+"([^"]*)")?'
        r'\s*$',
        re.MULTILINE
    )

    for table_match in table_pattern.finditer(text):
        table_name = table_match.group(1)
        body = table_match.group(2)
        table = Table(name=table_name)

        for col_match in col_pattern.finditer(body):
            data_type = col_match.group(1)
            col_name = col_match.group(2)
            pk_fk = col_match.group(3) or ""
            comment = col_match.group(4) or ""

            fk_ref = None
            ref_match = re.search(r'Ref:\s*(\w+)', comment)
            if ref_match:
                fk_ref = ref_match.group(1)

            table.columns.append(Column(
                name=col_name,
                data_type=data_type,
                is_pk="PK" in pk_fk,
                is_fk="FK" in pk_fk,
                fk_ref_table=fk_ref,
                raw_line=col_match.group(0).strip(),
            ))

        tables[table_name] = table

    # Parse relationships
    rel_pattern = re.compile(
        r'((?:dim|fact)_\w+)\s+[|}{o]+--[|}{o]+\s+((?:dim|fact)_\w+)\s*:\s*"([^"]*)"'
    )
    for rel_match in rel_pattern.finditer(text):
        relationships.append(Relationship(
            left_table=rel_match.group(1),
            right_table=rel_match.group(2),
            label=rel_match.group(3),
            raw_line=rel_match.group(0).strip(),
        ))

    return tables, relationships


# ─── Validators ───────────────────────────────────────────────────────────────

def validate_pk_exists(tables: dict[str, Table]) -> list[str]:
    """Every table should have at least one PK."""
    errors = []
    for name, table in tables.items():
        if not table.pk_columns():
            errors.append(f"[PK_MISSING] Table `{name}` has no primary key defined.")
    return errors


def validate_fk_ref_exists(tables: dict[str, Table]) -> list[str]:
    """Every FK with a Ref comment should point to a table that exists."""
    errors = []
    for name, table in tables.items():
        for col in table.fk_columns():
            if col.fk_ref_table and col.fk_ref_table not in tables:
                errors.append(
                    f"[FK_REF_MISSING] `{name}.{col.name}` references "
                    f"`{col.fk_ref_table}` which does not exist."
                )
    return errors


def validate_fk_has_ref_comment(tables: dict[str, Table]) -> list[str]:
    """Every FK column should have a Ref comment."""
    errors = []
    for name, table in tables.items():
        for col in table.fk_columns():
            if not col.fk_ref_table:
                errors.append(
                    f"[FK_NO_REF] `{name}.{col.name}` is marked FK but has no "
                    f'"Ref: <table>" comment.'
                )
    return errors


def validate_fk_pk_type_match(tables: dict[str, Table]) -> list[str]:
    """FK data type should match the PK data type of the referenced table."""
    errors = []
    for name, table in tables.items():
        for col in table.fk_columns():
            if not col.fk_ref_table or col.fk_ref_table not in tables:
                continue
            ref_table = tables[col.fk_ref_table]
            ref_pks = ref_table.pk_columns()
            if not ref_pks:
                continue
            ref_pk = ref_pks[0]
            if col.data_type != ref_pk.data_type:
                errors.append(
                    f"[TYPE_MISMATCH] `{name}.{col.name}` is `{col.data_type}` "
                    f"but `{col.fk_ref_table}.{ref_pk.name}` PK is `{ref_pk.data_type}`."
                )
    return errors


def validate_fk_target_is_pk(tables: dict[str, Table]) -> list[str]:
    """The FK column name should correspond to a PK in the target table."""
    errors = []
    for name, table in tables.items():
        for col in table.fk_columns():
            if not col.fk_ref_table or col.fk_ref_table not in tables:
                continue
            ref_table = tables[col.fk_ref_table]
            ref_pk_names = [pk.name for pk in ref_table.pk_columns()]

            candidate_names = [col.name]
            # Strip common prefixes for self-referencing FKs
            for prefix in ("adjusted_",):
                if col.name.startswith(prefix):
                    candidate_names.append(col.name[len(prefix):])
            # Date FKs referencing dim_calendar
            if col.fk_ref_table == "dim_calendar":
                candidate_names.append("calendar_date")

            if not any(cn in ref_pk_names for cn in candidate_names):
                errors.append(
                    f"[FK_TARGET_NOT_PK] `{name}.{col.name}` references `{col.fk_ref_table}` "
                    f"but no PK in that table matches (PKs: {ref_pk_names})."
                )
    return errors


def validate_relationships(tables: dict[str, Table], relationships: list[Relationship]) -> list[str]:
    """Every table in a relationship line should exist."""
    errors = []
    for rel in relationships:
        if rel.left_table not in tables:
            errors.append(
                f"[REL_TABLE_MISSING] Relationship `{rel.raw_line}` references "
                f"unknown table `{rel.left_table}`."
            )
        if rel.right_table not in tables:
            errors.append(
                f"[REL_TABLE_MISSING] Relationship `{rel.raw_line}` references "
                f"unknown table `{rel.right_table}`."
            )
    return errors


def validate_naming_conventions(tables: dict[str, Table]) -> list[str]:
    """Check naming convention compliance (warnings, not errors)."""
    warnings = []
    type_hints = {
        "_key": ["int", "integer", "bigint"],
        "_flag": ["boolean", "bool"],
        "_date": ["date"],
        "_amount": ["decimal", "numeric", "number"],
        "_quantity": ["decimal", "numeric", "number"],
    }
    for name, table in tables.items():
        for col in table.columns:
            for suffix, expected_types in type_hints.items():
                if col.name.endswith(suffix):
                    if col.data_type.lower() not in expected_types:
                        warnings.append(
                            f"[NAMING_CONVENTION] `{name}.{col.name}` ends with "
                            f"`{suffix}` but has type `{col.data_type}` "
                            f"(expected one of: {expected_types})."
                        )
    return warnings


def validate_scd2_completeness(tables: dict[str, Table]) -> list[str]:
    """If a table has effective_from_date, it should also have effective_to_date and is_current_flag.
    Also recognises valid_from_date/valid_to_date as an equivalent pattern."""
    errors = []
    scd2_standard = {"effective_from_date", "effective_to_date", "is_current_flag"}
    scd2_alt = {"valid_from_date", "valid_to_date", "is_current_flag"}
    for name, table in tables.items():
        col_names = {c.name for c in table.columns}
        has_standard = col_names & scd2_standard
        has_alt = col_names & scd2_alt
        if has_standard and has_standard != scd2_standard:
            if has_alt == scd2_alt:
                continue
            missing = scd2_standard - has_standard
            errors.append(
                f"[SCD2_INCOMPLETE] `{name}` has {sorted(has_standard)} but is missing "
                f"{sorted(missing)} for complete SCD2 support."
            )
        if has_alt and has_alt != scd2_alt and not has_standard:
            missing = scd2_alt - has_alt
            errors.append(
                f"[SCD2_INCOMPLETE] `{name}` has {sorted(has_alt)} but is missing "
                f"{sorted(missing)} for complete SCD2 support."
            )
    return errors


def parse_schema_md(filepath: Path) -> dict[str, list[str]]:
    """
    Parse schema.md and return {table_name: [column_names]}.

    Looks for ### dim_* / ### fact_* headings and extracts the first `backtick`
    cell from each markdown table row within that section.
    """
    tables: dict[str, list[str]] = {}
    current_table: str | None = None

    for line in filepath.read_text(encoding="utf-8").splitlines():
        heading_match = re.match(r'^###\s+((?:dim|fact)_\w+)', line)
        if heading_match:
            current_table = heading_match.group(1)
            tables[current_table] = []
            continue

        if current_table is None or not line.strip().startswith("|"):
            continue

        # Skip separator rows (e.g. | --- | --- |)
        if re.match(r'^\s*\|[\s\-:|]+\|\s*$', line):
            continue

        cells = line.split("|")
        if len(cells) >= 2:
            col_match = re.match(r'`(\w+)`', cells[1].strip())
            if col_match:
                col_name = col_match.group(1)
                # Skip header rows
                if col_name.lower() != "column":
                    tables[current_table].append(col_name)

    return tables


def validate_schema_md_sync(tables: dict[str, Table], mermaid_path: Path) -> list[str]:
    """
    Warn if schema.md is out of sync with model.mermaid.

    Checks for:
      - Tables present in the mermaid but missing from schema.md
      - Tables documented in schema.md but not in the mermaid
      - Columns present in a mermaid table but missing from the matching schema.md section
      - Columns documented in schema.md but not present in the mermaid table

    These are warnings, not errors — schema.md is a companion document, not the source of truth.
    """
    schema_path = mermaid_path.parent / "payroll_model.md"
    if not schema_path.exists():
        return [f"[SCHEMA_MD_MISSING] payroll_model.md not found alongside {mermaid_path.name} — cannot check sync."]

    schema_tables = parse_schema_md(schema_path)
    warnings = []

    mermaid_names = set(tables.keys())
    schema_names = set(schema_tables.keys())

    for t in sorted(mermaid_names - schema_names):
        warnings.append(f"[SCHEMA_MD_DRIFT] `{t}` is in model.mermaid but has no section in schema.md.")

    for t in sorted(schema_names - mermaid_names):
        warnings.append(f"[SCHEMA_MD_DRIFT] `{t}` has a section in schema.md but is not in model.mermaid.")

    for table_name in sorted(mermaid_names & schema_names):
        mermaid_cols = {c.name for c in tables[table_name].columns}
        schema_cols = set(schema_tables[table_name])

        for col in sorted(mermaid_cols - schema_cols):
            warnings.append(f"[SCHEMA_MD_DRIFT] `{table_name}.{col}` is in model.mermaid but not documented in schema.md.")

        for col in sorted(schema_cols - mermaid_cols):
            warnings.append(f"[SCHEMA_MD_DRIFT] `{table_name}.{col}` is in schema.md but not in model.mermaid.")

    return warnings


def validate_orphan_tables(tables: dict[str, Table], relationships: list[Relationship]) -> list[str]:
    """Warn about tables not referenced in any relationship."""
    warnings = []
    referenced = set()
    for rel in relationships:
        referenced.add(rel.left_table)
        referenced.add(rel.right_table)
    for name in tables:
        if name not in referenced:
            warnings.append(
                f"[ORPHAN_TABLE] `{name}` is not referenced in any relationship."
            )
    return warnings


def validate_duplicate_columns(tables: dict[str, Table]) -> list[str]:
    """Check for duplicate column names within a table."""
    errors = []
    for name, table in tables.items():
        seen = set()
        for col in table.columns:
            if col.name in seen:
                errors.append(f"[DUPLICATE_COLUMN] `{name}.{col.name}` appears more than once.")
            seen.add(col.name)
    return errors


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    filepath = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "payroll_model.mermaid"

    if not filepath.exists():
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)

    print(f"Validating: {filepath}")
    print("=" * 60)

    tables, relationships = parse_mermaid(filepath)

    print(f"\nParsed {len(tables)} tables and {len(relationships)} relationships.")
    for name, table in tables.items():
        pk_count = len(table.pk_columns())
        fk_count = len(table.fk_columns())
        col_count = len(table.columns)
        print(f"  {name}: {col_count} columns ({pk_count} PK, {fk_count} FK)")
    print()

    # Run all validators
    all_errors: list[str] = []
    all_warnings: list[str] = []

    all_errors.extend(validate_pk_exists(tables))
    all_errors.extend(validate_fk_ref_exists(tables))
    all_errors.extend(validate_fk_has_ref_comment(tables))
    all_errors.extend(validate_fk_pk_type_match(tables))
    all_errors.extend(validate_fk_target_is_pk(tables))
    all_errors.extend(validate_relationships(tables, relationships))
    all_errors.extend(validate_scd2_completeness(tables))
    all_errors.extend(validate_duplicate_columns(tables))
    all_warnings.extend(validate_naming_conventions(tables))
    all_warnings.extend(validate_orphan_tables(tables, relationships))
    all_warnings.extend(validate_schema_md_sync(tables, filepath))

    # Report
    if all_errors:
        print(f"ERRORS ({len(all_errors)}):")
        for e in all_errors:
            print(f"  FAIL {e}")
        print()

    if all_warnings:
        print(f"WARNINGS ({len(all_warnings)}):")
        for w in all_warnings:
            print(f"  WARN {w}")
        print()

    if not all_errors and not all_warnings:
        print("PASS All checks passed. No errors or warnings.")
    elif not all_errors:
        print(f"PASS No errors. {len(all_warnings)} warning(s).")
    else:
        print(f"FAIL {len(all_errors)} error(s), {len(all_warnings)} warning(s).")

    sys.exit(1 if all_errors else 0)


if __name__ == "__main__":
    main()
