import os
import re
import json
import fnmatch
import shutil
import subprocess

from cascade.generation.Generator import Generator
from cascade.generation.executor.OpenAICaller import OpenAICaller

class MultiStepTestGenerator(Generator):
    code_block_names = []

    def __init__(self,
                 model="gpt-4o-mini-2024-07-18",
                 max_attempts=1, delay=3,
                 max_tokens=16000,
                 temperature=0,
                 max_prompt_tokens=8000,
                 freq_penalty=0.0, dummy=False,
                 base_url=None, api_key=None
                ):
        super().__init__()
        self.prompt_executor = OpenAICaller(
            max_attempts=max_attempts,
            model=model,
            delay=delay,
            max_tokens=max_tokens,
            temperature=temperature,
            freq_penalty=freq_penalty,
            dummy=dummy,
            base_url=base_url,
            api_key=api_key
        )
        self.model = model
        self.max_prompt_tokens = max_prompt_tokens
    

    def generate(self, context, input_path, output_path,  response_step2=None):
        raise NotImplementedError

    def build_prompt(self, context):
        raise NotImplementedError

    def check_generated_tests_syntax(self, code, output_path):
        raise NotImplementedError

    def extract_tests(self, new_tests, context, response, output_path):
        pattern = r"```(?:" + "|".join(self.code_block_names) + r")(.*?)\n\s*```"
        code_blocks = re.findall(pattern, new_tests, flags=re.DOTALL)
        extracted_tests = ""

        if code_blocks:
            sorted_code_blocks = sorted(code_blocks, key=len, reverse=True)
            for code_block in sorted_code_blocks:
                if self.check_generated_tests_syntax(code_block, output_path):
                    extracted_tests = code_block
                    break
        else:
            print("      no code block could be extracted for generated Tests")
            errors_path = os.path.join(output_path, "errors.txt")
            with open(errors_path, "a") as f:
                f.write(f"Could not get tests from response:\n{response}")


        return extracted_tests

    def repair(self, context, input_path, output_path, errors, key):
        raise NotImplementedError

    def extract_json_list(self, output_path, response_text):
        # extract json list from response
        def log_json_error(error_message):
            """Logs the JSON error to results.txt and errors.txt"""
            print(error_message)
            results_path = os.path.join(output_path, "results.txt")
            errors_path = os.path.join(output_path, "errors.txt")
            
            with open(results_path, "w") as f:
                f.write("Negative, JSON test extraction error")
            with open(errors_path, "w") as f:
                f.write(f"Could not parse JSON: {error_message}\nResponse text:\n{response_text}")

        json_blocks = re.findall(r"```json\s*(.*?)\s*```", response_text, flags=re.DOTALL)
        json_text = json_blocks[0].strip() if json_blocks else response_text.strip()

        try:
            extracted_test_list = json.loads(json_text)

        except json.JSONDecodeError as e:
            log_json_error(str(e))
            return []

        if not isinstance(extracted_test_list, list):
            log_json_error("Extracted JSON is not a list")
            return []

        clean_test_list = []
        seen_names = {}
        for et in extracted_test_list:
            if not isinstance(et, dict):
                continue

            if "test_name" in et and "test_description" in et:
                base_name = self.normalize_test_name(et["test_name"])
                seen_names[base_name] = seen_names.get(base_name, 0) + 1
                test_name = base_name
                if seen_names[base_name] > 1:
                    test_name = self.duplicate_test_name(base_name, seen_names[base_name])
                ct = {
                    "test_name": test_name,
                    "test_description": str(et["test_description"])
                }
                clean_test_list.append(ct)
        if clean_test_list == []:
            log_json_error("No test case with the correct keys found in extracted JSON")
            return []

        test_names = [test['test_name'] for test in clean_test_list]
        print(f"      Got {len(clean_test_list)} potential tests:\n        {'\n        '.join(test_names)}")
        return  clean_test_list

    def normalize_test_name(self, name):
        base_name = str(name).replace("test", "").replace("Test", "").replace("TEST", "").strip()
        if not base_name:
            base_name = "GeneratedCase"
        return f"test{base_name}"

    def duplicate_test_name(self, name, count):
        return f"{name}{count}"

    def source_tree(self, input_path, pattern):
        if shutil.which("tree"):
            try:
                return subprocess.check_output(
                    ["tree", "-P", pattern, "--charset=ascii", input_path],
                ).decode("utf-8")
            except subprocess.SubprocessError:
                pass

        lines = [str(input_path)]
        for root, dirs, files in os.walk(input_path):
            dirs.sort()
            files = sorted(file for file in files if fnmatch.fnmatch(file, pattern))
            if not files:
                continue

            depth = os.path.relpath(root, input_path).count(os.sep)
            indent = "    " * max(depth, 0)
            if root != input_path:
                lines.append(f"{indent}|-- {os.path.basename(root)}/")
            for file in files:
                lines.append(f"{indent}    |-- {file}")

        return "\n".join(lines)


    def build_signature(self, context, doc=True):
        raise NotImplementedError


    def build_context(self, context):
        raise NotImplementedError


    def build_tests(self, context):
        raise NotImplementedError


    def check_syntax(self, code, output_path):
        raise NotImplementedError


    def syntax_check_instruction(self):
        raise NotImplementedError
