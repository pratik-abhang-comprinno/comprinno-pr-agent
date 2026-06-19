import ast
import os
from typing import List, Dict, Any

class PythonParser:
    def __init__(self):
        self.max_method_length = int(os.getenv('MAX_METHOD_LENGTH', '50'))
        self.max_class_length = int(os.getenv('MAX_CLASS_LENGTH', '300'))
    
    def parse_file(self, file_path: str) -> Dict[str, Any]:
        """Parse Python file and extract structure"""
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        
        try:
            tree = ast.parse(code)
            return {
                'code': code,
                'functions': self._extract_functions(tree, code),
                'classes': self._extract_classes(tree, code),
                'imports': self._extract_imports(tree)
            }
        except SyntaxError as e:
            return {'error': f'Syntax error: {e}', 'code': code}
    
    def _extract_functions(self, tree: ast.AST, code: str) -> List[Dict]:
        """Extract function definitions"""
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                lines = code.split('\n')
                func_lines = node.end_lineno - node.lineno + 1
                functions.append({
                    'name': node.name,
                    'line_start': node.lineno,
                    'line_end': node.end_lineno,
                    'length': func_lines,
                    'is_long': func_lines > self.max_method_length
                })
        return functions
    
    def _extract_classes(self, tree: ast.AST, code: str) -> List[Dict]:
        """Extract class definitions"""
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                lines = code.split('\n')
                class_lines = node.end_lineno - node.lineno + 1
                methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                classes.append({
                    'name': node.name,
                    'line_start': node.lineno,
                    'line_end': node.end_lineno,
                    'length': class_lines,
                    'methods': methods,
                    'is_god_class': class_lines > self.max_class_length
                })
        return classes
    
    def _extract_imports(self, tree: ast.AST) -> List[str]:
        """Extract import statements"""
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}")
        return imports
