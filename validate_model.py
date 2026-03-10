#!/usr/bin/env python3
"""
validate_model.py — Structural integrity checks for the payroll data model.

Parses model.mermaid and validates:
  1. Every FK column has a "Ref: <table>" comment pointing to a table that exists
  2. Every FK references a column that is a PK in the target table
  3. FK and PK data types match
  4. Every PK column is present and marked correctly
  5. Every relationship line references tables that exist in the diagram
  6. Naming convention checks (_key, _code, _name, _date, _amount, _quantity, _flag)
  7. SCD2 completeness: tables with effective_from_date also have effective_to_date and is_current_flag

Usage:
    python validate_model.py                  # defaults to model.mermaid in same directory
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
    fk_ref_table: str | None = None  # extracted from "Ref: <table>"
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

    # Parse tables and columns
    # Pattern: table_name { ... } — table names must start with dim_ or fact_
    table_pattern = re.compile(
        r'((?:dim|fact)_\w+)\s*\{([^}]*)\}',
        re.DOTALL
    )

    # Column pattern: type name PK/FK "comment"
    col_pattern = re.compile(
        r'^\s*(\w+)\s+(\w+)'           # data_type, column_name
        r'(?:\s+(PK|FK))?'             # optional PK/FK marker
        r'(?:\s+"([^"]*)")?'           # optional quoted comment
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

            # Extract FK reference from comment like "Ref: dim_employee"
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
    # Pattern: table1 }o--|| table2 : "label"  (and other cardinality variants)
    rel_pattern = re.compile(
        r'(\w+)\s+[|}{o]+--[|}{o]+\s+(\w+)\s*:\s*"([^"]*)"'
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
            # Match against the first PK (most tables have one)
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
            # The FK column name should match a PK name in the target
            # (allowing for self-references like parent_organisation_key → organisation_key)
            fk_base = col.name
            # Handle prefixed FKs: adjusted_pay_run_key → pay_run_key, parent_organisation_key → organisation_key
            candidate_names = [fk_base]
            # Strip common prefixes
            for prefix in ("adjusted_", "parent_"):
                if fk_base.startswith(prefix):
                    candidate_names.append(fk_base[len(prefix):])
            # Date FKs referencing dim_calendar: start_date, end_date, etc. → calendar_date
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
        # Check standard pattern
        if has_standard and has_standard != scd2_standard:
            # Maybe it's using the alt pattern instead
            if has_alt == scd2_alt:
                continue  # valid alternative
            missing = scd2_standard - has_standard
            errors.append(
                f"[SCD2_INCOMPLETE] `{name}` has {sorted(has_standard)} but is missing "
                f"{sorted(missing)} for complete SCD2 support."
            )
        # Check alt pattern used partially
        if has_alt and has_alt != scd2_alt and not has_standard:
            missing = scd2_alt - has_alt
            errors.append(
                f"[SCD2_INCOMPLETE] `{name}` has {sorted(has_alt)} but is missing "
                f"{sorted(missing)} for complete SCD2 support."
            )
    return errors


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


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    filepath = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "model.mermaid"

    if not filepath.exists():
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)

    print(f"Validating: {filepath}")
    print("=" * 60)

    tables, relationships = parse_mermaid(filepath)

    print(f"\nParsed {len(tables)} tables and {len(relationships)} relationships.")
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
    all_warnings.extend(validate_naming_conventions(tables))
    all_warnings.extend(validate_orphan_tables(tables, relationships))

    # Report
    if all_errors:
        print(f"ERRORS ({len(all_errors)}):")
        for e in all_errors:
            print(f"  ✗ {e}")
        print()

    if all_warnings:
        print(f"WARNINGS ({len(all_warnings)}):")
        for w in all_warnings:
            print(f"  ⚠ {w}")
        print()

    if not all_errors and not all_warnings:
        print("✓ All checks passed. No errors or warnings.")
    elif not all_errors:
        print(f"✓ No errors. {len(all_warnings)} warning(s).")
    else:
        print(f"✗ {len(all_errors)} error(s), {len(all_warnings)} warning(s).")

    sys.exit(1 if all_errors else 0)


if __name__ == "__main__":
    main()
