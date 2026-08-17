import copy
import os
import re
import json
import fnmatch
import shutil
import subprocess

from cascade.generation.Generator import Generator
from cascade.generation.executor.OpenAICaller import OpenAICaller
from abc import abstractmethod

class MultiStepTestGenerator(Generator):
    json_repair_attempts = 3
    test_repair_attempts = 3
    code_block_names = []
    language_name = None
    signature_block_name = None
    test_artifact_name = "test module"
    test_kind_name = "unit tests"
    test_name_rule = "a descriptive test name starting with 'test'"

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
    
    def generate(self, context, input_path, output_path, response_step2=None):
        chat_history = []

        print("     Test generation Phase 1")
        test_list = self.generate_test_plan(context, output_path, chat_history)

        if not test_list:
            return "", chat_history
        
        print("     Test generation Phase 2")
        new_tests = self.generate_test_code(context, output_path, chat_history)

        return new_tests, chat_history

    def build_behaviour_prompt(self, context):
        return [
            {
                "role": "system",
                "content": f"You are an expert {self.language_name} developer and requirements engineer. You will be given a method signature and its documentation. Your task is to extract behaviour specifications from the documentation that can be turned into unit tests to ensure the code is bug free and faithful to its documentation."
            },
            {
                "role": "user",
                "content": (
                    f"Give a complete description of the behavior that we should test when we want to assure that the code matches its documentation from the following method\n```{self.signature_block_name}\n"
                    f"{self.build_signature(context, doc=True)}\n"
                    "```\n\nMake sure you consider the entire functionality exactly as described in the documentation, and cover all edge cases but make no assumptions that are not stated in the documentation."
                )
            }
        ]

    def generate_test_plan(self, context, output_path, chat_history):
        errors_path = os.path.join(output_path, "errors.txt")

        prompt_step1 = self.build_behaviour_prompt(context)

        chat_history.append(copy.deepcopy(prompt_step1))
        response_step1a = self.prompt_executor.execute(prompt_step1).model_dump()
        chat_history.append(response_step1a)

        if not response_step1a["choices"]:
            print("     error during generation")
            with open(errors_path, "a") as f:
                f.write(f"error during test generation of {context["signature"]["name"]}")

            return []
        
        prompt_step1.append(response_step1a["choices"][0]["message"])
        prompt_step1.append(self.json_test_list_instruction())

        response_step1b = self.prompt_executor.execute(prompt_step1).model_dump()
        test_list = []
        json_error = "The model returned no response choice"
        response_text = ""

        for repair_attempt in range(self.json_repair_attempts + 1):
            chat_history.append(copy.deepcopy(prompt_step1))
            chat_history.append(response_step1b)

            if response_step1b.get("choices"):
                response_message = response_step1b["choices"][0]["message"]
                response_text = response_message.get("content") or ""
                test_list, json_error = self.parse_json_list(response_text)
                if test_list:
                    break
            else:
                response_message = {
                    "role": "assistant",
                    "content": response_text,
                }

            if repair_attempt == self.json_repair_attempts:
                break

            print(
                "      Invalid JSON test plan; requesting repair "
                f"{repair_attempt + 1}/{self.json_repair_attempts}"
            )
            prompt_step1.append(response_message)
            prompt_step1.append(self.json_repair_instruction(json_error))
            response_step1b = self.prompt_executor.execute(prompt_step1).model_dump()

        if not test_list:
            self.log_json_error(output_path, response_text, json_error)
            with open(errors_path, "a") as f:
                f.write("error during test extraction from json")
                return []
            
        context["test_list"] = test_list
        return test_list

        

    def generate_test_code(self, context, output_path, chat_history):
        errors_path = os.path.join(output_path, "errors.txt")
        results_path = os.path.join(output_path, "results.txt")

        prompt_step2 = self.build_prompt(context)

        response_step2a = self.prompt_executor.execute(prompt_step2).model_dump()

        prompt_step2.append(response_step2a["choices"][0]["message"])

        prompt_step2.append(self.syntax_check_instruction())

        response_step2b = self.prompt_executor.execute(prompt_step2).model_dump()
        chat_history.append(copy.deepcopy(prompt_step2))
        chat_history.append(response_step2b)

        new_tests = self.extract_tests(response_step2b["choices"][0]["message"]["content"], context, response_step2b, output_path)

        # Fallback if the second reply did not include a code block
        if new_tests == "":
            new_tests = self.extract_tests(response_step2a["choices"][0]["message"]["content"], context, response_step2b, output_path)

        if new_tests == "":
            with open(results_path, "w") as f:
                f.write(f"Negative, No syntactically correct {self.test_artifact_name} generated")
            with open(errors_path, "w") as f:
                f.write(f"No syntactically correct {self.test_artifact_name} generated \nResponse text:\n{response_step2b}")

        print("     Test generation finished")
        return new_tests


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

    def parse_json_list(self, response_text):
        json_blocks = re.findall(r"```json\s*(.*?)\s*```", response_text, flags=re.DOTALL)
        json_text = json_blocks[0].strip() if json_blocks else response_text.strip()

        try:
            extracted_test_list = json.loads(json_text)
        except json.JSONDecodeError as e:
            return [], str(e)

        if not isinstance(extracted_test_list, list):
            return [], "Extracted JSON is not a list"

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
            return [], "No test case with the correct keys found in extracted JSON"

        test_names = [test['test_name'] for test in clean_test_list]
        print(f"      Got {len(clean_test_list)} potential tests:\n        {'\n        '.join(test_names)}")
        return clean_test_list, None

    def extract_json_list(self, output_path, response_text):
        test_list, error_message = self.parse_json_list(response_text)
        if not test_list:
            self.log_json_error(output_path, response_text, error_message)
        return test_list

    def log_json_error(self, output_path, response_text, error_message):
        """Log a JSON error after all repair attempts have failed."""
        print(error_message)
        results_path = os.path.join(output_path, "results.txt")
        errors_path = os.path.join(output_path, "errors.txt")

        with open(results_path, "w") as f:
            f.write("Negative, JSON test extraction error")
        with open(errors_path, "w") as f:
            f.write(
                f"Could not parse JSON: {error_message}\n"
                f"Response text:\n{response_text}"
            )

    def json_repair_instruction(self, error_message):
        return {
            "role": "user",
            "content": (
                "Your previous response could not be parsed as the required "
                f"JSON test-plan list. Parser/validation error: {error_message}\n"
                "Repair the previous response without changing the intended "
                "test cases. Return only one valid JSON array using the exact "
                "keys `test_name` and `test_description` for every item. Do "
                "not include explanations or any text outside the JSON array."
            ),
        }

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


    def build_prompt(self, context):
        system_prompt = self.test_generation_system_prompt(context)
        context_prompt = self.test_generation_context_prompt(context)
        test_header = self.test_generation_test_header(context)

        test_level_prompt = (
            test_header
            + f"\n```{self.signature_block_name}\n"
            + self.build_tests(context)
            + "\n```"
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context_prompt + test_level_prompt}
        ]

    def syntax_check_instruction(self):
        return {
        "role": "user",
        "content": (
            f"Make sure that this {self.test_artifact_name} compiles or runs without errors. "
            "Check that all imports are correct, all referenced symbols exist, and errors or exceptions are handled appropriately. "
            f"Reply with the corrected {self.test_artifact_name} only, inside one "
            f"```{self.signature_block_name} code block. Do not call tools, emit tool calls, or include explanations."
        )
    }

    def json_test_list_instruction(self):
        return {
            "role": "user",
            "content": (
                f"Now turn this into a JSON array of {self.test_kind_name} we should write for test driven development. "
                "Each entry in the array should have: "
                f"\"test_name\": {self.test_name_rule}, "
                "\"test_description\": a detailed description for the developer of what this test should do and "
                "which specific behavior from the documentation it tests. "
                "In particular, I want testable statements of the 'if this then that' type.\n"
                "Return strictly valid JSON only. Escape every double quote inside string values. "
                "Prefer single quotes for Python literals mentioned inside test descriptions. "
                "Focus on those tests that follow directly from the documentation, e.g. no performance based ones."
            )
        }

    def repair(self, context, input_path, output_path, errors, key):
        response_history = []
        prompt_list = self.build_repair_prompt(context, input_path, output_path, errors, key)
        prompt_list.append(self.repair_output_instruction())

        for i in range(self.test_repair_attempts):
            print(f"      Test repair attempt {i + 1}/{self.test_repair_attempts}")
            # Test repair must always produce a directly consumable code block.
            # Do not expose tools: some OpenAI-compatible endpoints serialize a
            # tool request as ordinary response text, which cannot be executed
            # or parsed by CASCADE.
            res = self.execute_repair_prompt(prompt_list, tools=None, allow_tools=False)
            response_history.append(copy.deepcopy(prompt_list))
            response_history.append(res)

            if not res.get("choices"):
                if i + 1 < self.test_repair_attempts:
                    prompt_list.append(self.repair_retry_instruction())
                continue

            message = res["choices"][0]["message"]
            prompt_list.append(message)

            new_tests = self.extract_tests(message.get("content") or "", context, res, output_path)
            if new_tests:
                return new_tests, response_history

            if i + 1 < self.test_repair_attempts:
                prompt_list.append(self.repair_retry_instruction())

        return "", response_history

    def build_repair_prompt(self, context, input_path, output_path, errors, key):
        tree = self.source_tree(input_path, self.repair_source_pattern())
        return [
            {"role": "system", "content": self.repair_system_prompt()},
            {"role": "user", "content": self.repair_user_prompt(context, errors, key, tree)}
        ]

    def execute_repair_prompt(self, prompt_list, tools=None, allow_tools=True):
        if tools and allow_tools:
            return self.prompt_executor.execute(prompt_list, tools=tools).model_dump()
        return self.prompt_executor.execute(prompt_list).model_dump()

    def append_tool_results(self, message, prompt_list, input_path, output_path, context):
        for tool_call in message.get("tool_calls", []):
            function_call = tool_call["function"]
            results = self.run_repair_helper(
                function_call["name"],
                function_call["arguments"],
                input_path,
                output_path,
                context
            )

            prompt_list.append({
                "role": "tool",
                "content": json.dumps(results),
                "tool_call_id": tool_call["id"]
            })

    def repair_retry_instruction(self):
        return {
            "role": "user",
            "content": (
                f"The previous answer did not contain syntactically valid {self.test_artifact_name}. "
                f"Please return one complete {self.test_artifact_name} only, inside a "
                f"```{self.signature_block_name} code block. Do not call tools, emit tool calls, "
                "or include explanations or text outside the code block."
            )
        }

    def repair_output_instruction(self):
        return {
            "role": "user",
            "content": (
                f"Your response must contain exactly one complete {self.test_artifact_name} inside one "
                f"fenced ```{self.signature_block_name} code block. Do not call tools or emit tool calls. "
                "Do not include explanations or any text outside the code block."
            )
        }


    # Hooks for subclasses

    @abstractmethod
    def test_generation_system_prompt(self, context):
        pass

    @abstractmethod
    def test_generation_context_prompt(self, context):
        pass

    @abstractmethod
    def test_generation_test_header(self, context):
        pass

    @abstractmethod
    def check_generated_tests_syntax(self, code, output_path):
        pass

    @abstractmethod
    def build_signature(self, context, doc=True):
        pass

    @abstractmethod
    def build_context(self, context):
        pass

    @abstractmethod
    def build_tests(self, context):
        pass

    @abstractmethod
    def repair_source_pattern(self):
        pass

    @abstractmethod
    def repair_system_prompt(self):
        pass

    @abstractmethod
    def repair_user_prompt(self, context, errors, key, tree):
        pass

    def get_repair_tools(self):
        return None

    def run_repair_helper(
        self,
        func,
        arguments,
        input_path,
        output_path,
        context,
    ):
        raise NotImplementedError
