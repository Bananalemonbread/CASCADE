import copy
import json
import os

import tiktoken

from cascade.generation.Generator import Generator
from cascade.generation.executor.OpenAIChatCompletionExecutor import OpenAIChatCompletionExecutor
from cascade.utils.CSharpUtils import build_context, build_tests


# TODO: max_tokens can be changed if I remember correctly??
class GPT4oCSharpTestGenerator(Generator):
    def __init__(self, max_attempts=1, max_tokens=1000, temperature=0, delay=3, max_prompt_tokens=2000, model="gpt-4o", freq_penalty=0.0, dummy=False):
        super().__init__()
        self.model = model
        self.max_prompt_tokens = max_prompt_tokens
        self.prompt_executor = OpenAIChatCompletionExecutor(max_attempts=max_attempts, model=model, max_tokens=max_tokens, temperature=temperature,
                                            delay=delay, freq_penalty=freq_penalty, dummy=dummy)
        # TODO: add api key to env

        self.is_three = False # TODO: I don't need this, right?

    def build_prompt(self, context):
        enc = tiktoken.encoding_for_model(self.model)

        system_prompt = f"Write C# unit tests for the function {context['signature']['name']}. Respond only with the completion of the tests."

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

            '''
            imports = dict()
            if len(context["tests"]["test_imports"]) == 1 and "*" in context["test_imports"][0]:
                prompt.append({"role" : "assistant", "content" : response["choices"][0]["message"]["content"]})
                prompt.append({"role" : "user", "content" : "What imports are necessary for this code?"})
                imports = self.prompt_executor.execute(prompt).model_dump()
                imports_message = imports["choices"][0]["message"]["content"]
                for line in imports_message.splitlines():
                    if "import" in line and ";" in line:
                        context["test_imports"].append(line)
                context["test_imports"] = list(set(context["test_imports"]))
            
            response = {"response" : response, "imports" : imports}
            '''
            
            safety_copy["response"] = response
            with open(test_safety_copy_path , "w") as file:
                json.dump(safety_copy, file)

        new_tests = response["response"]["choices"][0]["message"]["content"]

        new_tests = self.extract_tests(new_tests, context, response, output_path)

        return new_tests , response

    def extract_tests(self, new_tests, context, response, output_path):
        pass