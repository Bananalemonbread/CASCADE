import copy
import json
import os
import re
import tiktoken

from cascade.generation.Generator import Generator
from cascade.generation.executor.OpenAIChatCompletionExecutor import OpenAIChatCompletionExecutor
from cascade.utils.RustUtils import build_context, build_tests, check_syntax, build_test_first_method, build_test_suite, \
    build_test_module, build_replacement_test_dict_with_path, INJECTED_SUITE_PATH


def is_public(c) -> bool:
    return False #TODO: later refactor lol...
    #return "pub" in c["signature"]["modifier"]

class GPT4oRustTestGenerator(Generator):
    def __init__(self, max_attempts=1, max_tokens=10000, temperature=0, delay=3, max_prompt_tokens=6000, model="gpt-4o-mini-2024-07-18", freq_penalty=0.0, dummy=False, no_original_tests=False):
        super().__init__()
        self.no_original_tests = no_original_tests
        self.model = model
        self.max_prompt_tokens = max_prompt_tokens
        self.prompt_executor = OpenAIChatCompletionExecutor(max_attempts=max_attempts, model=model, max_tokens=max_tokens, temperature=temperature,
                                                            delay=delay, freq_penalty=freq_penalty, dummy=dummy)




    def build_prompt_with_generic_tests(self, context):
        promptlist = []
        system_prompt = f"Write Rust unit tests for the function {context['signature']['name']}. Respond only with the completion of the tests. Do not use the quicktest crate."
        primer = f"// start writing tests for {context['signature']['name']} here"

        if is_public(context):
            replacement_test_dict = build_replacement_test_dict_with_path(INJECTED_SUITE_PATH)
            context["tests"] = [replacement_test_dict]

            code = "// CODE:\n\n" + build_context(context, doc=True)
            test_header = "\n\n// TESTS:\n\n" + build_test_suite(context, primer=primer)
            prompt = code + test_header
        else:
            replacement_test_dict = build_replacement_test_dict_with_path(context["code_file_path"])
            context["tests"] = [replacement_test_dict]

            code = "// CODE:\n\n" + build_context(context, doc=True)
            test_header = "\n\n// TESTS:\n\n" + build_test_module(context, primer=primer)
            prompt = code + test_header

        prompt = self.shorten_prompt(context, prompt, test_header)
        if prompt is None:
            return []

        promptlist.append({"role": "system", "content": system_prompt})
        promptlist.append({"role": "user", "content": prompt})

        return promptlist

    def build_prompt(self, context):
        system_prompt = f"Write Rust unit tests for the function {context['signature']['name']}. Respond only with the completion of the tests. Do not use the quicktest crate."

        code = "// CODE:\n\n" + build_context(context, doc=True)
        test_header = "\n\n// TESTS:\n\n" + build_tests(context, primer=f"// start writing tests for {context['signature']['name']} here")

        prompt = code + test_header

        prompt = self.shorten_prompt(context, prompt, test_header)
        if prompt is None:
            return []

        promptlist = []
        promptlist.append({"role": "system", "content": system_prompt})
        promptlist.append({"role": "user", "content": prompt})

        return promptlist

    def shorten_prompt(self, context, prompt, test_header):
        enc = tiktoken.encoding_for_model(self.model)
        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            code = "// CODE:\n\n" + build_context(context, doc=True, no_fields=True)
            prompt = code + test_header
        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            code = "// CODE:\n\n" + build_context(context, doc=True, no_fields=True, no_other_method_docs=True)
            prompt = code + test_header
        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            code = "// CODE:\n\n" + build_context(context, doc=True, no_fields=True, no_other_method_docs=True,
                                                  no_other_methods=True)
            prompt = code + test_header

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            return None

        return prompt

    def generate(self, context, output_path, safety_copy_prefix):
        # This is primarily used for our experiment run
        if self.no_original_tests:
            prompt = self.build_prompt_with_generic_tests(context)
        else:
            prompt = self.build_prompt(context)

        test_safety_copy_path = os.path.join(output_path, safety_copy_prefix + "test_generator_current.json")

        response = None
        if os.path.exists(test_safety_copy_path):
            with open(test_safety_copy_path, "r") as file:
                context2 = json.load(file)

            response = context2["response"]
            del context2["response"]

            if context != context2:
                response = None

        if not response:
            response = self.prompt_executor.execute(prompt).model_dump()

            safety_copy = copy.deepcopy(context)

            imports = dict()
            response = {"response" : response, "imports" : imports}

            safety_copy["response"] = response
            with open(test_safety_copy_path , "w") as file:
                json.dump(safety_copy, file)

        new_tests = response["response"]["choices"][0]["message"]["content"]

        new_tests = self.extract_tests(new_tests, context, response, output_path)

        return new_tests, response

    def extract_tests(self, new_tests, context, response, output_path):
        code_blocks = re.findall(r"```rust(.*?)\n```", new_tests, flags=re.DOTALL)

        if not code_blocks == []:
            new_tests = code_blocks[0]

        #for the experiment run
        if self.no_original_tests:
            if is_public(context):
                new_tests = self.try_to_fix_replacement(new_tests, response, context, output_path, build_test_suite)
            else:
                # this only returns the module, which has to be injected in the correct file later on
                new_tests = self.try_to_fix_replacement(new_tests, response, context, output_path, build_test_module)
        else:
            new_tests = self.try_to_fix(new_tests, response, context, output_path, build_context)

        return new_tests

    def try_to_fix_replacement(self, new_tests, response, context, output_path, build_test_function):
        new_tests = self.remove_first_method_signature(context, new_tests)
        chunk = new_tests

        # possible fixes
        to_check = [build_test_function(context) + chunk,
                    build_test_function(context) + chunk + "}",
                    build_test_function(context, no_method=True) + chunk,
                    build_test_function(context, no_method=True) + chunk + "}",
                    chunk,
                    build_test_function(context) + chunk[chunk.find("{") + 1:],
                    chunk[:chunk.rfind("}")]]

        for check in to_check:
            if check_syntax(check, output_path):
                return check

        if response['response']['choices'][0]["finish_reason"] == "length":
            last_test = 0
            lines = new_tests.splitlines()

            for num, line in enumerate(lines):
                if "#[test]" in line:
                    last_test = num

            return "\n".join(lines[:last_test])

        # if nothing helps, stick with the default
        return build_test_function(context) + new_tests

    def try_to_fix(self, new_tests, response, context, output_path, build_test_function):

        new_tests = self.remove_first_method_signature(context, new_tests)

        chunk = new_tests

        # possible fixes
        to_check = [build_test_function(context) + chunk, build_test_function(context, no_method=True) + chunk, chunk,
                    build_test_function(context) + chunk[chunk.find("{") + 1:], chunk[:chunk.rfind("}")]]
        for check in to_check:
            if check_syntax(check, output_path):
                return check

        if response['response']['choices'][0]["finish_reason"] == "length":
            last_test = 0
            lines = new_tests.splitlines()

            for num, line in enumerate(lines):
                if "#[test]" in line:
                    last_test = num

            return "\n".join(lines[:last_test])

        # if nothing helps, stick with the default
        return build_test_function(context) + new_tests

    def remove_first_method_signature(self, context, new_tests):
        # I know this is brutal, but this gives us the first test method signature that we passed
        # to the Chatbot prompting it to complete the test file from there on
        first_test_method_signature = build_test_first_method(context)

        split_result = new_tests.split(first_test_method_signature)

        if len(split_result) == 2:
            new_tests = split_result[1]

        # in case chatbot return the first passed signature again underneath the original signature,
        # we remove it
        if len(split_result) == 3:
            new_tests = split_result[0] + first_test_method_signature + split_result[2]

        return new_tests
