import unittest
from unittest.mock import patch

from protean.adapters.repository.sqlalchemy import (
    PostgresqlProvider,
    check_psycopg2_availability,
)
from protean.domain import Domain


class TestPostgresqlProvider(unittest.TestCase):
    def setUp(self):
        self.domain = Domain("test_domain")
        self.conn_info = {
            "database_uri": "postgresql://postgres:postgres@localhost:5432/test_db"
        }

    @patch("protean.adapters.repository.sqlalchemy.check_psycopg2_availability")
    def test_init_with_psycopg2(self, mock_check):
        """Test initialization when psycopg2 is available"""
        mock_check.return_value = "psycopg2"
        provider = PostgresqlProvider("test_provider", self.domain, self.conn_info)

        self.assertEqual(provider.name, "test_provider")
        self.assertEqual(provider.domain, self.domain)
        self.assertEqual(provider.conn_info, self.conn_info)
        self.assertEqual(provider.__database__, "postgresql")

    @patch("protean.adapters.repository.sqlalchemy.check_psycopg2_availability")
    def test_init_with_psycopg2_binary(self, mock_check):
        """Test initialization when psycopg2-binary is available"""
        mock_check.return_value = "psycopg2-binary"
        provider = PostgresqlProvider("test_provider", self.domain, self.conn_info)

        self.assertEqual(provider.name, "test_provider")
        self.assertEqual(provider.domain, self.domain)
        self.assertEqual(provider.conn_info, self.conn_info)
        self.assertEqual(provider.__database__, "postgresql")

    @patch("protean.adapters.repository.sqlalchemy.check_psycopg2_availability")
    def test_init_without_psycopg2(self, mock_check):
        """Test initialization when neither psycopg2 nor psycopg2-binary is available"""
        mock_check.return_value = None
        provider = PostgresqlProvider("test_provider", self.domain, self.conn_info)

        self.assertEqual(provider.name, "test_provider")
        self.assertEqual(provider.domain, self.domain)
        self.assertEqual(provider.conn_info, self.conn_info)
        self.assertEqual(provider.__database__, "postgresql")

    def test_database_specific_engine_args(self):
        """Test the database specific engine arguments"""
        provider = PostgresqlProvider("test_provider", self.domain, self.conn_info)
        engine_args = provider._get_database_specific_engine_args()

        self.assertEqual(engine_args, {"isolation_level": "AUTOCOMMIT"})

    def test_database_specific_session_args(self):
        """Test the database specific session arguments"""
        provider = PostgresqlProvider("test_provider", self.domain, self.conn_info)
        session_args = provider._get_database_specific_session_args()

        self.assertEqual(session_args, {"autoflush": False})
