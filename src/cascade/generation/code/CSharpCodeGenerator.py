import re

from cascade.generation.Generator import Generator
from cascade.generation.executor.OpenAICaller import OpenAICaller
from cascade.utils.CSharpUtils import build_context, build_signature

import os
import copy
import tiktoken
import json

class CSharpCodeGenerator(Generator):
    def __init__(self, max_attempts=1, max_tokens=10000, temperature=0, delay=3, max_prompt_tokens=6000, model="gpt-4o-mini-2024-07-18", freq_penalty=0.0, dummy=False):
        super().__init__()
        self.model = model
        self.max_prompt_tokens = max_prompt_tokens
        self.prompt_executor = OpenAICaller(max_attempts=max_attempts, model=model, max_tokens=max_tokens, temperature=temperature,
                                            delay=delay, freq_penalty=freq_penalty, dummy=dummy)

    def build_prompt(self, context):
        enc = tiktoken.encoding_for_model(self.model)

        system_prompt = f"Write the body of one C# method for {context['signature']['name']}. Respond only with the completion of the function body."

        parent = context["parent"]
        usings = '\n'.join(parent["imports"]) + '\n' if parent["imports"] else ""
        namespace = '\n' + "namespace " + parent["namespace"] + ";\n\n"

        code = build_context(context, doc=True)

        primer =  "{\n// write only the function body here\n"

        prompt = usings + namespace + code + primer

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            code = build_context(context, doc=True, no_fields=True)
            prompt = usings + namespace + code + primer

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            code = build_context(context, doc=True, no_fields=True, no_constructors=True)
            prompt = usings + namespace + code + primer

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            code = build_context(context, doc=True, no_fields=True, no_constructors=True, no_other_method_docs=True)
            prompt = usings + namespace + code + primer

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            code = build_context(context, doc=True, no_fields=True, no_constructors=True,  no_other_method_docs=True, no_other_methods=True)
            prompt = usings + namespace + code + primer

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            return []


        promptlist = []
        promptlist.append({"role": "system", "content": system_prompt})
        promptlist.append({"role": "user", "content": prompt})

        return promptlist


    def generate(self, context, output_path, safety_copy_prefix):
        prompt = self.build_prompt(context)
        code_safety_copy_path = os.path.join(output_path, safety_copy_prefix + "code_generator_current.json")

        if prompt == "":
            return "", None

        response = None
        if os.path.exists(code_safety_copy_path):
            with open(code_safety_copy_path, "r") as file:
                context2 = json.load(file)

            response = context2["response"]
            del context2["response"]

            if context != context2:
                response = None

        if not response:
            response = self.prompt_executor.execute(prompt).model_dump()

            safety_copy = copy.deepcopy(context)
            safety_copy["response"] = response

            with open(code_safety_copy_path, "w") as file:
                json.dump(safety_copy, file)

        new_code = response["choices"][0]["message"]["content"]

        new_code = self.extract_code(new_code, context, response)

        return new_code , response

    def extract_code(self, new_code, context, response):
        code_blocks = re.findall(r"```csharp(.*?)\n```", new_code, flags=re.DOTALL)

        if code_blocks:
            new_code = code_blocks[0]

        return self.try_to_fix(new_code, context, response)

    def try_to_fix(self, new_code, context, response):
        temp = new_code.split(build_signature(context , False) + "{")
        if len(temp) > 1:
            new_code = "".join(temp[1:])

        fixed_code = ""
        # First brace is already there
        braces = 1
        for letter in new_code:
            if letter == "{":
                braces += 1
            elif letter == "}":
                braces -= 1
            if braces == 0:
                break
            fixed_code += letter

        return "{" + fixed_code + "}"