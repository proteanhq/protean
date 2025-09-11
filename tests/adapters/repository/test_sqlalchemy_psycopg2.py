import unittest
from unittest.mock import patch

from protean.adapters.repository.sqlalchemy import check_psycopg2_availability


class TestPsycopg2Availability(unittest.TestCase):
    @patch("importlib.util.find_spec")
    def test_psycopg2_available(self, mock_find_spec):
        """Test when psycopg2 is available"""

        def mock_find_spec_impl(name):
            if name == "psycopg2":
                return True
            return None

        mock_find_spec.side_effect = mock_find_spec_impl
        result = check_psycopg2_availability()
        self.assertEqual(result, "psycopg2")

    @patch("importlib.util.find_spec")
    def test_psycopg2_binary_available(self, mock_find_spec):
        """Test when psycopg2-binary is available"""

        def mock_find_spec_impl(name):
            if name == "psycopg2_binary":
                return True
            return None

        mock_find_spec.side_effect = mock_find_spec_impl
        result = check_psycopg2_availability()
        self.assertEqual(result, "psycopg2-binary")

    @patch("importlib.util.find_spec")
    def test_no_psycopg2_available(self, mock_find_spec):
        """Test when neither psycopg2 nor psycopg2-binary is available"""
        mock_find_spec.return_value = None
        result = check_psycopg2_availability()
        self.assertIsNone(result)

    @patch("importlib.util.find_spec")
    def test_both_psycopg2_versions_available(self, mock_find_spec):
        """Test when both psycopg2 and psycopg2-binary are available"""
        mock_find_spec.return_value = True
        result = check_psycopg2_availability()
        self.assertEqual(result, "psycopg2")
