#!/usr/bin/env python3
"""
Generate SQL INSERT statements from seeds.py data
"""

from seeds import REMEDY_SEEDS
import textwrap

def escape_sql_string(s):
    """Escape single quotes for SQL"""
    return s.replace("'", "''")

def generate_sql_inserts():
    """Generate SQL INSERT statements for all remedy seeds"""

    inserts = []

    for name, full_name in REMEDY_SEEDS:
        # Escape single quotes in strings
        escaped_name = escape_sql_string(name)
        escaped_full_name = escape_sql_string(full_name)

        # Generate description and keywords as done in the app
        description = f"Traditional remedy: {full_name}."
        escaped_description = escape_sql_string(description)
        keywords = f"{name.lower()} {full_name.lower()}"
        escaped_keywords = escape_sql_string(keywords)

        # Create INSERT statement
        insert = f"""INSERT INTO remedies (name, full_name, description, keywords) VALUES ('{escaped_name}', '{escaped_full_name}', '{escaped_description}', '{escaped_keywords}');"""
        inserts.append(insert)

    return inserts

def main():
    """Generate and print SQL INSERT statements"""
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