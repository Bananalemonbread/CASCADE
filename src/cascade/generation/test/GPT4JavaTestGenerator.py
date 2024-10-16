import copy
import json
import os
import re
import subprocess

import tiktoken

from cascade.generation.Generator import Generator
from cascade.generation.executor.OpenAIChatCompletionExecutor import OpenAIChatCompletionExecutor
from cascade.utils.JavaUtils import build_context, check_syntax


class GPT4JavaTestGenerator(Generator):
    def __init__(self, max_attempts=1, max_tokens=1000, temperature=0, delay=3, max_prompt_tokens=2000, model="gpt-4", freq_penalty=0.0, dummy=False, ask_for_imports=False, import_prompt_finisher="Reply with the missing imports, leave out those you don't know the correct package of."):
        super().__init__()
        self.ask_for_imports = ask_for_imports
        self.model = model
        self.import_prompt_finisher = import_prompt_finisher
        self.max_prompt_tokens = max_prompt_tokens
        self.prompt_executor = OpenAIChatCompletionExecutor(max_attempts=max_attempts, model=model, max_tokens=max_tokens, temperature=temperature,
                                                            delay=delay, freq_penalty=freq_penalty, dummy=dummy)

        self.is_three = False


    def build_prompt(self, context):
        enc = tiktoken.encoding_for_model(self.model)

        system_prompt = f"Write Java tests for the function {context['signature']['name']}."

        code = "// CODE:\n\n" + build_context(context, doc=True)

        test_header = ";\n}\n\n// TESTS:\n\n" + self.build_tests(context, primer=f"\n    // write tests for {context['signature']['name']} here\n")

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



    def build_tests(self, context, primer=""):
        packg_declaration = f"package {context['test_package']};\n\n"
        imports = "".join(context["test_imports"]) + "\n"

        for import_ in context["test_imports"]:
            if import_.startswith("import junit.framework"):
                self.is_three = True
                break

        name = str(context["signature"]["name"])
        class_name = context["test_file_path"].split("/")[-1].split(".")[0]
        if self.is_three:
            classdefinition = "public class " + class_name + " extends TestCase {"
            test_suite_method = "\n    public static Test suite() {\n        return new TestSuite(" + class_name + ".class);\n    }\n"

            classdefinition = classdefinition + test_suite_method
            func_definition = "\n    public void test" + name[0].upper() + name[1:] + "1(){"
        else:
            classdefinition = "public class " + class_name + "{"
            func_definition = "\n    @Test\n    public void test" + name[0].upper() + name[1:] + "1(){"
        return packg_declaration + imports + classdefinition + primer + func_definition




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

            if self.ask_for_imports or (len(context["test_imports"]) == 1 and "*" in context["test_imports"][0]):
                prompt.append({"role" : "assistant", "content" : response["choices"][0]["message"]["content"]})
                prompt.append({"role" : "user", "content" : f"Give me the missing imports for this code to work. I am already importing:\n```java\n{''.join(context['test_imports'])}```\n\n for the Tests.\n The tested class imports:\n```java\n{''.join(context['parent']['imports'])}```\n\n{self.import_prompt_finisher}" })
                imports = self.prompt_executor.execute(prompt).model_dump()
                imports_message = imports["choices"][0]["message"]["content"]
                for line in imports_message.splitlines():
                    if "import" in line and ";" in line:
                        context["test_imports"].append(line + "\n")
                context["test_imports"] = list(set(context["test_imports"]))

            response = {"prompt" : prompt, "response" : response, "imports" : imports}
            safety_copy["response"] = response
            with open(test_safety_copy_path , "w") as file:
                json.dump(safety_copy, file)

        # TODO WRONG RESPONSE
        new_tests = response["response"]["choices"][0]["message"]["content"]

        new_tests = self.extract_tests(new_tests, context, response, output_path)

        return new_tests , response


    def extract_tests(self, new_tests, context, response, output_path):
        code_blocks = re.findall(r"```java(.*?)\n```", new_tests, flags=re.DOTALL)

        if not code_blocks == []:
            new_tests = code_blocks[0]

        new_tests = self.try_to_fix(new_tests, response, context, output_path)

        return new_tests


    def try_to_fix(self, new_tests, response, context, output_path):
        # check if the class is complete
        chunk = ""
        braces = 2
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
            return self.build_tests(context) + chunk

        if braces == 1:
            # to possible cases  full class with a brace too much   or a completion with a brace to few
            #full class
            to_check = [chunk[:chunk.rfind("}")], self.build_tests(context) + chunk + "}", self.build_tests(context) + chunk[chunk.find("{") + 1:]]
            for check in to_check:
                if check_syntax(check, "class", output_path):
                    return check

        # the class is complete
        if braces == 2:
            check = chunk
            if check_syntax(check, "class", output_path):
                return check
            check = self.build_tests(context) + chunk[chunk.find("{") + 1:] + "}"
            if check_syntax(check, "class", output_path):
                return check


        if braces > 2:
            if response['response']['choices'][0]["finish_reason"] == "length":
                last_test = 0
                lines = new_tests.splitlines()

                for num, line in enumerate(lines):
                    if not self.is_three:
                        if "@Test" in line:
                            last_test = num
                    else:
                        if "public void test" in line:
                            last_test = num

                return "\n".join(lines[:last_test]) + "\n}"

        return new_tests + "}"*(braces-2)
