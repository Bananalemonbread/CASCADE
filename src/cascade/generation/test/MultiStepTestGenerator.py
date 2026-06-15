import copy
import os
import re

from cascade.generation.Generator import Generator
from cascade.generation.executor.OpenAICaller import OpenAICaller

class MultiStepTestGenerator(Generator):
    def __init__(self,
                 model="gpt-4o-mini-2024-07-18",
                 max_attempts=1, delay=3,
                 max_tokens=16000,
                 temperature=0,
                 max_prompt_tokens=8000,
                 freq_penalty=0.0, dummy=False,
                 base_url=None, api_key=None
                ):
        super().__init__()
        self.prompt_executor = OpenAICaller(
            max_attempts=max_attempts,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            freq_penalty=freq_penalty,
            dummy=dummy,
            base_url=base_url,
            api_key=api_key
        )
        self.model = model
        self.max_prompt_tokens = max_prompt_tokens
    

    def generate(self, context, input_path, output_path,  response_step2=None):
        raise NotImplementedError


    def build_signature(self, context, doc=True):
        raise NotImplementedError


    def build_context(self, context):
        raise NotImplementedError


    def build_tests(self, context):
        raise NotImplementedError


    def check_syntax(self, code, output_path):
        raise NotImplementedError


    def syntax_check_instruction(self):
        raise NotImplementedError