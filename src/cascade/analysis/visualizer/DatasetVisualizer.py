import os

from cascade.analysis.visualizer.AnalysisVisualizer import AnalysisVisualizer
from cascade.utils.Utils import log


class DatasetVisualizer(AnalysisVisualizer):
    def __init__(self, vis_key="name", logger="print"):
        super().__init__()
        self.logger = logger
        self.vis_key = vis_key


    def visualize(self, data, output_path, full=False):
        pass