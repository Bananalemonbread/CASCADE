from cascade.generation.Generator import Generator
from cascade.generation.executor.OpenAICaller import OpenAICaller
from abc import abstractmethod

import tiktoken

class BaseCodeGenerator(Generator):
    language = None
    code_block_language = None
    context_name = None
    target_name = "function"
    response_kind = "function"
    valid_code_instruction = "The code should compile without errors."
    error_word = "errors"
    build_context_function = None
    build_context_kwargs = {}

    def __init__(self,
                 max_attempts=1,
                 max_tokens=16000,
                 temperature=0,
                 delay=3,
                 max_prompt_tokens=8000,
                 model="gpt-4o-mini-2024-07-18",
                 freq_penalty=0.0,
                 dummy=False,
                 base_url=None,
                 api_key=None):
        super().__init__()
        self.model = model
        self.max_prompt_tokens = max_prompt_tokens
        self.prompt_executor = OpenAICaller(max_attempts=max_attempts, model=model,
                                            max_tokens=max_tokens, temperature=temperature,
                                            delay=delay, freq_penalty=freq_penalty, dummy=dummy,
                                            api_key=api_key, base_url=base_url)

    def generate(self, context, input_path, output_path):
        prompt = self.build_prompt(context)

        if not prompt:
            return "", None

        response = self.prompt_executor.execute(prompt).model_dump()

        response = {"prompt": prompt, "response": response}

        new_code = response["response"]["choices"][0]["message"]["content"]

        new_code = self.extract_code(new_code, context, response["response"], output_path)

        return new_code, response
    
    def build_prompt(self, context):
        enc = tiktoken.get_encoding("o200k_base")

        prompt_start = self.build_prompt_start(context)
        prompt_finisher = self.build_prompt_finisher(context)
        system_prompt = self.system_prompt()

        for kwargs in self.context_variants():
            prompt = prompt_start + self.build_prompt_context(context, **kwargs) + prompt_finisher

            if len(enc.encode(prompt)) <= self.max_prompt_tokens:
                return [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ]

        return []

    def get_params(self, context):
        params = context["signature"]["params"]
        return ", ".join(params) if len(params) > 1 else (params[0] if params else "")

    def system_prompt(self):
        return (
            f"You are an Expert {self.language} developer. "
            f"You will be given a {self.context_name} and have to implement one specific {self.target_name}, "
            "following its documentation as close as possible. "
            "The documentation is the ground truth and should be seen as correct, even if the function name contradicts it. "
            f"Handle {self.error_word} properly, and ensure all calls are correct. "
            "Do not use any new imports. "
            f"{self.valid_code_instruction} "
            f"Respond only with the {self.response_kind}."
        )


    def build_prompt_start(self, context):
        params = self.get_params(context)
        return (
            f"The {self.target_name} you need to implement is "
            f"`{context['signature']['name']}({params})`.\n"
            f"Here is the {self.context_name} it is situated in:\n"
            f"```{self.code_block_language}\n"
            f"{self.prompt_code_prefix(context)}"
        )

    def prompt_code_prefix(self, context):
        return ""

    def build_prompt_context(self, context, **kwargs):
        return self.build_context_function(
            context,
            doc=True,
            **self.build_context_kwargs,
            **kwargs
        )

    @abstractmethod
    def build_prompt_finisher(self, context, **kwargs):
        pass

    def context_variants(self):
        return [
            {},
            {"no_fields": True},
            {"no_fields": True, "no_constructors": True},
            {"no_fields": True, "no_constructors": True, "no_other_method_docs": True},
            {"no_fields": True, "no_constructors": True, "no_other_method_docs": True, "no_other_methods": True},
        ]

    @abstractmethod
    def extract_code(self, new_code, context, response, output_path):
        pass
