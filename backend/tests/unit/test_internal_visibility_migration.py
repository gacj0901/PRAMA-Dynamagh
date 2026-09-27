from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect


def test_internal_visibility_migration_adds_classification_fields_and_indexes():
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0033_internal_mandate_visibility.py"
    )
    spec = spec_from_file_location("internal_visibility_migration", migration_path)
    migration = module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            Table(
                "mandates",
                MetaData(),
                Column("mandate_id", String(64), primary_key=True),
            ).create(connection)
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()

            columns = {column["name"]: column for column in inspect(connection).get_columns("mandates")}
            indexes = {index["name"] for index in inspect(connection).get_indexes("mandates")}
            assert {"visibility", "campaign_id", "case_id", "purpose"}.issubset(columns)
            assert columns["visibility"]["nullable"] is False
            assert columns["visibility"]["default"] == "'PUBLIC'"
            assert columns["campaign_id"]["nullable"] is True
            assert columns["case_id"]["nullable"] is True
            assert columns["purpose"]["nullable"] is True
            assert {"ix_mandates_campaign_id", "ix_mandates_case_id"}.issubset(indexes)
    finally:
        engine.dispose()
