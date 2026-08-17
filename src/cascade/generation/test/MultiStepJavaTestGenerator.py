import os

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

    def test_generation_system_prompt(self, context):
        test_framework_instruction = ""
        if "junit_version" in context:
            version = context["junit_version"]
            test_framework_instruction = " Use JUnit version " + (version if version[0].isdigit() else "5") + "."

        return (
            f"You are an expert Java developer. You will generate JUnit tests for a specific method in a provided test class.{test_framework_instruction} "
            "You can import anything from the project itself. Make sure to handle all exceptions properly, and ensure that all method signatures and calls are correct. "
            "The code should compile on its own without errors."
        )
    
    def test_generation_context_prompt(self, context):
        return (
            f"The interesting function under test is:\n```java\n{self.build_signature(context, doc=True)}```\n\n"
            "The other methods will be tested later. "
            "Fill all tests in the provided test class below. This is for test driven development so the tests should be designed to fail if the later implementation does not exactly conform to the documentation.\n"
            f"This is the parent class the method under test resides in:\n## Parent class\n```java\n"
            f"{self.build_context(context, doc=True, imports=True, no_fields=False, no_constructors=False, no_other_method_docs=True, no_other_methods=True)}"
            " {\n        // this is the function to be tested\n\n}\n}\n```\n\n"
        )
    

    def test_generation_test_header(self, context):
        return (
            "Make changes or add classes to the imports if necessary. Every object you use has to be properly instantiated, every method has to be imported. "
            "Handle any checked exceptions using try-catch or throws, do not forget type parameters. Match method signatures exactly when overriding or implementing methods. "
            "Respond with the filled Test Class:\n"
        )

    def build_tests(self, context):
        packg_declaration = f"package {context['test_package']};\n\n"
        imports = "".join(context["test_imports"]) + "\n" + "// add all other needed imports here\n\n"

        self.is_junit3 = any(
            "junit.framework" in import_
            for import_ in context["test_imports"]
        )

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

    
    def check_generated_tests_syntax(self, code, output_path):
        return check_syntax(code, "class", output_path)


    def repair_source_pattern(self):
        return "*.java"


    def repair_system_prompt(self):
        return (
            "You are an expert Java developer. You will fix compilation errors in a provided test class "
            "and return the entire repaired class. Use only the supplied errors, test class, and source-tree "
            "context; do not request or call tools."
        )


    def repair_user_prompt(self, context, errors, key, tree):
        return (
            f"During the compilation of my test class some errors occurred.\nErrors:\n```\n{errors}\n```\n\n"
            f"Test Class:\n```java\n{context[key]}\n```\n"
            "Dont change the content of the tests, but make sure that the class compiles without errors. "
            "Check if all necessary imports are present and if all exceptions are properly caught. "
            f"If you need to add imports, use the following directory structure:\n```\n{tree}\n```\n\n"
            "Now fix the class so that it compiles without errors, and respond with the entire fixed class."
        )


    def get_repair_tools(self):
        return get_repair_helper_functions()


    def run_repair_helper(self, func, arguments, input_path, output_path, context):
        return repair_helper_functions(func, arguments, input_path, output_path, context)
