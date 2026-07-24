"""Upsert idempotency: re-running a connector must update rows, not duplicate them."""
from src import db, models


def _conn():
    c = db.connect(":memory:")
    db.init_db(c)
    return c


def test_product_upsert_is_idempotent():
    c = _conn()
    p = models.Product(
        bucket="private", name="Crop-Hail Basic", source_type="aip_site", aip_code="NA",
        crops=["Corn", "Soybeans"], states=["IA"], peril_type="hail",
    )
    id1 = models.upsert_product(c, p)
    id2 = models.upsert_product(c, p)          # same natural key
    assert id1 == id2
    assert c.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
    # Child rows replaced, not appended.
    assert c.execute("SELECT COUNT(*) FROM product_crops").fetchone()[0] == 2


def test_child_rows_refresh_on_update():
    c = _conn()
    p = models.Product(bucket="private", name="X", source_type="aip_site", crops=["Corn"], states=["IA", "IL"])
    models.upsert_product(c, p)
    p.crops = ["Wheat"]                          # narrowed on a later run
    p.states = ["IA"]
    models.upsert_product(c, p)
    crops = [r["crop"] for r in c.execute("SELECT crop FROM product_crops")]
    states = [r["state"] for r in c.execute("SELECT state FROM product_states")]
    assert crops == ["Wheat"]
    assert states == ["IA"]


def test_distinct_keys_make_distinct_rows():
    c = _conn()
    base = dict(bucket="508h", name="Margin Protection", source_type="rma_plans_seed")
    models.upsert_product(c, models.Product(plan_code="16", **base))
    models.upsert_product(c, models.Product(plan_code="17", **base))   # different plan_code
    assert c.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2


def test_aip_upsert_idempotent():
    c = _conn()
    a = models.AIP(aip_code="NA", name="NAU Country Insurance Company", state="MN")
    models.upsert_aip(c, a)
    models.upsert_aip(c, models.AIP(aip_code="NA", name="NAU Country Insurance Company", state="MN"))
    assert c.execute("SELECT COUNT(*) FROM aips").fetchone()[0] == 1
