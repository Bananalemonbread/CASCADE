from cascade.generation.Generator import Generator
from cascade.generation.executor.OpenAICaller import OpenAICaller

class BaseCodeGenerator(Generator):
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
        raise NotImplementedError

    def extract_code(self, new_code, context, response, output_path):
        raise NotImplementedError
