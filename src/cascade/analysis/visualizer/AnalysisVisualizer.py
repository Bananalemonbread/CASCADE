from abc import ABC, abstractmethod

from cascade.Requirements import Requirements


class AnalysisVisualizer(ABC):
    def __init__(self):
        self.extraction_requirements = Requirements(Requirements.Kind.EXPECTED, name="Visualizer-Extraction-Expected")
        self.analysis_requirements = Requirements(Requirements.Kind.EXPECTED, name="Visualizer-Analysis-Expected")

    @abstractmethod
    def visualize(self, data, output_path, **kwargs):
        """
        This is used to visualize the results of the analysis module
        :param output_path:
        :param data: the data to be visualized
        """
        pass
