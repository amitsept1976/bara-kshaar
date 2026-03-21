#!/usr/bin/env python3
"""Generate SQL INSERT statements from seeds.py data."""

from seeds import REMEDY_SEEDS


def escape_sql_string(value: str) -> str:
    """Escape single quotes for SQL."""
    return value.replace("'", "''")


def _build_insert_statement(name: str, full_name: str) -> str:
    """Build one INSERT statement mirroring app seeding behavior."""
    escaped_name = escape_sql_string(name)
    escaped_full_name = escape_sql_string(full_name)

    description = f"Traditional remedy: {full_name}."
    escaped_description = escape_sql_string(description)
    keywords = f"{name.lower()} {full_name.lower()}"
    escaped_keywords = escape_sql_string(keywords)

    return (
        "INSERT INTO remedies (name, full_name, description, keywords) "
        f"VALUES ('{escaped_name}', '{escaped_full_name}', "
        f"'{escaped_description}', '{escaped_keywords}');"
    )


def generate_sql_inserts() -> list[str]:
    """Generate SQL INSERT statements for all remedy seeds."""
    return [_build_insert_statement(name, full_name) for name, full_name in REMEDY_SEEDS]


def main() -> None:
    """Generate and print SQL INSERT statements."""
    print("-- SQL INSERT statements for remedies table")
    print("-- Generated from seeds.py")
    print()

    inserts = generate_sql_inserts()

    print(f"-- Total INSERT statements: {len(inserts)}")
    print()

    # Print all INSERT statements
    for insert in inserts:
        print(insert)

    print()
    print("-- End of INSERT statements")


if __name__ == "__main__":
    main()