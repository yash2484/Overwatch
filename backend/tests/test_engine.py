from overwatch.db.engine import sqlalchemy_url


def test_plain_postgresql_url_gets_psycopg_driver() -> None:
    assert (
        sqlalchemy_url("postgresql://u:p@postgis:5432/overwatch")
        == "postgresql+psycopg://u:p@postgis:5432/overwatch"
    )


def test_explicit_driver_urls_pass_through() -> None:
    url = "postgresql+psycopg://u:p@host/db"
    assert sqlalchemy_url(url) == url
