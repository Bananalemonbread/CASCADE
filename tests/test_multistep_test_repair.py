from types import SimpleNamespace

from cascade.generation.test.MultiStepTestGenerator import MultiStepTestGenerator


class TestGenerator(MultiStepTestGenerator):
    code_block_names = ["python", "py"]
    language_name = "Python"
    signature_block_name = "python"
    test_artifact_name = "test module"

    def check_generated_tests_syntax(self, code, output_path):
        return True

    def unused(self, *args, **kwargs):
        raise NotImplementedError

    build_context = unused
    build_signature = unused
    build_tests = unused
    repair_source_pattern = unused
    repair_system_prompt = unused
    repair_user_prompt = unused
    test_generation_context_prompt = unused
    test_generation_system_prompt = unused
    test_generation_test_header = unused


class FakePromptExecutor:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def execute(self, prompt, **kwargs):
        self.calls.append((prompt.copy(), kwargs))
        return SimpleNamespace(model_dump=lambda: next(self.responses))


def response(content):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": content,
                },
            }
        ]
    }


def generator_with_responses(responses):
    generator = object.__new__(TestGenerator)
    generator.prompt_executor = FakePromptExecutor(responses)
    generator.build_repair_prompt = lambda *args: [
        {"role": "user", "content": "Repair these tests"}
    ]
    return generator


def test_repair_retries_non_code_responses_without_tools(tmp_path):
    generator = generator_with_responses(
        [
            response("<tool_call>list_directory</tool_call>"),
            response("Here is the repaired module."),
            response("```python\nassert True\n```"),
        ]
    )

    repaired, _ = generator.repair(
        {}, str(tmp_path), str(tmp_path), "NameError", "new_tests"
    )

    assert repaired.strip() == "assert True"
    assert len(generator.prompt_executor.calls) == 3
    assert all(kwargs == {} for _, kwargs in generator.prompt_executor.calls)
    assert "Do not call tools" in generator.prompt_executor.calls[0][0][-1]["content"]
    assert "previous answer did not contain" in generator.prompt_executor.calls[1][0][-1]["content"]


def test_repair_stops_after_first_valid_code_block(tmp_path):
    generator = generator_with_responses(
        [
            response("```python\nassert True\n```"),
            response("```python\nassert False\n```"),
        ]
    )

    repaired, _ = generator.repair(
        {}, str(tmp_path), str(tmp_path), "NameError", "new_tests"
    )

    assert repaired.strip() == "assert True"
    assert len(generator.prompt_executor.calls) == 1


def test_repair_stops_after_three_invalid_responses(tmp_path):
    generator = generator_with_responses(
        [
            response("<tool_call>first</tool_call>"),
            response("<tool_call>second</tool_call>"),
            response("<tool_call>third</tool_call>"),
            response("```python\nassert True\n```"),
        ]
    )

    repaired, _ = generator.repair(
        {}, str(tmp_path), str(tmp_path), "NameError", "new_tests"
    )

    assert repaired == ""
    assert len(generator.prompt_executor.calls) == 3
