from cascade.extraction.Extraction import Extraction
from typing import List, Dict
from cascade.extraction.JsonExtraction import JsonExtraction
from cascade.utils.Utils import save_dicts_list_to_json
import ast
import os

class PythonExtraction(Extraction):
    def __init__(self, pattern: str = "test_/%c.py"):
        """
        Extracts Python functions and methods from a Python project.

        :param pattern: Pattern used to infer test files from source files.
        """
        super().__init__()
        self.pattern = pattern

    def extract(self, input_path, output_path) -> List[Dict[str, any]]:
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

        for root, dirs, files in os.walk(input_path):
            for file in files:
                if not file.endswith(".py"):
                    continue
                if file.startswith("test_"):
                    continue

                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, input_path)

                with open(path, "r", encoding="utf-8") as f:
                    source = f.read()

                tree = ast.parse(source)

                for node in tree.body:
                    if isinstance(node, ast.FunctionDef):
                        extracted.append({
                            "language": "Python",
                            "doc": ast.get_docstring(node) or "",
                            "signature": {
                                "name": node.name,
                                "params": [arg.arg for arg in node.args.args],
                                "returns": ast.unparse(node.returns) if node.returns else "",
                                "decorators": [ast.unparse(d) for d in node.decorator_list],
                                "is_async": False
                            },
                            "parent": [{
                                "name": "root module",
                                "parent_type": "Module",
                                "imports": [],
                                "variables": [],
                                "other_methods": [],
                                "constructors": []
                            }],
                            "code": ast.unparse(node),
                            "code_file_path": rel_path,
                            "code_file_content": source,
                            "tests": [],
                            "called_functions": []
                        })

        save_dicts_list_to_json(extracted, os.path.join(output_path, "extracted.json"))
        return extracted