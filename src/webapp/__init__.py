"""Streamlit web-app helpers for the AIP products catalog.

Thin presentation layer over the existing pipeline modules (db, webmap, stack,
export_xlsx). Nothing here re-implements catalog logic — it imports it. Pure,
streamlit-free helpers live in `auth` and `data` so they stay unit-testable.
"""
