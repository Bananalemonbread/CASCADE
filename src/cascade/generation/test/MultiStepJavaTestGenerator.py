import copy
import json
import os
import re
#import tiktoken

from cascade.generation.test.MultiStepTestGenerator import MultiStepTestGenerator
from cascade.utils.JavaUtils import build_context, check_syntax, repair_helper_functions, get_repair_helper_functions, \
    build_signature


class MultiStepJavaTestGenerator(MultiStepTestGenerator):
    code_block_names = ["java"]
    language_name = "Java"
    signature_block_name = "java"
    test_artifact_name = "test class"
    test_kind_name = "unit tests"
    test_name_rule = "a descriptive test method name starting with 'test'"


    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.is_junit3 = False

    def build_prompt(self, context):
        # enc = tiktoken.encoding_for_model(self.model)   # this could be used to ensure the prompt is not too long.

        test_framework_instruction = ""
        if "junit_version" in context:
            version = context["junit_version"]
            test_framework_instruction = " Use JUnit version " + (version if version[0].isdigit() else "5") + "."

        par = context['signature']['params']
        params = ", ".join(par) if len(par) > 1 else (par[0] if par else "")

        system_prompt = (
            f"You are an expert Java developer. You will generate JUnit tests for a specific method in a provided test class.{test_framework_instruction} "
            "You can import anything from the project itself. Make sure to handle all exceptions properly, and ensure that all method signatures and calls are correct. "
            "The code should compile on its own without errors."
            )

        #
        class_level_prompt = (
            f"The interesting function under test is:\n```Java\n{build_signature(context, doc=True)}```\n\nThe other methods will be tested later. " 
            "Fill all tests in the provided test class below. This is for test driven development so the tests should be designed to fail if the later implementation does not exactly conform to the documentation.\n"
            f"This is the parent class the method under test resides in:\n## Parent class\n```java\n{build_context(context, doc=True, imports=True, no_fields=False, no_constructors=False, no_other_method_docs=True, no_other_methods=True)}"
            " {\n        // this is the function to be tested\n\n}\n}\n```\n\n"
            )

        test_header = (
            "Make changes or add classes to the imports if necessary. Every object you use has to be properly instantiated, every method has to be imported. "
            "Handle any checked exceptions using try-catch or throws, do not forget type parameters. Match method signatures exactly when overriding or implementing methods. "
            f"Respond with the filled Test Class:\n"
            )

        test_level_prompt = test_header + "\n```java\n" + self.build_tests(context) + "\n```"

        prompt = class_level_prompt + test_level_prompt

        promptlist = []
        promptlist.append({"role": "system", "content": system_prompt})
        promptlist.append({"role": "user", "content": prompt})

        return promptlist
    

    def build_tests(self, context):
        packg_declaration = f"package {context['test_package']};\n\n"
        imports = "".join(context["test_imports"]) + "\n" + "// add all other needed imports here\n\n"

        # check if we are using junit 3 as there is a difference in structure
        for import_ in context["test_imports"]:
            if ("junit.framework") in import_:
                self.is_junit3 = True
                break

        #class_name = context["test_file_path"].split("/")[-1].split(".")[0]
        class_name = os.path.splitext(os.path.basename(context["test_file_path"]))[0]

        functions = ""
        if self.is_junit3:
            class_definition = f"public class {class_name} extends TestCase {{"
            test_suite_method = f"\n    public {class_name}(String testName) {{\n        super(testName);\n    }}\n\n    public static Test suite() {{\n        return new TestSuite({class_name}.class);\n    }}\n"

            class_definition = class_definition + test_suite_method

            for test in context["test_list"]:
                functions += f"\n    public void {test['test_name']}() {{\n        // {test['test_description']}\n    }}\n\n"

        else:
            class_definition = f"public class {class_name} {{"

            for test in context["test_list"]:
                functions += f"\n    @Test\n    public void {test['test_name']}() {{\n        // {test['test_description']}\n    }}\n\n"

        return packg_declaration + imports + class_definition + functions + "\n}"


    def build_signature(self, context, doc=True):
        return build_signature(context, doc=doc)


    def build_context(self, context, *args, **kwargs):
        return build_context(context, *args, **kwargs)

    
    def check_syntax(self, code, output_path):
        raise NotImplementedError

    def check_generated_tests_syntax(self, code, output_path):
        return check_syntax(code, "class", output_path)


    def repair(self, context, input_path, output_path, errors, key):
        response_history = []
        tools = get_repair_helper_functions()
        #tools = None

        tree = self.source_tree(input_path, "*.java")

        system_prompt = "You are an expert Java developer. You will fix compilation errors in a provided test class and return the entire repaired class. Use tools to find out more about classes instead of making assumptions."

        prompt = (f"During the compilation of my test class some errors occurred.\nErrors:\n```\n{errors}\n```\n\nTest Class:\n```java\n{context[key]}\n```\n"
                  "Dont change the content of the tests, but make sure that the class compiles without errors. " 
                  "Check if all necessary imports are present and if all exceptions are properly caught. "
                  f"If you need to add imports, use the following directory structure:\n```\n{tree}\n```\n\nNow fix the class so that it compiles without errors, and respond with the entire fixed class."
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
