import re

from cascade.generation.test.MultiStepTestGenerator import MultiStepTestGenerator
from cascade.utils.RustUtils import build_context, check_syntax, \
build_signature


def is_public(c) -> bool:
    return False #TODO: later refactor lol...
    #return "pub" in c["signature"]["modifier"]

class MultiStepRustTestGenerator(MultiStepTestGenerator):
    code_block_names = ["rust"]
    language_name = "Rust"
    signature_block_name = "rust"
    test_artifact_name = "Rust test module"
    test_kind_name = "Rust tests"
    test_name_rule = "a descriptive Rust test method name in snake_case starting with 'test_'"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def normalize_test_name(self, name):
        name = str(name).strip()
        name = re.sub(r"^(test_?|Test_?|TEST_?)", "", name)
        name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
        name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
        name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        name = re.sub(r"_+", "_", name).strip("_").lower()

        if not name:
            name = "generated_case"
        if name[0].isdigit():
            name = "case_" + name

        return "test_" + name

    def duplicate_test_name(self, name, count):
        return f"{name}_{count}"

    def test_generation_system_prompt(self, context):
        test_framework_instruction = (
            "Use Rust's built-in test framework with #[test] and cargo test. "
            "Do not use external test crates such as rstest, proptest, quickcheck, or quicktest."
        )

        par = context['signature']['params']
        params = ", ".join(par) if len(par) > 1 else (par[0] if par else "")

        return (
            f"You are an expert Rust developer. You will generate unit tests for the specific function "
            f"{context['signature']['name']}({params}). {test_framework_instruction} "
            "You can import anything from the project itself. "
            "Make sure all function signatures and calls are correct. "
            "Handle Result, Option, panic behavior, and error cases appropriately when relevant. "
            "The code should compile on its own without errors."
        )


    def test_generation_context_prompt(self, context):
        return (
            f"The interesting function under test is:\n"
            f"```rust\n{self.build_signature(context, doc=True)}\n```\n\n"
            "The other functions will be tested later. "
            "Fill in Rust unit tests for the provided test module below. "
            "This is for test driven development, so the tests should be designed to fail if the later implementation does not exactly conform to the documentation.\n\n"
            f"This is the parent module or item context the function under test resides in:\n"
            f"## Parent context\n"
            f"```rust\n"
            f"{self.build_context(context, doc=True, no_fields=False, no_other_method_docs=True, no_other_methods=True)}"
            f"\n```\n\n"
        )


    def test_generation_test_header(self, context):
        return (
            "Add any necessary `use` statements from the project itself. "
            "Every value you use must be properly constructed. "
            "Match function signatures and calls exactly, including ownership, borrowing, lifetimes, generics, and trait bounds. "
            "Handle Result, Option, panic behavior, and error cases appropriately when relevant. "
            "Use idiomatic Rust assertions such as assert!, assert_eq!, assert_ne!, matches!, and unwrap_err() where appropriate. "
            "Respond with the filled Rust test module only:\n"
        )

    def check_generated_tests_syntax(self, code, output_path):
        return check_syntax(code, output_path)


    def build_signature(self, context, doc=True):
        return build_signature(context, doc=doc)


    def build_context(self, context, *args, **kwargs):
        return build_context(context, *args, **kwargs)


    def repair_source_pattern(self):
        return "*.rs"


    def repair_system_prompt(self):
        return (
            "You are an expert Rust developer. "
            "You will fix compilation errors in a provided Rust test module and return the entire repaired module."
        )


    def repair_user_prompt(self, context, errors, key, tree):
        return (
            f"During compilation of my Rust tests some errors occurred.\n"
            f"Errors:\n```\n{errors}\n```\n\n"
            f"Rust test module:\n```rust\n{context[key]}\n```\n"
            "Do not change the intended behavior of the tests, but make sure the test module compiles. "
            "Check imports, module paths, ownership, borrowing, lifetimes, generics, trait bounds, Result, Option, and panic behavior. "
            f"If you need to add imports, use the following Rust source tree:\n```\n{tree}\n```\n\n"
            "Now fix the Rust test module and respond with the entire fixed Rust code only."
        )


    def build_tests(self, context):
        functions = ""

        for test in context["test_list"]:
            functions += (
                f"\n    #[test]\n"
                f"      fn {test['test_name']}() {{\n"
                f"      // {test['test_description']}\n"
                f"      }}\n"
            )

        return (
            "#[cfg(test)]\n"
            "mod injected_test_mod_cascade {\n"
            "   use super::*;\n"
            f"{functions}"
            "}\n"
        )
