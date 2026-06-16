from cascade.generation.test.MultiStepTestGenerator import MultiStepTestGenerator
from cascade.utils.CSharpUtils import build_context, build_signature, build_tests, check_syntax, csharp_test_name


class MultiStepCSharpTestGenerator(MultiStepTestGenerator):
    code_block_names = ["csharp", "cs"]
    language_name = "C#"
    signature_block_name = "csharp"
    test_artifact_name = "C# test class"
    test_kind_name = "C# unit tests"
    test_name_rule = "a descriptive C# test method name"

    def __init__(self, tool_path=None, **kwargs):
        super().__init__(**kwargs)
        self.tool_path = tool_path

    def normalize_test_name(self, name):
        return csharp_test_name(name)

    def duplicate_test_name(self, name, count):
        return f"{name}{count}"

    def test_generation_system_prompt(self, context):
        framework = self.test_framework_name(context)
        params = ", ".join(context["signature"].get("params", []))
        return (
            f"You are an expert C# developer. You will generate {framework} tests for the specific method "
            f"{context['signature']['name']}({params}). "
            "You can import anything from the project itself. "
            "Make sure all method signatures and calls are correct. "
            "Handle exceptions, nullable values, async behavior, and error cases appropriately when relevant. "
            "The code should compile on its own without errors."
        )

    def test_generation_context_prompt(self, context):
        return (
            f"The interesting method under test is:\n"
            f"```csharp\n{self.build_signature(context, doc=True)}\n```\n\n"
            "The other methods will be tested later. "
            "Fill in C# unit tests for the provided test class below. "
            "This is for test driven development, so the tests should be designed to fail if the later implementation "
            "does not exactly conform to the documentation.\n\n"
            f"This is the parent class the method under test resides in:\n"
            f"## Parent class\n"
            f"```csharp\n"
            f"{self.build_context(context, doc=True, no_fields=False, no_constructors=False, no_other_method_docs=True, no_other_methods=True)}"
            "\n    {\n        // this is the method to be tested\n    }\n}\n"
            "```\n\n"
        )

    def test_generation_test_header(self, context):
        return (
            "Add or adjust using directives as needed. Use only the configured C# test framework, "
            "the .NET standard libraries, and imports from the project itself. Instantiate every object you use. "
            "Match method signatures and calls exactly, including generics, overloads, async/await, nullable values, "
            "and exceptions. Respond with the complete filled C# test class only:\n"
        )

    def build_tests(self, context):
        return build_tests(context)

    def build_signature(self, context, doc=True):
        return build_signature(context, doc=doc)

    def build_context(self, context, *args, **kwargs):
        return build_context(context, *args, **kwargs)

    def check_generated_tests_syntax(self, code, output_path):
        return check_syntax(code, output_path, tool_path=self.tool_path)

    def repair_source_pattern(self):
        return "*.cs"

    def repair_system_prompt(self):
        return (
            "You are an expert C# developer. You will fix compilation errors in a provided C# test class "
            "and return the entire repaired class."
        )

    def repair_user_prompt(self, context, errors, key, tree):
        return (
            f"During compilation of my C# test class some errors occurred.\n"
            f"Errors:\n```\n{errors}\n```\n\n"
            f"C# test class:\n```csharp\n{context[key]}\n```\n"
            "Do not change the intended behavior of the tests, but make sure the class compiles. "
            "Check using directives, namespaces, object construction, method calls, async/await, generics, nullable values, "
            "and expected exceptions. "
            f"If you need to add imports, use the following C# source tree:\n```\n{tree}\n```\n\n"
            "Now fix the C# test class and respond with the entire fixed C# code only."
        )

    def test_framework_name(self, context):
        test = (context.get("tests") or [{}])[0]
        return test.get("test_runner") or context.get("test_runner") or "xUnit"
