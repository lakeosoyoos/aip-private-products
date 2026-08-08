

def test_workbook_builds_without_the_dropped_county_detail(tmp_path):
    """The workbook must build against the SHIPPED database shape, not just the working one.

    scripts/build_app_db.py DROPS sob_sales (3.23M rows / ~400 MB of county detail) from the
    database the app actually deploys with, keeping only the sob_national rollup. export_xlsx
    read sob_sales unconditionally, so on Streamlit Cloud the workbook raised
    "no such table: sob_sales" — and because the app builds it eagerly, that took down the
    ENTIRE app, not just the download button. Every test passed throughout, because they all
    ran against the working DB where the table still exists.

    This builds against a database with the table genuinely absent.
    """
    import sqlite3
    from src.export_xlsx import build_workbook
    from src import db as dbmod

    path = tmp_path / "shipped_shape.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    dbmod.init_db(conn)
    conn.execute("DROP TABLE IF EXISTS sob_sales")      # exactly what the build script does
    conn.commit()
    assert "sob_sales" not in {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    out = build_workbook(conn, out_path=tmp_path / "wb.xlsx")
    assert out.exists()
