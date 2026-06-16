import json
import re

from cascade.generation.code.BaseCodeGenerator import BaseCodeGenerator
from cascade.utils.CSharpUtils import build_context, build_signature, parent_context


class CSharpCodeGenerator(BaseCodeGenerator):
    language = "C#"
    code_block_language = "csharp"
    context_name = "C# class"
    target_name = "method"
    response_kind = "method"
    error_word = "exceptions"
    valid_code_instruction = "The code should compile without errors."
    build_context_function = staticmethod(build_context)

    def prompt_code_prefix(self, context):
        parent = parent_context(context)

        imports = parent.get("imports", [])
        using_lines = ""
        if imports:
            using_lines = "\n".join(import_.rstrip() for import_ in imports) + "\n\n"

        namespace = parent.get("namespace")
        namespace_line = f"namespace {namespace};\n\n" if namespace else ""
        return using_lines + namespace_line

    def build_prompt_finisher(self, context):
        return (
            " {\n"
            "    // write the function body for this method. Take the Documentation as literal as possible.\n"
            "    }\n"
            "}\n"
            "```\n"
            "Now respond with the working implemented method."
        )

    def extract_code(self, new_code, context, response, output_path):
        code_blocks = re.findall(r"```(?:csharp|cs)(.*?)\n```", new_code, flags=re.DOTALL)

        if code_blocks:
            new_code = code_blocks[0]
        else:
            new_code = re.sub(r"^```(?:csharp|cs)?\s*", "", new_code.strip())
            new_code = re.sub(r"\s*```$", "", new_code).strip()

        return self.try_to_fix(new_code, context, response)

    def try_to_fix(self, new_code, context, response):
        new_code = new_code.strip()
        signature = build_signature(context, doc=False)
        signature_pattern = re.escape(re.sub(r"(\W)", r" \1 ", signature + " {")).replace(r"\ ", r"\s*")
        parts = re.split(signature_pattern, new_code)

        if len(parts) > 1:
            new_code = "".join(parts[1:])
            return self.extract_balanced_body(new_code, starts_after_open_brace=True)

        method_name = re.escape(context["signature"]["name"])
        method_match = re.search(rf"\b{method_name}\b[^\{{]*\{{", new_code, flags=re.DOTALL)
        if method_match:
            new_code = new_code[method_match.end():]
            return self.extract_balanced_body(new_code, starts_after_open_brace=True)

        if new_code.startswith("{"):
            return self.extract_balanced_body(new_code[1:], starts_after_open_brace=True)

        return self.extract_balanced_body(new_code, starts_after_open_brace=True)

    def extract_balanced_body(self, code, starts_after_open_brace):
        fixed_code = ""
        braces = 1 if starts_after_open_brace else 0

        for letter in code:
            if letter == "{":
                braces += 1
            elif letter == "}":
                braces -= 1

            if braces == 0:
                break

            fixed_code += letter

        return "{" + fixed_code.rstrip() + "\n}"

    def repair(self, context, input_path, output_path, errors, key):
        system_prompt = (
            "You are an expert C# developer. You will fix provided compilation errors in provided code "
            "without changing its functionality. Follow the documentation as close as possible. "
            "Handle exceptions properly, and ensure all calls are correct. Do not use any new imports. "
            "The code should compile without errors. Respond only with the method."
        )
        prompt = (
            f"The following errors occurred during compilation of the C# class: "
            f"{parent_context(context).get('name', 'unknown class')}.\n"
            f"Errors:\n```\n{errors}\n```\n\n"
            "Fix the errors in the following method while still following the documentation as close as possible:\n"
            f"```csharp\n{build_signature(context, doc=True) + context[key]}\n```"
        )

        promptlist = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        res = self.prompt_executor.execute(promptlist).model_dump()
        promptlist.append(res["choices"][0]["message"])

        repair_response = {"prompt": promptlist, "response": res}
        new_code = res["choices"][0]["message"]["content"]
        new_code = self.extract_code(new_code, context, res, output_path)

        return new_code, repair_response
