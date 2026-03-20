#!/usr/bin/env python3
"""Find functions longer than 40 lines in the codebase."""
import ast
import sys
from pathlib import Path

def count_function_lines(node):
    """Count actual code lines (excluding decorators, docstrings)."""
    if not hasattr(node, 'body') or not node.body:
        return 0
    
    start = node.body[0].lineno
    # Skip docstring if present
    if (isinstance(node.body[0], ast.Expr) and 
        isinstance(node.body[0].value, (ast.Str, ast.Constant))):
        if len(node.body) > 1:
            start = node.body[1].lineno
        else:
            return 1  # Only docstring
    
    end = node.end_lineno
    return end - start + 1

def analyze_file(filepath):
    """Find long functions in a Python file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=str(filepath))
    except Exception as e:
        return []
    
    long_funcs = []
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines = count_function_lines(node)
            if lines > 40:
                long_funcs.append({
                    'file': str(filepath),
                    'function': node.name,
                    'line': node.lineno,
                    'length': lines
                })
    
    return long_funcs

def main():
    root = Path('data_analyst_agent')
    all_long_funcs = []
    
    for py_file in root.rglob('*.py'):
        if '__pycache__' in str(py_file):
            continue
        long_funcs = analyze_file(py_file)
        all_long_funcs.extend(long_funcs)
    
    # Sort by length descending
    all_long_funcs.sort(key=lambda x: x['length'], reverse=True)
    
    # Print top 30
    print("Top 30 longest functions (>40 lines):")
    print(f"{'Lines':<8} {'File':<70} {'Function':<30} {'Line#':<6}")
    print("=" * 120)
    
    for func in all_long_funcs[:30]:
        rel_path = func['file'].replace('data_analyst_agent/', '')
        print(f"{func['length']:<8} {rel_path:<70} {func['function']:<30} {func['line']:<6}")
    
    print(f"\nTotal functions >40 lines: {len(all_long_funcs)}")

if __name__ == '__main__':
    main()
