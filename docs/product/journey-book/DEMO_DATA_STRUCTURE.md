# Journey Book Demo Data Structure

This document describes the isolated demo dataset in:

- `journey_book/demo_data.py`

The module does not perform any DB writes. It only returns in-memory dictionaries/lists for Journey Book demos and testing.

## Exported Sections

- `DEMO_USER_PROFILE`
  - Demo user identity/profile context.
- `DEMO_GOALS`
  - Four realistic goals across required categories:
    - career
    - financial
    - personal
    - health
- `DEMO_DAILY_ENTRIES`
  - 210 daily records (180+ required).
  - Each entry includes:
    - date + day index
    - short and long journal text
    - sentiment score/label
    - emotional state
    - habit completion map + missed habits
    - streak progression at day-level
- `DEMO_MILESTONES`
  - Derived/achievement milestones with:
    - `label`
    - `trigger_type`
    - `achieved_date`
    - `category`
- `DEMO_BOOK_CONTENT`
  - Optional pre-structured chapter mapping for preview usage.

## Narrative Arc Encoded in Data

- Day 1-30: strong momentum
- Day 45-70: slump with missed routines and lower confidence
- Around Day 90: turning point/reset
- Day 91+: stronger, sustained consistency

The tone of journal entries gradually shifts from high initial drive, to self-doubt in slump days, to grounded confidence after recovery.

## `get_demo_journey_data()` Return Shape

`get_demo_journey_data()` returns both:

1. Explicit demo sections (`DEMO_*` keys)
2. A collector-like schema used by Journey Book services:

- `profile`
- `goal`
- `journals`
- `streaks`
- `word_frequencies`
- `derived_milestones`

This enables simple drop-in use for local rendering and pipeline previews without touching production data sources.
