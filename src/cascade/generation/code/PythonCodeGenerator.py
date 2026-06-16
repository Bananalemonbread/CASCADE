import re

from cascade.generation.code.BaseCodeGenerator import BaseCodeGenerator
from cascade.utils.PythonUtils import repair_helper_functions, get_repair_helper_functions, build_context, build_signature

import tiktoken
import json

class PythonCodeGenerator(BaseCodeGenerator):
    def build_prompt(self, context):
        #enc = tiktoken.encoding_for_model(self.model)
        enc = tiktoken.get_encoding("o200k_base")

        par = context['signature']['params']
        params = ", ".join(par) if len(par) > 1 else (par[0] if par else "")

        system_prompt = ("You are an Expert Python developer. "
                         "You will be given a Python module or class and have to implement one specific function or method, following its documentation as close as possible. "
                         "The documentation is the ground truth and should be seen as correct, even if the function name contradicts it. "
                         "Handle errors properly, and ensure all calls are correct. Do not use any new imports. "
                         "The code should be syntactically valid Python. Respond only with the function body."
                         )

        prompt_start = (
            f"The function you need to implement is `{context['signature']['name']}({params})`.\n"
            "Here is the Python module or class context it is situated in:\n"
            "```python\n"
        )

        prompt_finisher = (
            "\n    # implement only the function body here. "
            "Take the documentation as literal as possible.\n"
            "```\n"
            "Now respond with the working implemented function body."
        )

        prompt = prompt_start +  build_context(context, doc=True, imports=True)  + prompt_finisher

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            prompt = prompt_start + build_context(context, doc=True, imports=True, no_fields=True) + prompt_finisher

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            prompt = prompt_start + build_context(context, doc=True, imports=True, no_fields=True, no_constructors=True) + prompt_finisher

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            prompt = prompt_start + build_context(context, doc=True, imports=True, no_fields=True, no_constructors=True, no_other_method_docs=True) + prompt_finisher

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            prompt = prompt_start + build_context(context, doc=True, imports=True, no_fields=True, no_constructors=True,  no_other_method_docs=True, no_other_methods=True) + prompt_finisher

        if len(enc.encode(prompt)) > self.max_prompt_tokens:
            return []

        promptlist = []
        promptlist.append({"role": "system", "content": system_prompt})
        promptlist.append({"role": "user", "content": prompt})

        return promptlist

    def extract_code(self, new_code, context, response, output_path):
        code_blocks = re.findall(r"```(?:python|py)(.*?)\n```", new_code, flags=re.DOTALL)

        if code_blocks:
            new_code = code_blocks[0]
        else:
            new_code = re.sub(r"^```(?:python|py)?\s*", "", new_code.strip())
            new_code = re.sub(r"\s*```$", "", new_code).strip()

        return self.try_to_fix(new_code, context, response)


    def try_to_fix(self, new_code, context, response):
        new_code = new_code.strip()

        signature_name = context["signature"]["name"]

        if re.search(rf"^\s*(async\s+)?def\s+{re.escape(signature_name)}\s*\(", new_code, flags=re.MULTILINE):
            lines = new_code.splitlines()
            body_lines = []
            in_function = False
            base_indent = None

            for line in lines:
                if re.match(rf"^\s*(async\s+)?def\s+{re.escape(signature_name)}\s*\(", line):
                    in_function = True
                    continue

                if in_function:
                    if line.strip() == "":
                        body_lines.append("")
                        continue

                    indent = len(line) - len(line.lstrip())
                    if base_indent is None:
                        base_indent = indent

                    body_lines.append(line[base_indent:])

            new_code = "\n".join(body_lines).strip()

        return new_code


    def repair(self, context, input_path, output_path, errors, key):
        tools = get_repair_helper_functions()

        system_prompt = ("You are an Expert Python developer. You will fix provided syntax or runtime errors in provided code without changing its functionality. "
                        "Follow the documentation as close as possible. "
                        "Do not use any new imports. Respond only with the function body."
                        )
        prompt = (
            f"The following errors occurred while checking or running the Python function `{context['signature']['name']}`.\n"
            f"Errors:\n```\n{errors}\n```\n\n"
            "Fix the errors in the following function body while still following the documentation as close as possible:\n"
            f"```python\n{build_signature(context, doc=True)}\n{context[key]}\n```"
        )
        promptlist = []
        promptlist.append({"role": "system", "content": system_prompt})
        promptlist.append({"role": "user", "content": prompt})

        res = self.prompt_executor.execute(promptlist, tools=tools).model_dump()

        steps = 3
        for i in range(3):
            if res["choices"][0]["finish_reason"] == "tool_calls":
                promptlist.append(res['choices'][0]['message'])

                tool_calls = res["choices"][0]["message"]["tool_calls"]

                for tool_call in tool_calls:
                    func = tool_call["function"]["name"]
                    arguments = tool_call["function"]["arguments"]

                    results = repair_helper_functions(func, arguments, input_path, output_path, context)

                    promptlist.append({"role": "tool", "content": json.dumps(results), "tool_call_id": tool_call["id"]})

                if i < steps - 1:
                    res = self.prompt_executor.execute(promptlist, tools=tools).model_dump()
                else:
                    res = self.prompt_executor.execute(promptlist).model_dump()



        promptlist.append(res['choices'][0]['message'])

        repair_response = {"prompt": promptlist, "response": res}

        new_code = res["choices"][0]["message"]["content"]

        new_code = self.extract_code(new_code, context, res, output_path)

        return new_code, repair_response
