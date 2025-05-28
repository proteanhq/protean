import os
from unittest.mock import patch

from protean.domain.helpers import get_debug_flag, get_env


class TestGetEnv:
    """Test cases for get_env() function"""

    def test_get_env_returns_production_by_default(self):
        """Test that get_env returns 'production' when PROTEAN_ENV is not set"""
        with patch.dict(os.environ, {}, clear=True):
            # Remove PROTEAN_ENV if it exists
            if "PROTEAN_ENV" in os.environ:
                del os.environ["PROTEAN_ENV"]
            assert get_env() == "production"

    def test_get_env_returns_development_when_set(self):
        """Test that get_env returns 'development' when PROTEAN_ENV is set to development"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "development"}):
            assert get_env() == "development"

    def test_get_env_returns_testing_when_set(self):
        """Test that get_env returns 'testing' when PROTEAN_ENV is set to testing"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "testing"}):
            assert get_env() == "testing"

    def test_get_env_returns_staging_when_set(self):
        """Test that get_env returns 'staging' when PROTEAN_ENV is set to staging"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "staging"}):
            assert get_env() == "staging"

    def test_get_env_returns_production_when_explicitly_set(self):
        """Test that get_env returns 'production' when PROTEAN_ENV is explicitly set to production"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "production"}):
            assert get_env() == "production"

    def test_get_env_returns_custom_value(self):
        """Test that get_env returns custom values when PROTEAN_ENV is set to non-standard values"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "custom_env"}):
            assert get_env() == "custom_env"

    def test_get_env_handles_empty_string(self):
        """Test that get_env returns 'production' when PROTEAN_ENV is set to empty string"""
        with patch.dict(os.environ, {"PROTEAN_ENV": ""}):
            assert get_env() == "production"

    def test_get_env_handles_whitespace(self):
        """Test that get_env returns whitespace value when PROTEAN_ENV contains only whitespace"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "   "}):
            assert get_env() == "   "

    def test_get_env_case_sensitivity(self):
        """Test that get_env is case sensitive"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "DEVELOPMENT"}):
            assert get_env() == "DEVELOPMENT"

        with patch.dict(os.environ, {"PROTEAN_ENV": "Development"}):
            assert get_env() == "Development"


class TestGetDebugFlag:
    """Test cases for get_debug_flag() function"""

    def test_get_debug_flag_true_when_env_is_development_and_no_debug_var(self):
        """Test that get_debug_flag returns True when PROTEAN_ENV is development and PROTEAN_DEBUG is not set"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "development"}, clear=True):
            if "PROTEAN_DEBUG" in os.environ:
                del os.environ["PROTEAN_DEBUG"]
            assert get_debug_flag() is True

    def test_get_debug_flag_false_when_env_is_production_and_no_debug_var(self):
        """Test that get_debug_flag returns False when PROTEAN_ENV is production and PROTEAN_DEBUG is not set"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "production"}, clear=True):
            if "PROTEAN_DEBUG" in os.environ:
                del os.environ["PROTEAN_DEBUG"]
            assert get_debug_flag() is False

    def test_get_debug_flag_false_when_env_is_testing_and_no_debug_var(self):
        """Test that get_debug_flag returns False when PROTEAN_ENV is testing and PROTEAN_DEBUG is not set"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "testing"}, clear=True):
            if "PROTEAN_DEBUG" in os.environ:
                del os.environ["PROTEAN_DEBUG"]
            assert get_debug_flag() is False

    def test_get_debug_flag_false_when_env_is_staging_and_no_debug_var(self):
        """Test that get_debug_flag returns False when PROTEAN_ENV is staging and PROTEAN_DEBUG is not set"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "staging"}, clear=True):
            if "PROTEAN_DEBUG" in os.environ:
                del os.environ["PROTEAN_DEBUG"]
            assert get_debug_flag() is False

    def test_get_debug_flag_false_when_no_env_and_no_debug_var(self):
        """Test that get_debug_flag returns False when neither PROTEAN_ENV nor PROTEAN_DEBUG is set (defaults to production)"""
        with patch.dict(os.environ, {}, clear=True):
            if "PROTEAN_ENV" in os.environ:
                del os.environ["PROTEAN_ENV"]
            if "PROTEAN_DEBUG" in os.environ:
                del os.environ["PROTEAN_DEBUG"]
            assert get_debug_flag() is False

    def test_get_debug_flag_true_when_debug_is_true(self):
        """Test that get_debug_flag returns True when PROTEAN_DEBUG is set to 'true'"""
        with patch.dict(os.environ, {"PROTEAN_DEBUG": "true"}):
            assert get_debug_flag() is True

    def test_get_debug_flag_true_when_debug_is_1(self):
        """Test that get_debug_flag returns True when PROTEAN_DEBUG is set to '1'"""
        with patch.dict(os.environ, {"PROTEAN_DEBUG": "1"}):
            assert get_debug_flag() is True

    def test_get_debug_flag_true_when_debug_is_yes(self):
        """Test that get_debug_flag returns True when PROTEAN_DEBUG is set to 'yes'"""
        with patch.dict(os.environ, {"PROTEAN_DEBUG": "yes"}):
            assert get_debug_flag() is True

    def test_get_debug_flag_false_when_debug_is_false(self):
        """Test that get_debug_flag returns False when PROTEAN_DEBUG is set to 'false'"""
        with patch.dict(os.environ, {"PROTEAN_DEBUG": "false"}):
            assert get_debug_flag() is False

    def test_get_debug_flag_false_when_debug_is_0(self):
        """Test that get_debug_flag returns False when PROTEAN_DEBUG is set to '0'"""
        with patch.dict(os.environ, {"PROTEAN_DEBUG": "0"}):
            assert get_debug_flag() is False

    def test_get_debug_flag_false_when_debug_is_no(self):
        """Test that get_debug_flag returns False when PROTEAN_DEBUG is set to 'no'"""
        with patch.dict(os.environ, {"PROTEAN_DEBUG": "no"}):
            assert get_debug_flag() is False

    def test_get_debug_flag_case_insensitive_false_values(self):
        """Test that get_debug_flag handles case insensitive false values"""
        false_values = ["FALSE", "False", "NO", "No", "0"]
        for value in false_values:
            with patch.dict(os.environ, {"PROTEAN_DEBUG": value}):
                assert get_debug_flag() is False, f"Failed for value: {value}"

    def test_get_debug_flag_case_insensitive_true_values(self):
        """Test that get_debug_flag handles case insensitive true values"""
        true_values = ["TRUE", "True", "YES", "Yes", "1", "on", "ON", "On"]
        for value in true_values:
            with patch.dict(os.environ, {"PROTEAN_DEBUG": value}):
                assert get_debug_flag() is True, f"Failed for value: {value}"

    def test_get_debug_flag_empty_string_defaults_to_env_check(self):
        """Test that get_debug_flag falls back to environment check when PROTEAN_DEBUG is empty string"""
        with patch.dict(
            os.environ, {"PROTEAN_ENV": "development", "PROTEAN_DEBUG": ""}
        ):
            assert get_debug_flag() is True

        with patch.dict(os.environ, {"PROTEAN_ENV": "production", "PROTEAN_DEBUG": ""}):
            assert get_debug_flag() is False

    def test_get_debug_flag_whitespace_string_defaults_to_env_check(self):
        """Test that get_debug_flag falls back to environment check when PROTEAN_DEBUG is whitespace"""
        with patch.dict(
            os.environ, {"PROTEAN_ENV": "development", "PROTEAN_DEBUG": "   "}
        ):
            assert get_debug_flag() is True

        with patch.dict(
            os.environ, {"PROTEAN_ENV": "production", "PROTEAN_DEBUG": "   "}
        ):
            assert get_debug_flag() is False

    def test_get_debug_flag_overrides_development_env_when_explicitly_false(self):
        """Test that PROTEAN_DEBUG=false overrides development environment"""
        with patch.dict(
            os.environ, {"PROTEAN_ENV": "development", "PROTEAN_DEBUG": "false"}
        ):
            assert get_debug_flag() is False

    def test_get_debug_flag_overrides_production_env_when_explicitly_true(self):
        """Test that PROTEAN_DEBUG=true overrides production environment"""
        with patch.dict(
            os.environ, {"PROTEAN_ENV": "production", "PROTEAN_DEBUG": "true"}
        ):
            assert get_debug_flag() is True

    def test_get_debug_flag_with_custom_env_and_no_debug_var(self):
        """Test that get_debug_flag returns False for custom environments when PROTEAN_DEBUG is not set"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "custom_env"}, clear=True):
            if "PROTEAN_DEBUG" in os.environ:
                del os.environ["PROTEAN_DEBUG"]
            assert get_debug_flag() is False

    def test_get_debug_flag_with_invalid_debug_value(self):
        """Test that get_debug_flag returns True for invalid PROTEAN_DEBUG values (not in false list)"""
        invalid_values = ["invalid", "maybe", "2", "debug", "enable"]
        for value in invalid_values:
            with patch.dict(os.environ, {"PROTEAN_DEBUG": value}):
                assert get_debug_flag() is True, f"Failed for value: {value}"


class TestIntegration:
    """Integration tests for helpers functions"""

    def test_both_functions_work_together_development(self):
        """Test that both functions work correctly together in development environment"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "development"}, clear=True):
            if "PROTEAN_DEBUG" in os.environ:
                del os.environ["PROTEAN_DEBUG"]
            assert get_env() == "development"
            assert get_debug_flag() is True

    def test_both_functions_work_together_production(self):
        """Test that both functions work correctly together in production environment"""
        with patch.dict(os.environ, {"PROTEAN_ENV": "production"}, clear=True):
            if "PROTEAN_DEBUG" in os.environ:
                del os.environ["PROTEAN_DEBUG"]
            assert get_env() == "production"
            assert get_debug_flag() is False

    def test_both_functions_work_together_with_debug_override(self):
        """Test that both functions work correctly together with debug override"""
        with patch.dict(
            os.environ, {"PROTEAN_ENV": "production", "PROTEAN_DEBUG": "true"}
        ):
            assert get_env() == "production"
            assert get_debug_flag() is True

    def test_both_functions_with_no_env_vars(self):
        """Test that both functions work correctly with no environment variables set"""
        with patch.dict(os.environ, {}, clear=True):
            if "PROTEAN_ENV" in os.environ:
                del os.environ["PROTEAN_ENV"]
            if "PROTEAN_DEBUG" in os.environ:
                del os.environ["PROTEAN_DEBUG"]
            assert get_env() == "production"
            assert get_debug_flag() is False
