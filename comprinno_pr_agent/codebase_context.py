"""
Codebase Context Provider
Uses Probe (AST-aware code search) to fetch relevant codebase context
for a given changed file — patterns, conventions, related code.
"""
import subprocess
import os
from typing import Optional


class CodebaseContextProvider:
    def __init__(self, repo_path: str = "."):
        self.repo_path = os.path.abspath(repo_path)
        self.probe_bin = "probe"
        self.probe_available = self._check_probe()

    def _check_probe(self) -> bool:
        """Check if probe binary is available — try multiple locations"""
        locations = [
            "probe",
            "/usr/local/bin/probe",
            os.path.expanduser("~/.local/bin/probe"),
            "/home/runner/.local/bin/probe"
        ]
        for probe_path in locations:
            try:
                r = subprocess.run([probe_path, "--version"], capture_output=True, timeout=5)
                if r.returncode == 0:
                    self.probe_bin = probe_path
                    print(f"🔧 Probe found at: {probe_path}")
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        print(f"🔧 Probe not found in any location")
        return False

    def _run_probe(self, query: str, language: str = None, max_tokens: int = 2000, path: str = None) -> str:
        """Run a probe search query and return results"""
        if not self.probe_available:
            return ""
        try:
            search_path = path if path and os.path.exists(path) else self.repo_path
            # Correct probe CLI syntax: probe search [--language <LANG>] <PATTERN> <PATH>
            cmd = [self.probe_bin, "search"]
            if language:
                cmd += [f"--language={language}"]
            cmd += [query, search_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    def get_context_for_file(self, file_path: str, code: str, language: str) -> str:
        """
        Get relevant codebase context for a changed file.
        Searches for similar patterns, conventions, and related code.
        """
        if not self.probe_available:
            return self._get_static_context(file_path)

        context_parts = []
        file_name = os.path.basename(file_path).replace('.py', '').replace('.js', '').replace('.ts', '')
        search_terms = self._extract_search_terms(file_name, code)

        # Search 1 — Find similar files in the same directory (most relevant for conventions)
        file_dir = os.path.dirname(file_path)
        dir_path = os.path.join(self.repo_path, file_dir)
        print(f"🔧 Searching dir: {dir_path} (exists: {os.path.exists(dir_path)})")
        dir_results = self._run_probe("execute", language=language, max_tokens=1200, path=dir_path)
        print(f"🔧 Dir search returned: {len(dir_results)} chars")
        if dir_results and file_name not in dir_results:
            context_parts.append(f"### Existing patterns in same directory (follow these conventions exactly):\n{dir_results}")

        # Search 2 — Find similar patterns by key terms
        for term in search_terms[:2]:
            results = self._run_probe(term, language=language, max_tokens=600)
            if results and file_name not in results:
                context_parts.append(f"### Existing '{term}' patterns:\n{results}")

        # Search 3 — Find error handling conventions
        error_results = self._run_probe("except Exception", language=language, max_tokens=500)
        if error_results:
            context_parts.append(f"### Error handling conventions:\n{error_results}")

        print(f"🔧 Total context parts: {len(context_parts)}")
        if not context_parts:
            return ""

        return "## Codebase Context — How similar things are done in this project:\n\n" + \
               "\n\n".join(context_parts[:3])

    def _extract_search_terms(self, file_name: str, code: str) -> list:
        """Extract meaningful search terms from file name and code"""
        terms = []
        for word in file_name.replace('_', ' ').replace('-', ' ').split():
            if len(word) > 3:
                terms.append(word)
        import re
        class_names = re.findall(r'class\s+(\w+)', code)
        func_names = re.findall(r'def\s+(\w+)', code)
        for name in class_names[:2] + func_names[:3]:
            if len(name) > 4 and name not in ('self', 'init', 'main'):
                terms.append(name)
        return list(dict.fromkeys(terms))

    def _get_static_context(self, file_path: str) -> str:
        """Fallback — read CODING_STANDARDS.md if probe not available"""
        standards_paths = [
            os.path.join(self.repo_path, 'CODING_STANDARDS.md'),
            os.path.join(self.repo_path, 'CONTRIBUTING.md'),
            os.path.join(self.repo_path, '.github', 'CODING_STANDARDS.md'),
        ]
        for path in standards_paths:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    content = f.read()[:2000]
                return f"## Project Coding Standards:\n{content}"
        return ""
