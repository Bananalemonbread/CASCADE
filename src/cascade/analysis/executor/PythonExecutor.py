import ast
import os
import shutil
import tempfile
import textwrap

from cascade.analysis.executor.AnalysisExecutor import AnalysisExecutor
from cascade.analysis.executor.ExecutionResults import ExecutionResults
from cascade.analysis.executor.builders.PythonBuilder import PythonBuilder


class PythonExecutor(AnalysisExecutor):
    def __init__(self, debug=False, image="python:3.12", timeout=120, builder=None):
        super().__init__()
        self.debug = debug
        self.builder = builder or PythonBuilder(image=image, timeout=timeout)

    def execute(self, code: str, tests: str, context: dict, input_path, output_path):
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                shutil.copytree(input_path, temp_dir, dirs_exist_ok=True)
            except Exception as e:
                return self.build_execution_results(([], [], ["copy_project"]), comp_errors=str(e))

            modification_error = self.apply_code_and_tests(temp_dir, context, code, tests)
            if modification_error:
                return self.build_execution_results(([], [], ["modify_project"]), comp_errors=modification_error)

            test_file_path = self.get_test_file_path(context)
            test_command = self.builder.test_pattern.replace("%t", self.shell_quote(test_file_path))

            dock_context = {
                "image": self.builder.image,
                "directory": temp_dir,
                "command": (
                    f"cat -n {self.shell_quote(context['code_file_path'])}; "
                    f"cat -n {self.shell_quote(test_file_path)}; "
                    f"{test_command}"
                ),
                "eval_command": "cat out",
                "eval_function": self.builder.eval_function,
            }

            from cascade.utils.DockerizedWrapper import DockerizedWrapper

            result = DockerizedWrapper(debug=self.debug).execute(dock_context, output_path)

        return result

    def apply_code_and_tests(self, temp_dir, context, code_key, tests_key):
        if code_key not in context:
            return f"Missing code key in context: {code_key}"
        if tests_key not in context:
            return f"Missing tests key in context: {tests_key}"

        code_path = os.path.join(temp_dir, context["code_file_path"])
        test_path = os.path.join(temp_dir, self.get_test_file_path(context))

        try:
            self.replace_function_body(code_path, context, context[code_key])
            test_directory = os.path.dirname(test_path)
            if test_directory:
                os.makedirs(test_directory, exist_ok=True)
            with open(test_path, "w", encoding="utf-8") as f:
                f.write(self.normalize_tests(context[tests_key]))
        except Exception as e:
            return str(e)

        return None

    def replace_function_body(self, code_path, context, new_body):
        with open(code_path, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)
        target = self.find_target_function(tree, context)
        if target is None:
            return_name = context.get("qualified_name") or context["signature"]["name"]
            raise ValueError(f"Could not find Python function or method {return_name}")

        lines = source.splitlines()
        body_start, body_end = self.body_line_range(target)
        indent = " " * (target.col_offset + 4)
        replacement = self.indent_body(new_body, indent)

        lines[body_start - 1:body_end] = replacement

        with open(code_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def find_target_function(self, tree, context):
        signature_name = context["signature"]["name"]
        class_name = self.get_parent_class_name(context)

        if class_name:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == signature_name:
                            return child
            return None

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == signature_name:
                return node

        return None

    def get_parent_class_name(self, context):
        parents = context.get("parent", [])
        if isinstance(parents, dict):
            parents = [parents]

        for parent in reversed(parents):
            if parent.get("parent_type") == "Class":
                return parent.get("name")

        return None

    def body_line_range(self, function_node):
        body_nodes = list(function_node.body)
        docstring_node = body_nodes[0] if body_nodes and self.is_docstring_node(body_nodes[0]) else None
        if docstring_node:
            body_nodes = body_nodes[1:]

        if not body_nodes:
            if docstring_node:
                return docstring_node.end_lineno + 1, docstring_node.end_lineno
            return function_node.end_lineno, function_node.end_lineno

        return body_nodes[0].lineno, function_node.end_lineno

    def is_docstring_node(self, node):
        return (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )

    def indent_body(self, body, indent):
        body = textwrap.dedent(str(body)).strip("\n")
        if not body.strip():
            body = "pass"

        return [(indent + line) if line.strip() else "" for line in body.splitlines()]

    def normalize_tests(self, tests):
        if isinstance(tests, str):
            return tests.rstrip() + "\n"

        if isinstance(tests, list):
            snippets = []
            for test in tests:
                if isinstance(test, str):
                    snippets.append(test)
                elif isinstance(test, dict):
                    snippets.append(test.get("content") or test.get("code") or "")
            return "\n\n".join(snippet for snippet in snippets if snippet).rstrip() + "\n"

        return str(tests).rstrip() + "\n"

    def get_test_file_path(self, context):
        if context.get("test_file_path"):
            return context["test_file_path"]

        code_file_path = context["code_file_path"]
        directory = os.path.dirname(code_file_path)
        basename = os.path.basename(code_file_path)
        return os.path.join(directory, "test_" + basename)

    def build_execution_results(self, result, comp_errors=None, parsed_file=""):
        exec_results = ExecutionResults()
        exec_results.results = result
        exec_results.results_numbers = (
            len(result[0]),
            len(result[1]),
            len(result[2]),
        )
        exec_results.comp_errors = comp_errors
        exec_results.parsed_file = parsed_file or comp_errors or ""
        exec_results.comp_error_matches = [comp_errors] if comp_errors else []
        return exec_results

    def set_up(self, data, input_path, output_path):
        return True

    def tear_down(self, data):
        if self.builder:
            self.builder.tear_down(data)

    def shell_quote(self, value):
        return "'" + str(value).replace("'", "'\"'\"'") + "'"
