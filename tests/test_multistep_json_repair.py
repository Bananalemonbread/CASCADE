from types import SimpleNamespace

from cascade.generation.test.MultiStepTestGenerator import MultiStepTestGenerator


class TestGenerator(MultiStepTestGenerator):
    def unused(self, *args, **kwargs):
        raise NotImplementedError

    build_context = unused
    build_signature = unused
    build_tests = unused
    check_generated_tests_syntax = unused
    repair_source_pattern = unused
    repair_system_prompt = unused
    repair_user_prompt = unused
    test_generation_context_prompt = unused
    test_generation_system_prompt = unused
    test_generation_test_header = unused


class FakePromptExecutor:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []

    def execute(self, prompt):
        self.prompts.append(prompt.copy())
        return SimpleNamespace(model_dump=lambda: next(self.responses))


def response(content):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                }
            }
        ]
    }


def generator_with_responses(responses):
    generator = object.__new__(TestGenerator)
    generator.prompt_executor = FakePromptExecutor(responses)
    generator.build_behaviour_prompt = lambda context: [
        {"role": "user", "content": "Describe the behavior"}
    ]
    generator.json_test_list_instruction = lambda: {
        "role": "user",
        "content": "Return JSON",
    }
    return generator


def test_invalid_json_is_sent_back_to_llm_for_repair(tmp_path):
    generator = generator_with_responses(
        [
            response("Behavior description"),
            response('[{"test_name": "broken",]'),
            response(
                '[{"test_name": "works", '
                '"test_description": "valid repaired JSON"}]'
            ),
        ]
    )
    context = {"signature": {"name": "example"}}

    test_list = generator.generate_test_plan(context, str(tmp_path), [])

    assert test_list == [
        {
            "test_name": "testworks",
            "test_description": "valid repaired JSON",
        }
    ]
    assert len(generator.prompt_executor.prompts) == 3
    repair_prompt = generator.prompt_executor.prompts[-1]
    assert '[{"test_name": "broken",]' in repair_prompt[-2]["content"]
    assert "Parser/validation error" in repair_prompt[-1]["content"]


def test_json_failure_is_logged_after_three_repair_attempts(tmp_path):
    generator = generator_with_responses(
        [response("Behavior description")] + [response("not json")] * 4
    )
    context = {"signature": {"name": "example"}}

    test_list = generator.generate_test_plan(context, str(tmp_path), [])

    assert test_list == []
    assert len(generator.prompt_executor.prompts) == 5
    assert "Could not parse JSON" in (tmp_path / "errors.txt").read_text()
