import re

from cascade.generation.code.BaseCodeGenerator import BaseCodeGenerator
from cascade.utils.RustUtils import build_context, build_signature

class RustCodeGenerator(BaseCodeGenerator):
    language = "Rust"
    code_block_language = "rust"
    context_name = "Rust module"
    target_name = "function"
    response_kind = "function"
    error_word = "errors"
    valid_code_instruction = "The code should compile without errors."

    def build_prompt_context(self, context, **kwargs):
        rust_context = build_context(context, doc=True, **kwargs)
        module_closers = "\n}" * max(len(context["parent"]) - 1, 0)

        if module_closers and rust_context.endswith(module_closers):
            rust_context = rust_context[:-len(module_closers)]

        function_body_prompt = " {\n     // write the function body for this function. Take the Documentation as literal as possible.\n    }"
        return rust_context + function_body_prompt + module_closers

    def build_prompt_finisher(self, context):
        return "\n```\nNow respond with the working implemented function."

    def context_variants(self):
        return [
            {},
            {"no_fields": True},
            {"no_fields": True, "no_other_method_docs": True},
            {"no_fields": True, "no_other_method_docs": True, "no_other_methods": True},
        ]

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
