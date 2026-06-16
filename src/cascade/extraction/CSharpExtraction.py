import os
from typing import List, Dict

from cascade.extraction.Extraction import Extraction
from cascade.extraction.JsonExtraction import JsonExtraction
from cascade.utils import CSharpUtils
from cascade.utils.Utils import save_dicts_list_to_json


class CSharpExtraction(Extraction):
    def __init__(self, framework="net9.0", tool_path=None):
        super().__init__()
        self.framework = framework
        self.tool_path = tool_path

    def extract(self, input_path, output_path) -> List[Dict[str, any]]:
        json_extractor = JsonExtraction()
        extracted = json_extractor.extract(input_path, output_path)
        if extracted:
            return extracted

        CSharpUtils.run_extraction(input_path, output_path, self.framework, tool_path=self.tool_path)

        extracted = json_extractor.extract(input_path, output_path)
        if extracted is None:
            raise RuntimeError(
                "CSharpTool finished but no extracted.json could be loaded from "
                f"{output_path}."
            )

        save_dicts_list_to_json(extracted, os.path.join(output_path, "extracted.json"))
        return extracted
