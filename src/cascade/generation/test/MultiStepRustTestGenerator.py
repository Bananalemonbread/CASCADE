import copy
import os
import re
import subprocess

from cascade.generation.test.MultiStepTestGenerator import MultiStepTestGenerator
from cascade.utils.RustUtils import build_context, check_syntax, \
build_signature


def is_public(c) -> bool:
    return False #TODO: later refactor lol...
    #return "pub" in c["signature"]["modifier"]

class MultiStepRustTestGenerator(MultiStepTestGenerator):
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

    def build_prompt(self, context):
        test_framework_instruction = (
            "Use Rust's built-in test framework with #[test] and cargo test. "
            "Do not use external test crates such as rstest, proptest, quickcheck, or quicktest."
        )

        par = context['signature']['params']
        params = ", ".join(par) if len(par) > 1 else (par[0] if par else "")

        system_prompt = (
            f"You are an expert Rust developer. You will generate unit tests for the specific function "
            f"{context['signature']['name']}({params}). {test_framework_instruction} "
            "You can import anything from the project itself. "
            "Make sure all function signatures and calls are correct. "
            "Handle Result, Option, panic behavior, and error cases appropriately when relevant. "
            "The code should compile on its own without errors."
        )

        class_level_prompt = (
            f"The interesting function under test is:\n"
            f"```rust\n{build_signature(context, doc=True)}\n```\n\n"
            "The other functions will be tested later. "
            "Fill in Rust unit tests for the provided test module below. "
            "This is for test driven development, so the tests should be designed to fail if the later implementation does not exactly conform to the documentation.\n\n"
            f"This is the parent module or item context the function under test resides in:\n"
            f"## Parent context\n"
            f"```rust\n"
            f"{build_context(context, doc=True, no_fields=False, no_other_method_docs=True, no_other_methods=True)}"
            f"\n```\n\n"
        )
            
        test_header = (
            "Add any necessary `use` statements from the project itself. "
            "Every value you use must be properly constructed. "
            "Match function signatures and calls exactly, including ownership, borrowing, lifetimes, generics, and trait bounds. "
            "Handle Result, Option, panic behavior, and error cases appropriately when relevant. "
            "Use idiomatic Rust assertions such as assert!, assert_eq!, assert_ne!, matches!, and unwrap_err() where appropriate. "
            "Respond with the filled Rust test module only:\n"
        )
        
        test_level_prompt = test_header + "\n```rust\n" + self.build_tests(context) + "\n```"

        prompt = class_level_prompt + test_level_prompt

        promptlist = []
        promptlist.append({"role": "system", "content": system_prompt})
        promptlist.append({"role": "user", "content": prompt})

        return promptlist
    
    def generate(self, context, input_path, output_path, response_step2=None):
        results_path = os.path.join(output_path, "results.txt")
        errors_path = os.path.join(output_path, "errors.txt")

        chat_history = []
        print("     Test generation Phase 1")
        # first given the method documentation and signature, we want to extract possible testcases or properties.
        prompt_step1 = [
            {"role": "system",
             "content": "You are an expert Rust developer and requirements engineer. You will be given a method signature and its documentation. Your task is to extract behavior specifications from the documentation that can be turned into unit tests to ensure the code is bug free and faithful to its documentation."},
            {"role": "user",
             "content": f"Give a complete description of the behavior that we should test when we want to asure that the code matches its documentation from the following Rust method:\n```Rust\n{build_signature(context, doc=True)}\n```\n\nMake sure you consider the entire functionality exactly as described in the documentation, and cover all edge cases but make no assumptions that are not stated in the documentation."}           
        ]

        chat_history.append(copy.deepcopy(prompt_step1))
        response_step1a = self.prompt_executor.execute(prompt_step1).model_dump()

        if not response_step1a["choices"]:
            print("     error during generation")
            with open (errors_path, "a") as f:
                f.write(f"error during test generation of {context["signature"]["name"]}")

            return "", chat_history
        
        prompt_step1.append(response_step1a["choices"][0]["message"])

        # now the goal is to convert this text into a usable format and extract the testable properties
        prompt_json_list = {
            "role": "user",
            "content": (
                "Now turn this into a JSON array of Rust tests we should write for test driven development. "
                "Each entry in the array should have: \"test_name\": a descriptive Rust test method name in snake_case starting with 'test_', "
                "and \"test_description\": a detailed description for the developer of what this tests should do and which specific behavior from the documentation it tests. In particular, I want testable statements of the 'if this then that' type.\nFocus on those tests that follow directly from the documentation, e.g. no performance based ones."
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

        print("     Test generation Phase 2")
        # now we have a list of testable properties we want to generate a Rust test filled with these
        prompt_step2 = self.build_prompt(context)

        response_step2a = self.prompt_executor.execute(prompt_step2).model_dump()

        prompt_step2.append(response_step2a["choices"][0]["message"])

        prompt_step2.append({
            "role": "user",
            "content": (
                "Make sure that this Rust test module compiles without errors. "
                "Check imports, module paths, ownership, borrowing, lifetimes, generics, trait bounds, Result, Option, and panic behavior. "
                "Reply with the corrected Rust test module only."
            )
        })

        response_step2b = self.prompt_executor.execute(prompt_step2).model_dump()
        chat_history.append(copy.deepcopy(prompt_step2))
        chat_history.append(response_step2b)

        new_tests = self.extract_tests(response_step2b["choices"][0]["message"]["content"], context, response_step2b, output_path)

        # this is a fallback if the second reply did not include a code block
        if new_tests == "":
            new_tests = self.extract_tests(response_step2a["choices"][0]["message"]["content"], context, response_step2b, output_path)
        

        if new_tests == "":
            with open(results_path, "w") as f:
                f.write("Negative, No syntactically correct Rust test module generated")
            with open(errors_path, "w") as f:
                f.write(f"No syntactically correct Rust test module generated \nResponse text:\n{response_text}")
        print("     Test generation finished")
        return new_tests, chat_history
    
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
    
    def extract_tests(self, new_tests, context, response, output_path):
        code_blocks = re.findall(r"```rust(.*?)\n\s*```", new_tests, flags=re.DOTALL)
        new_tests = ""

        if code_blocks:
            sorted_code_blocks = sorted(code_blocks, key=len, reverse=True)
            for code_block in sorted_code_blocks:
                if check_syntax(code_block, output_path):
                    new_tests = code_block
                    break
        else:
            print("     no code block could be extracted for generated Tests")
            errors_path = os.path.join(output_path, "errors.txt")
            with open(errors_path, "a") as f:
                f.write(f"Could not get tests from response: \n{response}")

        return new_tests

    def repair(self, context, input_path, output_path, errors, key):
        response_history = []

        tree = subprocess.check_output(["tree", "-P", "*.rs", "--charset=ascii", input_path]).decode("utf-8")

        system_prompt = (
            "You are an expert Rust developer. "
            "You will fix compilation errors in a provided Rust test module and return the entire repaired module."
        )

        prompt = (
            f"During compilation of my Rust tests some errors occurred.\n"
            f"Errors:\n```\n{errors}\n```\n\n"
            f"Rust test module:\n```rust\n{context[key]}\n```\n"
            "Do not change the intended behavior of the tests, but make sure the test module compiles. "
            "Check imports, module paths, ownership, borrowing, lifetimes, generics, trait bounds, Result, Option, and panic behavior. "
            f"If you need to add imports, use the following Rust source tree:\n```\n{tree}\n```\n\n"
            "Now fix the Rust test module and respond with the entire fixed Rust code only."
        )

        promptlist = []
        promptlist.append({"role": "system", "content": system_prompt})
        promptlist.append({"role": "user", "content": prompt})

        steps = 3
        last_new_tests = ""

        for i in range(steps):
            res = self.prompt_executor.execute(promptlist).model_dump()

            response_history.append(copy.deepcopy(promptlist))
            response_history.append(res)

            if not res["choices"]:
                break

            assistant_message = res["choices"][0]["message"]
            promptlist.append(assistant_message)

            new_tests = assistant_message["content"]
            extracted_tests = self.extract_tests(new_tests, context, res, output_path)

            if extracted_tests:
                return extracted_tests, response_history

            last_new_tests = new_tests

            if i < steps - 1:
                promptlist.append({
                    "role": "user",
                    "content": (
                        "The previous answer did not contain syntactically valid Rust test code. "
                        "Please return one complete Rust test module only, inside a ```rust code block. "
                        "Do not include explanations."
                    )
                })

        return last_new_tests, response_history
