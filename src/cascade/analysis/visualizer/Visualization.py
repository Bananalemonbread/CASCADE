import copy

from cascade.analysis.visualizer.AnalysisVisualizer import AnalysisVisualizer


class Visualization:
    def __init__(self, visualizer: AnalysisVisualizer):
        self.visualizer = visualizer

    def visualize(self, data, output_path, **kwargs):
        self.visualizer.visualize(copy.deepcopy(data), output_path, **kwargs)
