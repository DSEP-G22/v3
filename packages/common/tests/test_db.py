from lanka_common.db import parse_neon_key

URL = (
    "postgresql://u:p@ep-x-123-pooler.us-east-2.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)


def test_bare_url():
    d = parse_neon_key(URL)
    assert d.pooled == "postgresql://u:p@ep-x-123-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require"
    assert d.direct == "postgresql://u:p@ep-x-123.us-east-2.aws.neon.tech/neondb?sslmode=require"


def test_psql_command_with_prefix_and_spacing():
    assert parse_neon_key(f"NEON_KEY = psql '{URL}'") == parse_neon_key(URL)


def test_sqlalchemy_and_postgres_scheme():
    d = parse_neon_key(URL.replace("postgresql://", "postgres://"))
    assert d.sqlalchemy().startswith("postgresql+asyncpg://")
    assert "-pooler" not in d.sqlalchemy(direct=True)


def test_rejects_garbage():
    try:
        parse_neon_key("nope")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
