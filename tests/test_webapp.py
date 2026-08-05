"""Tests for the web-app helper layer — passcode gate + product filtering.

These cover the streamlit-free logic only (no UI): the constant-time passcode
check, passcode collection from secrets/env, subsidy derivation, and the
products filter. They run against the bundled catalog.db.
"""
import pandas as pd
import pytest

from src.webapp import auth, data


# ------------------------------------------------------------ passcode gate
def test_verify_passcode_matches_and_rejects():
    allowed = ["s3cret", "other-user-pass"]
    assert auth.verify_passcode("s3cret", allowed) is True
    assert auth.verify_passcode("other-user-pass", allowed) is True
    assert auth.verify_passcode("wrong", allowed) is False
    assert auth.verify_passcode("s3cre", allowed) is False  # prefix must not pass


def test_verify_passcode_empty_never_authenticates():
    assert auth.verify_passcode("", ["s3cret"]) is False
    assert auth.verify_passcode("s3cret", []) is False
    assert auth.verify_passcode("s3cret", [""]) is False


def test_allowed_passcodes_reads_single_table_and_env(monkeypatch):
    monkeypatch.delenv("APP_PASSCODE", raising=False)
    secrets = {"app_passcode": "one", "passcodes": {"alice": "a1", "bob": "b2"}}
    got = auth.allowed_passcodes(secrets)
    assert set(got) == {"one", "a1", "b2"}

    monkeypatch.setenv("APP_PASSCODE", "envpass")
    got2 = auth.allowed_passcodes({})
    assert got2 == ["envpass"]


def test_allowed_passcodes_dedupes(monkeypatch):
    monkeypatch.setenv("APP_PASSCODE", "dup")
    got = auth.allowed_passcodes({"app_passcode": "dup"})
    assert got == ["dup"]


# ------------------------------------------------------------ subsidy rule
def test_derive_subsidized():
    assert data.derive_subsidized("508h") is True
    assert data.derive_subsidized("private") is False


# ------------------------------------------------------------ product filter
@pytest.fixture(scope="module")
def products_df():
    conn = data.open_ro()
    try:
        return data.products_dataframe(conn)
    finally:
        conn.close()


def test_products_dataframe_shape(products_df):
    assert len(products_df) > 100  # catalog grows; just assert it's populated, not an exact count
    for col in ("name", "AIP", "bucket", "subsidy", "layer", "doc_url", "_crops_list"):
        assert col in products_df.columns
    # subsidy is derived consistently from bucket
    assert (products_df["subsidized"] == (products_df["bucket"] != "private")).all()


def test_filter_by_bucket_reduces_rows(products_df):
    fed = data.filter_products(products_df, bucket="508h")
    priv = data.filter_products(products_df, bucket="private")
    assert len(fed) == 16                              # the 508(h) reference set is fixed
    assert len(priv) == len(products_df) - len(fed)    # everything else is private (count grows)
    assert len(priv) > len(fed)
    assert len(fed) + len(priv) == len(products_df)


def test_filter_by_subsidy(products_df):
    sub = data.filter_products(products_df, subsidy="subsidized")
    unsub = data.filter_products(products_df, subsidy="private")
    assert sub["subsidized"].all()
    assert not unsub["subsidized"].any()


def test_filter_search_is_case_insensitive(products_df):
    hail = data.filter_products(products_df, search="hail")
    assert len(hail) > 0
    assert hail["name"].str.contains("hail", case=False).all()


def test_filter_crops_any_match(products_df):
    crop_opts = sorted({c for cl in products_df["_crops_list"] for c in cl})
    assert crop_opts, "expected some crops in the catalog"
    target = crop_opts[0]
    filtered = data.filter_products(products_df, crops=[target])
    assert len(filtered) > 0
    assert filtered["_crops_list"].apply(lambda cl: target in cl).all()


def test_filters_combine(products_df):
    combined = data.filter_products(products_df, bucket="private", subsidy="private")
    # bucket=private is already all-unsubsidized, so combining changes nothing
    assert len(combined) == len(data.filter_products(products_df, bucket="private"))
    assert not combined["subsidized"].any()


def test_empty_filters_return_all(products_df):
    assert len(data.filter_products(products_df)) == len(products_df)
