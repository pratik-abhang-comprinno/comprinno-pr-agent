"""
PR Agent Config Loader
Reads .pr-agent-config.yml from repo root to customize agent behavior.
"""
import os
import yaml
from typing import Dict, Any


DEFAULT_CONFIG = {
    "review": {
        "depth": "thorough",        # thorough | standard | quick
        "scope": "pr_and_codebase"  # pr_only | pr_and_codebase
    },
    "standards": {
        "file": None                # path to coding standards doc
    },
    "ignore": []                    # file patterns to skip
}


def load_config(repo_path: str = ".") -> Dict[str, Any]:
    """Load .pr-agent-config.yml from repo root, fall back to defaults"""
    config_path = os.path.join(repo_path, ".pr-agent-config.yml")
    config = DEFAULT_CONFIG.copy()

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                user_config = yaml.safe_load(f) or {}
            # Deep merge user config into defaults
            for key, value in user_config.items():
                if isinstance(value, dict) and key in config:
                    config[key].update(value)
                else:
                    config[key] = value
            print(f"📋 Loaded .pr-agent-config.yml from {config_path}")
        except Exception as e:
            print(f"⚠️  Could not load .pr-agent-config.yml: {e} — using defaults")
    else:
        print(f"📋 No .pr-agent-config.yml found — using default settings")

    return config


def get_coding_standards(config: Dict, repo_path: str) -> str:
    """Read coding standards file if configured"""
    standards_file = config.get("standards", {}).get("file")
    if not standards_file:
        return ""
    path = os.path.join(repo_path, standards_file)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return f.read()[:3000]
    return ""


def should_ignore_file(filename: str, config: Dict) -> bool:
    """Check if a file should be ignored based on config patterns"""
    import fnmatch
    ignore_patterns = config.get("ignore", [])
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(os.path.basename(filename), pattern):
            return True
    return False
