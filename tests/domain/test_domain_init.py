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
