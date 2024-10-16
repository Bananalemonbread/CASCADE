from abc import ABC, abstractmethod
from typing import List

from cascade.Requirements import Requirements


class Extraction(ABC):
    def __init__(self):
        self.provided: Requirements = Requirements(Requirements.Kind.PROVIDED, name="Extraction-Provided")
        self.provided.add_requirement("all", Requirements.Level.MANDATORY)
    @abstractmethod
    def extract(self, input_path, output_path) -> List[dict]:
        """
        This is the main method of the Extraction module.
        It gets an input path which could be for a root directory of an entire project or a dataset file or a jar.
        It then should extract functions and other required data from there.

        These should then be returned as a list of dictionaries but also saved as a json file to the output path.
        Either with the generic name such as "extracted.json" or with the name provided in the path if it ends with ".json".
        This could also be used to append to an existing file.

        The expected output format for one function is
        {
            "doc" : str  #
            "id" : str or int - # depending on the usecase
            "signature" : {
                "name" : str - the simple name of the function
                "returns" : str - return type of the function,
                "params" : list of str    -  parameters, including types -- if existent -- each as a string ,
                "modifier" : list of str  - ,
                "annotations": list of str ,
                "generics" list of str :
                }
            "language" : str   - #e.g. python or java
            "parent" : {
                "name" : str,
                "doc" : str,
                "imports" : list of str,
                "other_methods" : list of dict    these dicts should contain {doc:str, signature:dict, code:str},
                "variables" : list of str   - global variables of the class that could be used by the function under test,
                "generics" : list of str
                }
            "code" : str    -the body of the function
            "code_file_path" : str   -  relative to root
            "called_functions" : list of str   full function call of the functions that are called insdie of origianl 'code'
            "tests" :  str    complete content of a test_ file
            "test_imports" : list of str
            "test_file_path" : str   -  relative to root
            "testrunner": str  e.g. unnittest, junit,
        }
        TODO add other missing ones.  for java we have extends


        Note that depending on the Analysis and generate implementations not all of these fields need to be filled.

        You can use the implementation 'json_Extraction' and its extract() method to check whether
        the file already exists in the output path and just load this one instead.

        The output

        """
        pass
