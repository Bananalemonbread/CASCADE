from cascade.analysis.executor.Execution import Execution
from cascade.analysis.visualizer.Visualization import Visualization
from cascade.generation.NoGenerator import NoGenerator
from cascade.Pipeline import Pipeline
from cascade.generation.Generation import Generation
from cascade.filters.Filter import Filter
from cascade.utils import Utils

import sys

import os
import importlib


class PipelineFactory:
    """
    TODO
    """

    def __init__ (self):
        """
        TODO Write Doc
        """

    @staticmethod
    def load_class(class_name, module_path, args, kwargs):
        """
        Dynamically loads a class and instantiates it with given arguments.

        :param
            class_name: The name of the class to be instantiated.
            module_path: The dot-separated path to the module containing the class.
                               For example, 'package.subpackage.module'.
            **kwargs: Arbitrary keyword arguments passed to the class constructor.
        :return
            An instance of the specified class, instantiated with the given arguments.
        """
        try:
            # Dynamically import the module where the class is defined
            module = importlib.import_module(module_path)

            # Get the class by its name
            cls = getattr(module, class_name)

            # Instantiate the class with the provided arguments
            instance = cls(*args, **kwargs)

            return instance
        except ModuleNotFoundError as e:
            print(f"Module '{module_path}' not found: {e}")
            sys.exit(-1)
        except AttributeError as e:
            print(f"Class '{class_name}' not found in '{module_path}': {e}")
            sys.exit(-1)
        except Exception as e:
            print(f"Error instantiating class '{class_name}': {e}")
            sys.exit(-1)

    def build(self, pipeline_path, kwargs=None):
        """
        Builds a pipeline from a setup file and optional keyword arguments.
        The setup file is a JSON file containing the specific modules that should be used for each pipeline component.
        It should include Extraction, any of (CodeGenerator, TestGenerator, DocGenerator), Analysis, Executor and Visualizer

        :param pipeline_path: The path to the setup file.
        """
        if not kwargs:
            kwargs = {"module_path": None, "Extraction": {}, "CodeGenerator": {}, "TestGenerator": {},
                      "DocGenerator": {}, "Analysis": {}, "Executor": {}, "Visualizer": {}, "FilterFunctions": []}

        setup = Utils.load_json_from_path(pipeline_path)
        if not setup:
            raise Exception("No setup file found")

        if kwargs["module_path"]:
            sys.path.append(os.path.abspath(str(kwargs["module_path"])))
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cascade")))

        name = setup["Extraction"]["name"]
        path = "cascade.extraction." + name
        kwargs_ = setup["Extraction"]["kwargs"]
        kwargs_.update(kwargs["Extraction"])
        extraction = self.load_class(name, path, [], kwargs_)

        filter_functions = []
        if "FilterFunctions" in setup:
            for f in setup["FilterFunctions"]:
                name = f["name"]
                path = "cascade.filters." + name
                kwargs_ = f["kwargs"]
                index = setup["FilterFunctions"].index(f)
                if len(kwargs["FilterFunctions"]) > index:
                    kwargs_.update(kwargs["FilterFunctions"][index])
                filter_functions.append(self.load_class(name, path, [], kwargs_))

        filter_ = Filter(filter_functions)

        generator_strings = [("CodeGenerator", "code"),
                             ("TestGenerator", "test"),
                             ("DocGenerator", "doc")]

        generators = {gen[1]: NoGenerator() for gen in generator_strings}
        for gen in generator_strings:
            if gen[0] in setup and "name" in setup[gen[0]]:
                current = setup[gen[0]]
                name = current["name"]
                path = f"cascade.generation.{gen[1]}." + name
                kwargs_ = current["kwargs"]
                kwargs_.update(kwargs[gen[0]])
                generators[gen[1]] = self.load_class(name, path, [], kwargs_)

        generation = Generation(generators["code"], generators["test"], generators["doc"])

        name = setup["Executor"]["name"]
        path = "cascade.analysis.executor." + name
        kwargs_ = setup["Executor"]["kwargs"]
        kwargs_.update(kwargs["Executor"])
        analysis_executor = self.load_class(name, path, [], kwargs_)

        name = setup["Visualizer"]["name"]
        path = "cascade.analysis.visualizer." + name
        kwargs_ = setup["Visualizer"]["kwargs"]
        kwargs_.update(kwargs["Visualizer"])
        analysis_visualizer = self.load_class(name, path, [], kwargs_)

        name = setup["Analysis"]["name"]
        path = "cascade.analysis." + name
        kwargs_ = setup["Analysis"]["kwargs"]
        kwargs_.update(kwargs["Analysis"])
        analysis = self.load_class(name, path, [generation, Execution(analysis_executor),
                                                Visualization(analysis_visualizer)], kwargs_)

        can_work = True
        extraction_prov = extraction.provided
        for ff in filter_functions:
            can_work &= extraction_prov.fulfills(ff.extraction_requirements)
            extraction_prov.merge(ff.provided)
        can_work &= extraction_prov.fulfills(analysis.extraction_requirements)
        for gen in generators.values():
            can_work &= extraction_prov.fulfills(gen.extraction_requirements)
        can_work &= extraction_prov.fulfills(analysis_executor.extraction_requirements)
        can_work &= extraction_prov.fulfills(analysis_visualizer.extraction_requirements)
        analysis_prov = analysis.provided
        for gen in generators.values():
            can_work &= analysis_prov.fulfills(gen.analysis_requirements)
        can_work &= analysis_prov.fulfills(analysis_executor.analysis_requirements)
        can_work &= analysis_prov.fulfills(analysis_visualizer.analysis_requirements)

        pipeline = Pipeline(extraction, filter_, analysis, setup)

        return pipeline


