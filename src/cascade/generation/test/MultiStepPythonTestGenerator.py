import re
#import tiktoken

from cascade.generation.test.MultiStepTestGenerator import MultiStepTestGenerator
from cascade.utils.PythonUtils import build_context, check_syntax, repair_helper_functions, get_repair_helper_functions, \
    build_signature


class MultiStepPythonTestGenerator(MultiStepTestGenerator):
    code_block_names = ["python", "py"]
    language_name = "Python"
    signature_block_name = "python"
    test_artifact_name = "test module"
    test_kind_name = "pytest tests"
    test_name_rule = "a descriptive snake_case pytest function name starting with 'test_'"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


    def test_generation_system_prompt(self, context):
        test_framework_instruction = (
            "Use pytest. Do not use external testing libraries beyond pytest and the Python standard library."
        )

        par = context['signature']['params']
        params = ", ".join(par) if len(par) > 1 else (par[0] if par else "")

        return (
            f"You are an expert Python developer. You will generate pytest tests for the specific function "
            f"{context['signature']['name']}({params}). "
            f"{test_framework_instruction} "
            "You can import anything from the project itself. "
            "Make sure all function signatures and calls are correct. "
            "Handle exceptions, None, async behavior, and error cases appropriately when relevant. "
            "The code should run without syntax errors."
        )


    def test_generation_context_prompt(self, context):
        return (
            f"The interesting function under test is:\n"
            f"```python\n{self.build_signature(context, doc=True)}\n```\n\n"
            "Fill in pytest tests for the provided test module below. "
            "The tests should fail if the implementation does not exactly follow the documentation.\n\n"
            f"Python context:\n```python\n"
            f"{self.build_context(context, doc=True, imports=True, no_fields=False, no_other_method_docs=True, no_other_methods=True)}"
            f"\n```\n\n"
        )


    def test_generation_test_header(self, context):
        return (
            "Add or adjust imports as needed. Use only pytest, the Python standard library, "
            "and imports from the project itself. Instantiate every object you use and call "
            "functions or methods with the correct Python signatures. "
            "Use the imports already present in the test module skeleton; do not guess alternate module names. "
            "Use pytest.raises for expected exceptions. If the function under test is async, "
            "write appropriate async pytest tests. "
            "Respond with the complete filled pytest test module only:\n"
        )

    def build_tests(self, context):
        imports = "".join(context.get("test_imports",[]))

        if imports and not imports.endswith("\n"):
            imports += "\n"

        if "import pytest\n" not in imports and "import pytest\r\n" not in imports:
            imports += "import pytest\n"

        target_import = self.build_target_import(context)
        if target_import and target_import not in imports:
            imports += target_import

        imports += "\n# add all other needed imports here\n\n"

        functions = ""
        for test in context["test_list"]:
            test_name = self.to_python_test_name(test["test_name"])
            test_description = test["test_description"].replace('"""', '\\"\\"\\"')

            functions += (
                f"def {test_name}():\n"
                f"    \"\"\"{test_description}\"\"\"\n"
                f"    pass\n\n"
            )

        return imports + functions.rstrip() + "\n"
    
    def build_target_import(self, context):
        signature = context.get("signature", {})
        function_name = signature.get("name")
        if not function_name or signature.get("is_method"):
            return ""

        module_name = context.get("module_name")
        if module_name:
            return f"from {module_name} import {function_name}\n"

        import_path = context.get("import_path", "")
        if "." in import_path:
            module_path, name = import_path.rsplit(".", 1)
            if name == function_name:
                return f"from {module_path} import {function_name}\n"

        return ""


    def to_python_test_name(self, name):
        name = re.sub(r"[^0-9a-zA-Z_]+", "_", str(name)).strip("_")
        if not name.startswith("test_"):
            name = "test_" + name.removeprefix("test").strip("_")
        return name.lower() or "test_generated_case"

    def normalize_test_name(self, name):
        return self.to_python_test_name(name)

    def duplicate_test_name(self, name, count):
        return f"{name}_{count}"


    def build_signature(self, context, doc=True):
        return build_signature(context, doc=doc)


    def build_context(self, context, *args, **kwargs):
        return build_context(context, *args, **kwargs)
    
    def check_generated_tests_syntax(self, code, output_path):
        return check_syntax(code, "module", output_path)


    def repair_source_pattern(self):
        return "*.py"


    def repair_system_prompt(self):
        return (
            "You are an expert Python developer. You will fix syntax, runtime and import errors in a provided "
            "test module and return the entire repaired module. Use tools to find out more about modules instead of making assumptions."
        )


    def repair_user_prompt(self, context, errors, key, tree):
        return (
            f"Some errors occurred while validating or running my pytest test module.\nErrors:\n```\n{errors}\n```\n\n"
            f"Test module:\n```python\n{context[key]}\n```\n"
            "Do not change the intended behavior of the tests, but make sure the module is syntactically valid "
            "and can run under pytest. Check imports, function calls, expected exceptions, and async handling. "
            f"If you need to add imports, use the following directory structure:\n```\n{tree}\n```\n\n"
            "Now fix the module and respond with the entire corrected pytest test module only."
        )


    def get_repair_tools(self):
        return get_repair_helper_functions()


    def run_repair_helper(self, func, arguments, input_path, output_path, context):
        return repair_helper_functions(func, arguments, input_path, output_path, context)
