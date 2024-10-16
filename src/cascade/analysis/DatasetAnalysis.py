import os
import shutil
import tempfile

from cascade.analysis.Analysis import Analysis
from cascade.analysis.executor.Execution import Execution
from cascade.analysis.visualizer.Visualization import Visualization

from cascade.generation.Generation import Generation
from cascade.utils.Utils import load_json_from_path, log, save_dicts_list_to_json

from cascade.utils.DockerizedWrapper import DockerizedWrapper
import xml.etree.ElementTree as ET

class DatasetAnalysis(Analysis):
    """
    TODO
    """
    def __init__(self, generator: Generation, executor: Execution, visualizer: Visualization, regenerate=False, reexecute=False, image="maven" , debug=0, step_size=1):
        super().__init__(generator, executor, visualizer)
        self.reexecute = reexecute or regenerate

        self.step_size = step_size
        self.regenerate = regenerate
        self.debug = debug
        self.visualizer.logger = "tqdm"
        self.image = image

    def extract_junit_version(self, input_path, output_path):
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                shutil.copytree(input_path, temp_dir, dirs_exist_ok=True)

            except Exception as e:
                print("could not copy root path")
                print(e)

            dock_ex = DockerizedWrapper(debug=0)

            dock_context = {
                "image" : self.image,
                "directory" : temp_dir,
                "command" : "mvn help:effective-pom -Doutput=effective-pom.xml",
                "path" : "/root/effective-pom.xml"
            }

            dock_ex.copy_path(dock_context, output_path)

        try:
            tree = ET.parse(os.path.join(output_path, "effective-pom.xml"))
            root = tree.getroot()

            # Define namespaces, if they exist in your pom.xml
            namespaces = {'m': 'http://maven.apache.org/POM/4.0.0'}  # Default Maven namespace

            # Initialize variables for return values
            junit_version = "JUnit dependency not found"
            source_dir = "Source directory not specified"
            test_source_dir = "Test source directory not specified"

            # Search for JUnit dependency
            for dependency in root.findall(".//m:dependency", namespaces):
                group_id = dependency.find("m:groupId", namespaces)
                artifact_id = dependency.find("m:artifactId", namespaces)
                if group_id is not None and artifact_id is not None:
                    if group_id.text == "junit" and artifact_id.text == "junit":
                        version = dependency.find("m:version", namespaces)
                        if version is not None:
                            junit_version = version.text
                        else:
                            junit_version = "Version not specified"

            # Extract source and test source directories
            build = root.find(".//m:build", namespaces)
            if build is not None:
                source_directory = build.find("m:sourceDirectory", namespaces)
                test_source_directory = build.find("m:testSourceDirectory", namespaces)

                if source_directory is not None:
                    source_dir = source_directory.text
                if test_source_directory is not None:
                    test_source_dir = test_source_directory.text

            # Return a 3-tuple with JUnit version, source directory, and test source directory
            return junit_version, source_dir, test_source_dir

        except ET.ParseError as e:
            return f"Error parsing pom.xml: {e}", None, None

    def analyse(self, data: list, input_path, output_path):
        """
        this is the specific analysis for the dataset benchmark. it only executes level 2 and 3 of a normal tree analysis.
        it does not visualize anything. it does however safe the results in a file called result_CASCADE.txt
        :param input_path:
        """
        output = ""

        ana_path = os.path.join(output_path, "analyzed.json")

        # load data for this specific run.
        data = load_json_from_path(ana_path)

        d = data[0]




        if "junit_version" not in d:    #remove this if clause later
            print(output_path)
            print("extracting Junit version")
            junit_version, source_dir, test_source_dir = self.extract_junit_version( input_path, output_path )
            print("Junit version: ", junit_version)

            if not "test_file_path" in d:
                if test_source_dir is not None and source_dir is not None:
                    print(d["code_file_path"])

                    d["test_file_path"] = d["code_file_path"].replace(source_dir.replace("/root/" , ""), test_source_dir.replace("/root/" , ""))
                    d["test_file_path"] = d["test_file_path"].replace(".java", "Test.java")
                    print(d["test_file_path"])
                else:
                    d["test_file_path"] = d["code_file_path"].replace(".java", "Test.java")

            d["junit_version"] = junit_version #remove that later
            save_dicts_list_to_json([d], ana_path)


            return

        else:
            junit_version = d["junit_version"]


        # found in imports ?
        junit_found = False

        if not "test_package" in d:
            print("no tests were extracted for this method")
            d["test_package"] = d["package"]


        else:
            for imp in d["test_imports"]:
                if "junit" in imp:
                    junit_found = True
                    break

        if not junit_found:
            if junit_version.startswith("3.8"):
                d["test_imports"] = ["import junit.framework.*;"]
            elif junit_version.startswith("4."):
                d["test_imports"] = ["import org.junit.*;"]
            else:
                d["test_imports"] = ["import org.junit.jupiter.api.*;"]


        print(f"Starting analysis of function: {d['signature']['name']}")

        if not "new_tests" in d:
            print("generate new tests")
            new_tests, response = self.generator.generate_tests(d, output_path)
            new_tests = new_tests.replace(d["test_file_path"].split("/")[-1].split(".")[0], str("THIS_IS_A_UNIQUE_NAME_Test"))
            d["new_tests"] = new_tests
            d["new_tests_response"] = response
        else:
            print("new tests already generated")

        d["test_file_path"] = d["test_file_path"].replace(d["test_file_path"].split("/")[-1].split(".")[0], str("THIS_IS_A_UNIQUE_NAME_Test"))

        print("execute new tests")

        res2 = list(self.executor.execute("code", "new_tests", d, input_path, output_path))

        d["results"] = {}
        d["results"]["(code, new_tests)"] = res2

        save_dicts_list_to_json([d], ana_path)



        # check if it passed failed or errored
        evaluated = self.evaluate(d["results"]["(code, new_tests)"])
        if evaluated >= 0:
            output += "Negative"
            output += ", error in layer 2: code, new_tests" if evaluated == 0 else ", pass in layer 2: code, new_tests"

        else:
            # generate new code
            new_code, response = self.generator.generate_code(d, output_path)

            d["new_code"] = new_code
            d["new_code_response"] = response

            # execute new code
            res3 = list(self.executor.execute("new_code", "new_tests", d, input_path, output_path))


            d["results"]["(new_code, new_tests)"] = res3
            save_dicts_list_to_json([d], ana_path)

            evaluated = self.evaluate(res3)
            if evaluated <= 0:
                output += "Negative"
                output += ", error in layer 3: new_code, new_tests" if evaluated == 0 else ", fail in layer 3: new_code, new_tests"

            else:
                output += "Positive"


        with open("result.txt", "w") as f:
            f.write(output)
            print("result:" , output)


    def evaluate(self, res):
        if res[0] == [] and res[1] == []:
            if self.debug >= 1:
                log("        Error", logger="tqdm")
            # error
            return 0
        elif res[1] == [] and res[2] == []:
            if self.debug >= 1:
                log("        Passed", logger="tqdm")
            # if no errors or failures  then passed
            return 1
        else:
            if self.debug >= 1:
                log("        Failed", logger="tqdm")
            # failed
            return -1
