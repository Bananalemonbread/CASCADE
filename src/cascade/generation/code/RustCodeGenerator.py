import re

from cascade.generation.code.BaseCodeGenerator import BaseCodeGenerator
from cascade.utils.RustUtils import build_context, build_signature

import tiktoken

class RustCodeGenerator(BaseCodeGenerator):
    def build_prompt(self, context):
        #enc = tiktoken.encoding_for_model(self.model)
        enc = tiktoken.get_encoding("o200k_base")

        par = context['signature']['params']
        params = ", ".join(par) if len(par) > 1 else (par[0] if par else "")

        system_prompt = ("You are an Expert Rust developer. "
                         "You will be given a Rust module and have to implement one specific function, following its documentation as close as possible. "
                         "The documentation is the ground truth and should be seen as correct, even if the function name contradicts it. "
                         "Handle errors properly, and ensure all calls are correct. Do not use any new imports. "
                         "The code should compile without errors. Respond only with the function."
                         )

        prompt_start = f"The function you need to implement is `{context['signature']['name']}({params})`\nHere is the module it is situated in\n```rust\n"
        function_body_prompt = " {\n     // write the function body for this function. Take the Documentation as literal as possible.\n    }"
        prompt_finisher = "\n```\nNow respond with the working implemented function."

        def build_prompt_body(**kwargs):
            rust_context = build_context(context, doc=True, **kwargs)
            module_closers = "\n}" * max(len(context["parent"]) - 1, 0)

            if module_closers and rust_context.endswith(module_closers):
                rust_context = rust_context[:-len(module_closers)]

            return rust_context + function_body_prompt + module_closers + prompt_finisher

        prompt = prompt_start + build_prompt_body()

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            prompt = prompt_start + build_prompt_body(no_fields=True)

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            prompt = prompt_start + build_prompt_body(no_fields=True, no_other_method_docs=True)

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            prompt = prompt_start + build_prompt_body(no_fields=True, no_other_method_docs=True, no_other_methods=True)

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            return []

        promptlist = []
        promptlist.append({"role": "system", "content": system_prompt})
        promptlist.append({"role": "user", "content": prompt})

        return promptlist

    def extract_code(self, new_code, context, response, output_path):
        code_blocks = re.findall(r"```rust(.*?)\n```", new_code, flags=re.DOTALL)

        if code_blocks:
            new_code = code_blocks[0]
        else:
            new_code = new_code.split("```rust")[-1].strip()

        return self.try_to_fix(new_code, context, response)


    def try_to_fix(self, new_code, context, response):
        sign = re.escape(re.sub(r"(\W)", r" \1", build_signature(context, False) + " {")).replace(r"\ ", r'\s*')
        temp = re.split(sign, new_code)

        if len(temp) > 1:
            new_code = "".join(temp[1:])
            #new_code = new_code[new_code.find("{") + 1:]

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


    def repair(self, context, input_path, output_path, errors, key):
        system_prompt = ("You are an Expert Rust developer. You will fix provided compilation errors in provided code without changing its functionality. "
                         "Follow the documentation as close as possible. "
                         "Handle errors properly, and ensure all calls are correct. Do not use any new imports. "
                         "The code should compile without errors. Respond only with the function."
                         )

        module_name = context["parent"][-1]["name"] if context.get("parent") else "unknown module"
        prompt = (f"The following errors occurred during compilation of the Rust module: {module_name}.\nErrors:\n```\n{errors}\n```\n\n"
                  "Fix the errors in the following function while still following the documentation as close as possible:\n"
                  f"```rust\n{build_signature(context, doc=True) + context[key]}\n```"
                  )

        promptlist = []
        promptlist.append({"role": "system", "content": system_prompt})
        promptlist.append({"role": "user", "content": prompt})

        res = self.prompt_executor.execute(promptlist).model_dump()
        promptlist.append(res['choices'][0]['message'])

        repair_response = {"prompt": promptlist, "response": res}

        new_code = res["choices"][0]["message"]["content"]
        new_code = self.extract_code(new_code, context, res, output_path)

        return new_code, repair_response
