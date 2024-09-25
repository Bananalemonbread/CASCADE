from cascade.extraction.Extraction import Extraction
from cascade.extraction.JsonExtraction import JsonExtraction
from typing import List, Dict
from cascade.utils.Utils import save_dicts_list_to_json
import subprocess
import os


class CSharpExtraction(Extraction):
    def __init__(self):
        """
        A class which enables extracting CSharp projects.
        """
        super().__init__()

    """
    The Java extraction class, this class supports extracting from source folders.
    """
    def extract(self, input_path, output_path) -> List[Dict[str, any]]:
        """
        Extracts a C# class hierarchy from the source folder that the input path points to.

        For typical C# package structures point it to the directory which contains both the source and the test
        directory.

        If there already is an "extracted.json" in the output folder, loads that instead.

        :param input_path: The path to the jar/source folder
        :param output_path:
        :return:
        """
        json_extractor = JsonExtraction()
        extracted = json_extractor.extract(input_path, output_path)
        if extracted:
            return extracted

        my_path = os.path.dirname(__file__)
        subprocess.run(
            ["dotnet", os.path.join(my_path, "..", "resources", "tools","CSharpExtractor", "CSharpExtractor.dll"),
             input_path,
             output_path,
             "net6.0"] # TODO: make this a parameter
            , text=True
        )
        extracted = json_extractor.extract(input_path, output_path)

        count = 0
        for e in extracted:
            e["id"] = count
            count += 1

            # TODO remove this later when it is fixed in the jar
            del e["root_path"]


        save_dicts_list_to_json(extracted, os.path.join(output_path, "extracted.json"))

        return extracted
