---
name: research-data-provenance
description: "Check whether each observation identifies its source row and measurement. When reviewing observations from a supplied dataset."
---

# Data intake and provenance

## Evidence to gather

A named source and observations with source row, sample, measurement, value and unit.

## Review procedure

1. Inventory the files actually supplied, their recorded origin, headers and units. Preserve original row numbers. Use any supplied data dictionary to distinguish sample IDs from group labels and technical replicates from independent observations. State explicitly when the mapping or unit is undocumented.

2. Trace each reviewed value to a file, row and measurement. Check missing or ambiguous identifiers, repeated keys, inconsistent units and changes introduced during conversion. Repeated group labels can be valid replicates: ask for a sample key before attributing a row to an individual. Keep raw values intact.

3. Return the usable mappings, affected rows, and the smallest missing piece of evidence. A complete normalized table supports row traceability only; independent source authenticity or instrument identity requires separate evidence.

## Expected result

Traceability assessment with source-row references.
