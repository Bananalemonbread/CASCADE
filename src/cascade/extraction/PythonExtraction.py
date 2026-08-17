import ast
import os
import textwrap
import tokenize
from typing import Any, Dict, List

from cascade.extraction.Extraction import Extraction
from cascade.extraction.JsonExtraction import JsonExtraction
from cascade.utils.Utils import save_dicts_list_to_json


class PythonExtraction(Extraction):
    def __init__(self, pattern: str = "test_%c.py"):
        """
        Extracts Python functions and methods from a Python project.

        :param pattern: Pattern used to infer test files from source files.
        """
        super().__init__()
        self.pattern = pattern

    def extract(self, input_path, output_path) -> List[Dict[str, Any]]:
        """
        Extracts Python functions and methods from the project at input_path.

        If there already is an extracted.json in the output folder, loads that instead.

        :param input_path: path to the Python project root
        :param output_path: path where extracted.json should be written
        :return: extracted function/method contexts
        """
        json_extractor = JsonExtraction()
        extracted = json_extractor.extract(input_path, output_path)

        if extracted:
            return extracted

        extracted = []
        next_id = 0

        for file_path in self.find_python_files(input_path):
            rel_path = os.path.relpath(file_path, input_path)

            try:
                # Respect PEP 263 encoding declarations used by older Python
                # projects. A single unreadable source file must not abort the
                # extraction of the complete repository.
                with tokenize.open(file_path) as f:
                    source = f.read()
            except (OSError, UnicodeError, SyntaxError):
                continue

            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue

            module_imports = self.extract_imports(tree)
            module_variables = self.extract_variables(tree.body)
            module_functions = [node for node in tree.body if self.is_function(node)]

            for node in module_functions:
                extracted.append(
                    self.build_function_context(
                        node=node,
                        source=source,
                        rel_path=rel_path,
                        imports=module_imports,
                        variables=module_variables,
                        all_functions=module_functions,
                        next_id=next_id,
                    )
                )
                next_id += 1

            for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
                class_methods = [node for node in class_node.body if self.is_function(node)]

                for method_node in class_methods:
                    extracted.append(
                        self.build_function_context(
                            node=method_node,
                            source=source,
                            rel_path=rel_path,
                            imports=module_imports,
                            variables=[],
                            all_functions=class_methods,
                            next_id=next_id,
                            class_node=class_node,
                        )
                    )
                    next_id += 1

        save_dicts_list_to_json(extracted, os.path.join(output_path, "extracted.json"))
        return extracted

    def find_python_files(self, input_path):
        ignored_dirs = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "build", "dist"}

        for root, dirs, files in os.walk(input_path):
            dirs[:] = [d for d in dirs if d not in ignored_dirs and d != "tests"]

            for file in files:
                if not file.endswith(".py"):
                    continue

                if file.startswith("test_") or file.endswith("_test.py"):
                    continue

                yield os.path.join(root, file)

    def build_function_context(self, node, source, rel_path, imports, variables, all_functions, next_id, class_node=None):
        doc = ast.get_docstring(node)
        parent_context = self.build_parent_context(class_node, imports, variables, all_functions, node)

        return {
            "id": next_id,
            "language": "Python",
            "doc": f'"""{doc}"""' if doc else "",
            "signature": self.extract_signature(node, is_method=(class_node is not None)),
            "parent": [parent_context],
            "code": self.extract_body(source, node),
            "code_file_path": rel_path,
            "code_file_content": source,
            "tests": [],
            "called_functions": [],
            "module_name": self.module_name_from_path(rel_path),
            "qualified_name": self.qualified_name(node, class_node),
            "import_path": self.import_path(rel_path, node, class_node),
        }

    def build_parent_context(self, class_node, imports, variables, all_functions, current_function):
        other_methods = [
            {
                "doc": self.format_docstring(ast.get_docstring(node)),
                "signature": self.extract_signature(node, is_method=(class_node is not None)),
                "code": self.extract_node_code(node),
            }
            for node in all_functions
            if node is not current_function
        ]

        if class_node is None:
            return {
                "name": "root module",
                "parent_type": "Module",
                "imports": imports,
                "variables": variables,
                "other_methods": other_methods,
                "constructors": [],
            }

        constructors = [
            method for method in other_methods
            if method["signature"]["name"] == "__init__"
        ]
        other_methods = [
            method for method in other_methods
            if method["signature"]["name"] != "__init__"
        ]

        return {
            "name": class_node.name,
            "parent_type": "Class",
            "bases": [ast.unparse(base) for base in class_node.bases],
            "decorators": [self.format_decorator(decorator) for decorator in class_node.decorator_list],
            "imports": imports,
            "variables": self.extract_variables(class_node.body),
            "other_methods": other_methods,
            "constructors": constructors,
        }

    def extract_signature(self, node, is_method=False):
        return {
            "name": node.name,
            "params": self.extract_params(node.args),
            "returns": ast.unparse(node.returns) if node.returns else "",
            "decorators": [self.format_decorator(decorator) for decorator in node.decorator_list],
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "is_method": is_method,
        }

    def extract_params(self, args):
        params = []

        positional_args = list(args.posonlyargs) + list(args.args)
        default_offset = len(positional_args) - len(args.defaults)

        for index, arg in enumerate(positional_args):
            default = args.defaults[index - default_offset] if index >= default_offset else None
            params.append(self.format_arg(arg, default=default))

        if args.vararg:
            params.append(self.format_arg(args.vararg, prefix="*"))

        if args.kwonlyargs:
            if not args.vararg:
                params.append("*")

            for arg, default in zip(args.kwonlyargs, args.kw_defaults):
                params.append(self.format_arg(arg, default=default))

        if args.kwarg:
            params.append(self.format_arg(args.kwarg, prefix="**"))

        return params

    def format_arg(self, arg, default=None, prefix=""):
        result = prefix + arg.arg

        if arg.annotation:
            result += f": {ast.unparse(arg.annotation)}"

        if default:
            result += f" = {ast.unparse(default)}"

        return result

    def extract_body(self, source, node):
        body_nodes = self.body_without_docstring(node.body)

        if not body_nodes:
            return "pass"

        lines = source.splitlines()
        start = min(body_node.lineno for body_node in body_nodes)
        end = max(getattr(body_node, "end_lineno", body_node.lineno) for body_node in body_nodes)

        return textwrap.dedent("\n".join(lines[start - 1:end])).rstrip()

    def extract_node_code(self, node):
        return ast.unparse(node)

    def body_without_docstring(self, body):
        body_nodes = list(body)

        if body_nodes and isinstance(body_nodes[0], ast.Expr):
            value = body_nodes[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                body_nodes = body_nodes[1:]

        return body_nodes

    def extract_imports(self, tree):
        imports = []

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(ast.unparse(node) + "\n")

        return imports

    def extract_variables(self, body):
        variables = []

        for node in body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                variables.append(ast.unparse(node))

        return variables

    def is_function(self, node):
        return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))

    def format_decorator(self, decorator):
        return "@" + ast.unparse(decorator)

    def format_docstring(self, doc):
        return f'"""{doc}"""' if doc else ""

    def module_name_from_path(self, rel_path):
        without_ext = os.path.splitext(rel_path)[0]
        return without_ext.replace(os.sep, ".")

    def qualified_name(self, node, class_node=None):
        return f"{class_node.name}.{node.name}" if class_node else node.name

    def import_path(self, rel_path, node, class_node=None):
        module_name = self.module_name_from_path(rel_path)
        return f"{module_name}.{self.qualified_name(node, class_node)}"
