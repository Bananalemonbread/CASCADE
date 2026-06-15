import copy
import json
import os
import re
#import tiktoken

from cascade.generation.test.MultiStepTestGenerator import MultiStepTestGenerator
from cascade.utils.PythonUtils import build_context, check_syntax, repair_helper_functions, get_repair_helper_functions, \
    build_signature


class MultiStepPythonTestGenerator(MultiStepTestGenerator):
    code_block_names = ["python", "py"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


    def build_prompt(self, context):
        # enc = tiktoken.encoding_for_model(self.model)   # this could be used to ensure the prompt is not too long.

        test_framework_instruction = (
            "Use pytest. Do not use external testing libraries beyond pytest and the Python standard library."
        )

        par = context['signature']['params']
        params = ", ".join(par) if len(par) > 1 else (par[0] if par else "")

        system_prompt = (
            f"You are an expert Python developer. You will generate pytest tests for the specific function "
            f"{context['signature']['name']}({params}). "
            "Use pytest. Do not use external testing libraries beyond pytest and the Python standard library. "
            "You can import anything from the project itself. "
            "Make sure all function signatures and calls are correct. "
            "Handle exceptions, None, async behavior, and error cases appropriately when relevant. "
            "The code should run without syntax errors."
        )
        #
        class_level_prompt = (
            f"The interesting function under test is:\n"
            f"```python\n{build_signature(context, doc=True)}\n```\n\n"
            "Fill in pytest tests for the provided test module below. "
            "The tests should fail if the implementation does not exactly follow the documentation.\n\n"
            f"Python context:\n```python\n"
            f"{build_context(context, doc=True, imports=True, no_fields=False, no_other_method_docs=True, no_other_methods=True)}"
            f"\n```\n\n"
        )
        test_header = (
            "Add or adjust imports as needed. Use only pytest, the Python standard library, "
            "and imports from the project itself. Instantiate every object you use and call "
            "functions or methods with the correct Python signatures. "
            "Use the imports already present in the test module skeleton; do not guess alternate module names. "
            "Use pytest.raises for expected exceptions. If the function under test is async, "
            "write appropriate async pytest tests. "
            "Respond with the complete filled pytest test module only:\n"
        )

        test_level_prompt = test_header + "\n```python\n" + self.build_tests(context) + "\n```"

        prompt = class_level_prompt + test_level_prompt

        promptlist = []
        promptlist.append({"role": "system", "content": system_prompt})
        promptlist.append({"role": "user", "content": prompt})

        return promptlist


    def generate(self, context, input_path, output_path, response_step2=None):
        results_path = os.path.join(output_path, "results.txt")
        errors_path = os.path.join(output_path, "errors.txt")

        chat_history = []
        print("      Test generation Phase 1")
        # first given the method documentation and signature, we want to extract possible testcases or properties.
        prompt_step1 = [
            {"role": "system",
             "content": "You are an expert Python developer and requirements engineer. You will be given a method signature and its documentation. Your task is to extract behavior specifications from the documentation that can be turned into unit tests to ensure the code is bug free and faithful to its documentation."},
            {"role": "user",
             "content": f"Give a complete description of the behavior that we should test when we want to asure that the code matches its documentation from the following Python method:\n```Python\n{build_signature(context, doc=True)}\n```\n\nMake sure you consider the entire functionality exactly as described in the documentation, and cover all edge cases but make no assumptions that are not stated in the documentation."}
        ]

        chat_history.append(copy.deepcopy(prompt_step1))
        response_step1a = self.prompt_executor.execute(prompt_step1).model_dump()
        chat_history.append(response_step1a)

        if not response_step1a["choices"]:
            print("      error during generation")
            with open(errors_path, "a") as f:
                f.write(f"error during test generation of {context["signature"]["name"]}")

            return "", chat_history

        prompt_step1.append(response_step1a["choices"][0]["message"])

        # now the goal is to convert this text into a usable format and extract the testable properties
        prompt_json_list = {
            "role": "user",
            "content": (
                "Now turn this into a JSON array of pytest tests we should write for test driven development. "
                "Each entry should have \"test_name\": a descriptive snake_case pytest function name starting with 'test_', "
                "and \"test_description\": a detailed description..."
            )
        }

        prompt_step1.append(prompt_json_list)

        response_step1b = self.prompt_executor.execute(prompt_step1).model_dump()
        response_text = response_step1b["choices"][0]["message"]["content"]


        test_list = self.extract_json_list(output_path, response_text)

        chat_history.append(copy.deepcopy(prompt_step1))
        chat_history.append(response_step1b)

        if not test_list:
            with open(errors_path, "a") as f:
                f.write("error during test extraction from json")
            return "", chat_history


        context["test_list"] = test_list

        print("      Test generation Phase 2")
        # now we have a list of testable properties, we want to generate a testclass filled with these.
        prompt_step2 = self.build_prompt(context)

        response_step2a = self.prompt_executor.execute(prompt_step2).model_dump()

        prompt_step2.append(response_step2a["choices"][0]["message"])

        prompt_step2.append({
            "role": "user",
            "content": (
                "Make sure that this module is syntactically correct and pytest-runnable without errors. "
                "Keep the exact project import from the provided test module skeleton unless it is syntactically invalid. "
                "Check if everything that is used is imported correctly and all exceptions are properly caught. "
                "Reply with the complete corrected pytest test module only."
            )
        })

        response_step2b = self.prompt_executor.execute(prompt_step2).model_dump()
        chat_history.append(copy.deepcopy(prompt_step2))
        chat_history.append(response_step2b)

        new_tests = self.extract_tests(response_step2b["choices"][0]["message"]["content"], context, response_step2b, output_path)

        # this is a fallback if the second reply did not include a code block
        if new_tests == "":
            new_tests = self.extract_tests(response_step2a["choices"][0]["message"]["content"], context, response_step2b, output_path)
        # prompt_step2.append({"role": "assistant", "content": f"```python\n{new_tests}\n```"})

        if new_tests == "":
            with open(results_path, "w") as f:
                f.write("Negative, No syntactically correct test module generated")
            with open(errors_path, "w") as f:
                f.write(f"No syntactically correct test module generated \nResponse text:\n{response_text}")
        print("      Test generation finished")
        return new_tests, chat_history


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
    
    def check_syntax(self, code, output_path):
        raise NotImplementedError

    def check_generated_tests_syntax(self, code, output_path):
        return check_syntax(code, "module", output_path)


    def repair(self, context, input_path, output_path, errors, key):
        response_history = []
        tools = get_repair_helper_functions()
        #tools = None

        tree = self.source_tree(input_path, "*.py")

        system_prompt = "You are an expert Python developer. You will fix syntax, runtime and import errors in a provided test module and return the entire repaired module. Use tools to find out more about modules instead of making assumptions."

        prompt = (
            f"Some errors occurred while validating or running my pytest test module.\nErrors:\n```\n{errors}\n```\n\n"
            f"Test module:\n```python\n{context[key]}\n```\n"
            "Do not change the intended behavior of the tests, but make sure the module is syntactically valid "
            "and can run under pytest. Check imports, function calls, expected exceptions, and async handling. "
            f"If you need to add imports, use the following directory structure:\n```\n{tree}\n```\n\n"
            "Now fix the module and respond with the entire corrected pytest test module only."
        )

        promptlist = []
        promptlist.append({"role": "system", "content": system_prompt})
        promptlist.append({"role": "user", "content": prompt})

        res = self.prompt_executor.execute(promptlist, tools=tools).model_dump()
        response_history.append(copy.deepcopy(promptlist))
        response_history.append(res)
        # we allow three tool usages before we force a generation
        steps = 3
        for i in range(steps):
            if res["choices"][0]["finish_reason"] == "tool_calls":
                promptlist.append(res['choices'][0]['message'])

                tool_calls = res["choices"][0]["message"]["tool_calls"]

                for tool_call in tool_calls:
                    func = tool_call["function"]["name"]
                    arguments = tool_call["function"]["arguments"]

                    results = repair_helper_functions(func, arguments, input_path, output_path, context)

                    promptlist.append({"role": "tool", "content": json.dumps(results), "tool_call_id": tool_call["id"]})

                if i < steps - 1:
                    res = self.prompt_executor.execute(promptlist, tools=tools).model_dump()
                else:
                    res = self.prompt_executor.execute(promptlist).model_dump()
                response_history.append(copy.deepcopy(promptlist))
                response_history.append(res)

        promptlist.append(res['choices'][0]['message'])
        new_tests = res["choices"][0]["message"]["content"]

        new_tests = self.extract_tests(new_tests, context, res, output_path)

        response_history.append(copy.deepcopy(promptlist))
        response_history.append(res)
        return new_tests, response_history
