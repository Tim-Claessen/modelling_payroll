"""
mermaid_to_sql.py — Generate a SQL DDL script from an erDiagram .mermaid file.

Outputs CREATE TABLE statements in module order, followed by FK constraints.
Output file: <input_stem>_build_YYYYMMDD.sql in the same directory.

Notes:
  - PKs are NOT NULL; all other columns are nullable.
  - VARCHAR defaults to 255, DECIMAL to 18,4. Adjust for your platform.
  - FK constraints are ALTER TABLE statements at the end, so creation order doesn't matter.

Usage:
    python mermaid_to_sql.py                        # reads payroll_model.mermaid
    python mermaid_to_sql.py path/to/model.mermaid
"""

import re
import sys
from datetime import date
from pathlib import Path


TYPE_MAP = {
    "int":     "INTEGER",
    "integer": "INTEGER",
    "string":  "VARCHAR(255)",
    "date":    "DATE",
    "boolean": "BOOLEAN",
    "decimal": "DECIMAL(18,4)",
    "time":    "TIME",
}

section_re = re.compile(r'^%%\s*={3,}\s*(.+?)\s*={3,}', re.MULTILINE)
table_re   = re.compile(r'((?:dim|fact)_\w+)\s*\{([^}]*)\}', re.DOTALL)
col_re     = re.compile(r'^\s*(\w+)\s+(\w+)(?:\s+(PK|FK))?(?:\s+"([^"]*)")?', re.MULTILINE)


# ─── Parse ────────────────────────────────────────────────────────────────────

def parse(filepath: Path):
    """Return [(header, [table_dict, ...]), ...] in document order."""
    text = filepath.read_text()

    # Build a sorted list of (position, kind, data) events
    events = (
        [(m.start(), "section", m.group(1).strip()) for m in section_re.finditer(text)] +
        [(m.start(), "table",   m)                  for m in table_re.finditer(text)]
    )
    events.sort()

    sections, header, tables = [], None, []
    for _, kind, data in events:
        if kind == "section":
            if tables:
                sections.append((header, tables))
            header, tables = data, []
        else:
            table = {"name": data.group(1), "columns": []}
            for col in col_re.finditer(data.group(2)):
                ref = re.search(r'Ref:\s*(\w+)', col.group(4) or "")
                table["columns"].append({
                    "name":   col.group(2),
                    "type":   col.group(1),
                    "is_pk":  col.group(3) == "PK",
                    "is_fk":  col.group(3) == "FK",
                    "fk_ref": ref.group(1) if ref else None,
                })
            tables.append(table)

    if tables:
        sections.append((header, tables))
    return sections


# ─── Generate SQL ─────────────────────────────────────────────────────────────

def sql_type(t):
    return TYPE_MAP.get(t.lower(), t.upper())


def create_table(table):
    pk_cols  = [c["name"] for c in table["columns"] if c["is_pk"]]
    col_lines = [
        f"    {c['name']:<30} {sql_type(c['type']):<15}{'NOT NULL' if c['is_pk'] else ''}"
        for c in table["columns"]
    ]
    if pk_cols:
        col_lines.append(f"    CONSTRAINT pk_{table['name']} PRIMARY KEY ({', '.join(pk_cols)})")
    return f"CREATE TABLE IF NOT EXISTS {table['name']} (\n" + ",\n".join(col_lines) + "\n);"


def fk_constraints(sections):
    # Build a lookup of table name → first PK column name
    pk_lookup = {
        t["name"]: next((c["name"] for c in t["columns"] if c["is_pk"]), None)
        for _, tables in sections for t in tables
    }
    stmts = []
    for _, tables in sections:
        for table in tables:
            for col in table["columns"]:
                if col["is_fk"] and col["fk_ref"]:
                    ref_pk = pk_lookup.get(col["fk_ref"], col["name"])
                    stmts.append(
                        f"ALTER TABLE {table['name']}\n"
                        f"    ADD CONSTRAINT fk_{table['name']}_{col['name']}\n"
                        f"    FOREIGN KEY ({col['name']}) REFERENCES {col['fk_ref']} ({ref_pk});"
                    )
    return stmts


def section_comment(header):
    bar = "=" * 60
    return f"-- {bar}\n-- {header or 'UNLABELLED'}\n-- {bar}"


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    filepath = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "payroll_model.mermaid"
    if not filepath.exists():
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    sections = parse(filepath)
    out_path = filepath.parent / f"{filepath.stem}_build_{date.today().strftime('%Y%m%d')}.sql"

    lines = [
        f"-- Generated from {filepath.name}",
        f"-- PKs are NOT NULL; all other columns are nullable.",
        f"-- Review the companion .md file for full nullability before running.",
        "",
    ]

    for header, tables in sections:
        lines += [section_comment(header), ""]
        for table in tables:
            lines += [create_table(table), ""]

    fks = fk_constraints(sections)
    if fks:
        lines += [section_comment("FOREIGN KEY CONSTRAINTS"), ""]
        for stmt in fks:
            lines += [stmt, ""]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
