import re

from cascade.generation.code.BaseCodeGenerator import BaseCodeGenerator
from cascade.utils.JavaUtils import build_context, build_signature, repair_helper_functions, get_repair_helper_functions

import json

class JavaCodeGenerator(BaseCodeGenerator):
    language = "Java"
    code_block_language = "java"
    context_name = "class"
    target_name = "method"
    response_kind = "function"
    error_word = "exceptions"
    valid_code_instruction = "The code should compile without errors."
    build_context_function = staticmethod(build_context)

    def prompt_code_prefix(self, context):
        return f"package {context['package']};\n\n" + "".join(context["parent"]["imports"]) + "\n"

    def build_prompt_finisher(self, context):
        return " {\n    // write the function body for this method. Take the Documentation as literal as possible.\n    }\n}\n```\nNow respond with the working implemented method."


    def extract_code(self, new_code, context, response, output_path):
        code_blocks = re.findall(r"```java(.*?)\n```", new_code, flags=re.DOTALL)

        if code_blocks:
            new_code = code_blocks[0]
        else:
            new_code = new_code.split("```java")[-1].strip()

        return self.try_to_fix(new_code, context, response)


    def try_to_fix(self, new_code, context, response):
        sign = re.escape(re.sub(r"(\W)", r" \1 ", build_signature(context, False) + " {")).replace(r"\ ", r'\s*')
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
        tools = get_repair_helper_functions()

        system_prompt = ("You are an Expert Java developer. You will Fix provided compilation errors in provided code without changing its functionality. "
                         "You can use tools to find out more about classes instead of making your own assumptions. "
                         "You have to assume that all fields are initialized with null"
                         )
        prompt = (f"The following errors occurred during compilation of the class: {context["parent"]["name"]}.\nErrors:\n```\n{errors}\n```\n\n "
                  "Fix the errors in the following function while still following the documentation as close as possible:\n"
                  f"```java\n{build_signature(context, doc=True) + context[key]}\n```"

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
