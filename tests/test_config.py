import pytest

from app.core.config import Settings, validate_production_config


def test_empty_urls_become_none_and_fall_back_to_writer(monkeypatch):
    monkeypatch.setenv("DB_WRITER_URL", "mssql+aioodbc://u:p@h:1433/sav_uat?driver=x")
    monkeypatch.setenv("DB_READER_URL", "")
    monkeypatch.setenv("DB_MIGRATION_URL", "  ")
    s = Settings(_env_file=None)
    assert s.DB_READER_URL is None
    assert s.DB_MIGRATION_URL is None
    assert s.reader_url == s.writer_url == s.migration_url


def test_url_is_secret_in_repr(monkeypatch):
    monkeypatch.setenv("DB_WRITER_URL", "mssql+aioodbc://u:topsecret@h/db")
    s = Settings(_env_file=None)
    assert "topsecret" not in repr(s)
    assert "topsecret" not in str(s.model_dump())


def test_missing_writer_url_raises(monkeypatch):
    monkeypatch.delenv("DB_WRITER_URL", raising=False)
    s = Settings(_env_file=None)
    with pytest.raises(RuntimeError, match="DB_WRITER_URL"):
        _ = s.writer_url


def test_production_guard(monkeypatch):
    monkeypatch.delenv("DB_WRITER_URL", raising=False)
    s = Settings(_env_file=None, ENVIRONMENT="prod", DB_ECHO=True, CORS_ORIGINS=["*"])
    with pytest.raises(RuntimeError) as e:
        validate_production_config(s)
    msg = str(e.value)
    assert "DB_WRITER_URL" in msg
    assert "DB_ECHO" in msg
    assert "CORS_ORIGINS" in msg


def test_non_prod_is_not_guarded():
    validate_production_config(Settings(_env_file=None, ENVIRONMENT="local"))
