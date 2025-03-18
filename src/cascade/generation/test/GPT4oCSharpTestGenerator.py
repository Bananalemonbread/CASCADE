import copy
import json
import os
import re
import tiktoken

from cascade.generation.Generator import Generator
from cascade.generation.executor.OpenAIChatCompletionExecutor import OpenAIChatCompletionExecutor
from cascade.utils.CSharpUtils import build_context, build_tests, check_syntax, build_test_first_method


class GPT4oCSharpTestGenerator(Generator):
    def __init__(self, max_attempts=1, max_tokens=10000, temperature=0, delay=3, max_prompt_tokens=6000, model="gpt-4o-mini-2024-07-18", freq_penalty=0.0, dummy=False):
        super().__init__()
        self.model = model
        self.max_prompt_tokens = max_prompt_tokens
        self.prompt_executor = OpenAIChatCompletionExecutor(max_attempts=max_attempts, model=model, max_tokens=max_tokens, temperature=temperature,
                                                            delay=delay, freq_penalty=freq_penalty, dummy=dummy)

    def build_prompt(self, context):
        enc = tiktoken.encoding_for_model(self.model)

        system_prompt = f"Write C# unit tests for the method {context['signature']['name']}. Respond only with the completion of the tests."

        code = "// CODE:\n\n" + build_context(context, doc=True)

        test_header = ";\n}\n\n// TESTS:\n\n" + build_tests(context, primer=f"\n    // start writing tests for {context['signature']['name']} here")

        prompt = code + test_header

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            code = "// CODE:\n\n" + build_context(context, doc=True, no_fields=True)
            prompt = code + test_header

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            code = "// CODE:\n\n" + build_context(context, doc=True, no_fields=True, no_constructors=True)
            prompt = code + test_header

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            code = "// CODE:\n\n" + build_context(context, doc=True, no_fields=True, no_constructors=True, no_other_method_docs=True)
            prompt = code + test_header

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            code = "// CODE:\n\n" + build_context(context, doc=True, no_fields=True, no_constructors=True, no_other_method_docs=True,
                                 no_other_methods=True)
            prompt = code + test_header

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            return []

        promptlist = []
        promptlist.append({"role": "system", "content": system_prompt})
        promptlist.append({"role": "user", "content": prompt})

        return promptlist


    def generate(self, context, output_path, safety_copy_prefix):
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
            if True: #TODO: use param from master
                prompt.append({"role" : "assistant", "content" : response["choices"][0]["message"]["content"]})
                prompt.append({"role" : "user", "content" : "What imports are necessary for this code?"})
                imports = self.prompt_executor.execute(prompt).model_dump()
                imports_message = imports["choices"][0]["message"]["content"]
                for line in imports_message.splitlines():
                    if "using" in line and ";" in line:
                        context["tests"][0]["test_imports"].append(line) #TODO: handle multiple tests

            context["tests"][0]["test_imports"] = list(set(context["tests"][0]["test_imports"])) #TODO: use it somewhere..

            response = {"response" : response, "imports" : imports}

            safety_copy["response"] = response
            with open(test_safety_copy_path , "w") as file:
                json.dump(safety_copy, file)

        new_tests = response["response"]["choices"][0]["message"]["content"]

        new_tests = self.extract_tests(new_tests, context, response, output_path)

        return new_tests, response

    def extract_tests(self, new_tests, context, response, output_path):
        code_blocks = re.findall(r"```csharp(.*?)\n```", new_tests, flags=re.DOTALL)

        if not code_blocks == []:
            new_tests = code_blocks[0]

        new_tests = self.try_to_fix(new_tests, response, context, output_path)

        return new_tests

    def try_to_fix(self, new_tests, response, context, output_path):

        new_tests = self.remove_first_method_signature(context, new_tests)

        # check if the class is complete
        chunk = ""
        braces = 3 # one opening brace for namespace, class and method
        for letter in new_tests:
            chunk += letter
            if letter == "{":
                braces += 1
            elif letter == "}":
                braces -= 1
            if braces == 0:
                break

        # we have to complete the class
        if braces == 0:
            return build_tests(context) + chunk

        if braces == 1:
            # two possible cases: 1. full class with a brace too much, 2. or a completion with a brace to few
            # full class
            to_check = [chunk[:chunk.rfind("}")], build_tests(context) + chunk + "}",
                        build_tests(context) + chunk[chunk.find("{") + 1:]]
            for check in to_check:
                if check_syntax(check, output_path):
                    return check

        # the class is complete
        if braces == 2:
            check = chunk
            if check_syntax(check, output_path):
                return check

            check = build_tests(context) + chunk + "}}"
            if check_syntax(check, output_path):
                return check

            check = build_tests(context, no_method=True) + chunk + "}"
            if check_syntax(check, output_path):
                return check

        if braces == 3: # Response could be a full class
            check = chunk
            if check_syntax(check, output_path):
                return check

        if braces >= 3:
            if response['response']['choices'][0]["finish_reason"] == "length":
                last_test = 0
                lines = new_tests.splitlines()

                for num, line in enumerate(lines):
                    if "[Test]" in line or "[Fact]" in line or "[TestMethod]" in line:
                        last_test = num

                return "\n".join(lines[:last_test]) + "\n}"

        return new_tests + "}" * (braces - 2)

    def remove_first_method_signature(self, context, new_tests):
        # I know this is brutal, but this gives us the first test method signature that we passed
        # to the Chatbot prompting it to complete the test file from there on
        first_test_method_signature = build_test_first_method(context["signature"]["name"])

        split_result = new_tests.split(first_test_method_signature)

        # in case chatbot return the first passed signature again underneath the original signature,
        # we remove it
        if len(split_result) == 3:
            new_tests = split_result[0] + first_test_method_signature + split_result[2]

        return new_tests