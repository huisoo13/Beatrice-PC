"""Public real-time recognition API; imports do not load Qt or inference models."""
from .pipeline import FrameRecognition,RecognitionPipeline
from .service import RecognitionEvents,RecognitionService

__all__=['FrameRecognition','RecognitionPipeline','RecognitionEvents','RecognitionService']
