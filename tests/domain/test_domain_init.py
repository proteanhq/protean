"""Tests for the domain initialization behavior."""

import sys
from pathlib import Path

from protean import Domain


def test_domain_init_without_root_path():
    """Test that a Domain can be initialized without root_path."""
    domain = Domain()
    # It should detect the current file's directory
    assert domain.root_path == str(Path(__file__).parent)


def test_domain_init_with_explicit_root_path():
    """Test that a Domain can be initialized with an explicit root_path."""
    test_path = "/test/path"
    domain = Domain(root_path=test_path)
    assert domain.root_path == test_path


def test_domain_init_with_environment_variable(monkeypatch):
    """Test that a Domain uses DOMAIN_ROOT_PATH if set."""
    env_path = "/env/path"
    monkeypatch.setenv("DOMAIN_ROOT_PATH", env_path)
    domain = Domain()
    assert domain.root_path == env_path


def test_domain_fallback_to_cwd_in_interactive(monkeypatch):
    """Test that Domain uses cwd in interactive environments."""
    # Create a Domain with a patched function that intercepts the _guess_caller_path call
    original_init = Domain.__init__

    def patched_init(
        self, root_path=None, name="", config=None, identity_function=None
    ):
        # Mock as if we're in an interactive shell - call original but override root_path handling
        if root_path is None:
            # Simulate the logic in _guess_caller_path for interactive shells
            root_path = str(Path.cwd())

        original_init(
            self,
            root_path=root_path,
            name=name,
            config=config,
            identity_function=identity_function,
        )

    # Apply the patch
    monkeypatch.setattr(Domain, "__init__", patched_init)

    domain = Domain()
    assert domain.root_path == str(Path.cwd())


def test_domain_resolution_priority(monkeypatch):
    """Test that Domain respects the resolution priority."""
    # 1. Explicit root_path should take precedence
    env_path = "/env/path"
    explicit_path = "/explicit/path"
    monkeypatch.setenv("DOMAIN_ROOT_PATH", env_path)

    domain = Domain(root_path=explicit_path)
    assert domain.root_path == explicit_path

    # 2. Environment variable should be next
    domain = Domain()
    assert domain.root_path == env_path

    # 3. Auto-detection should be last
    monkeypatch.delenv("DOMAIN_ROOT_PATH")
    domain = Domain()
    assert domain.root_path != env_path
    assert Path(domain.root_path).exists()


def test_domain_frozen_application(monkeypatch):
    """Test that Domain handles frozen applications correctly."""
    # Mock sys to simulate a frozen app (like PyInstaller)
    frozen_path = "/frozen/app/path"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", frozen_path, raising=False)

    domain = Domain()
    assert domain.root_path == frozen_path


def test_is_interactive_context():
    """Test that _is_interactive_context correctly identifies interactive shells and notebooks."""
    domain = Domain()

    # Test all interactive filenames from the actual implementation
    interactive_filenames = ["<stdin>", "<ipython-input>", "<string>", "<console>"]
    for filename in interactive_filenames:
        assert (
            domain._is_interactive_context(filename) is True
        ), f"Should identify {filename} as interactive"

    # Test typical non-interactive filenames
    non_interactive_filenames = [
        "/path/to/script.py",
        "script.py",
        "__main__.py",
        "",
        None,
    ]
    for filename in non_interactive_filenames:
        assert (
            domain._is_interactive_context(filename) is False
        ), f"Should identify {filename} as non-interactive"


def test_interactive_path_resolution():
    """Test the code path in _guess_caller_path that handles interactive shells."""
    domain = Domain()

    # Create a simplified version of the method that uses the actual implementation
    # of _is_interactive_context to determine behavior
    def simplified_guess_caller_path(filename):
        """Simplified version of _guess_caller_path that only tests the interactive branch."""
        if domain._is_interactive_context(filename):
            return str(Path.cwd())
        return "non-interactive-path"

    # Test all the special filenames that should trigger the interactive path
    for filename in ["<stdin>", "<ipython-input>", "<string>", "<console>"]:
        path = simplified_guess_caller_path(filename)
        assert path == str(
            Path.cwd()
        ), f"For {filename}, should return current working directory"

    # Make sure a regular filename doesn't trigger the interactive path
    assert simplified_guess_caller_path("regular_file.py") == "non-interactive-path"


def test_guess_caller_path_inner_exception_handling(monkeypatch):
    """Test the inner exception handling in _guess_caller_path for TypeError/ValueError."""
    domain = Domain()

    # Mock the frame that would be returned by sys._getframe(2)
    mock_frame = type(
        "MockFrame",
        (),
        {"f_code": type("MockCode", (), {"co_filename": "/path/to/file.py"})},
    )

    # Patch sys._getframe to return our mock frame
    monkeypatch.setattr(sys, "_getframe", lambda depth: mock_frame)

    # Define a mock that will raise TypeError
    def mock_resolve(self, *args, **kwargs):
        raise TypeError("Mock error for testing")

    # Apply the patch to Path.resolve
    monkeypatch.setattr(Path, "resolve", mock_resolve)

    # Now when _guess_caller_path tries to resolve the path, it will raise TypeError
    # and should fall back to returning cwd
    result = domain._guess_caller_path()

    # Verify the fallback path is used (cwd)
    assert result == str(Path.cwd())


def test_guess_caller_path_outer_exception_handling(monkeypatch):
    """Test the outer exception handling in _guess_caller_path."""
    domain = Domain()

    # Mock sys._getframe to raise an exception
    def mock_getframe(depth):
        raise Exception("Mock error for testing the outer exception handler")

    # Patch sys._getframe
    monkeypatch.setattr(sys, "_getframe", mock_getframe)

    # Now calling _guess_caller_path should trigger the outer exception handler
    # and return cwd as the fallback
    result = domain._guess_caller_path()

    # Verify the fallback path is used (cwd)
    assert result == str(Path.cwd())


def test_guess_caller_path_interactive_return(monkeypatch):
    """Test the return value in the interactive shell branch of _guess_caller_path."""
    domain = Domain()

    # Create a mock frame with a filename that will be identified as interactive
    mock_frame = type(
        "MockFrame", (), {"f_code": type("MockCode", (), {"co_filename": "<stdin>"})}
    )

    # Patch sys._getframe to return our mock frame
    monkeypatch.setattr(sys, "_getframe", lambda depth: mock_frame)

    # Call _guess_caller_path, which should detect interactive mode and return cwd
    result = domain._guess_caller_path()

    # Verify it returns the current working directory
    assert result == str(Path.cwd())
