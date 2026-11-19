"""
Appraisal Analyzer PoC Package
Analyzes XML/PDF appraisal reports for:
1. Photo and label extraction & bed/bath identification.
2. Missing photo label detection.
3. Blank page detection via OpenCV.
"""

from .xml_parser import XMLAppraisalParser
from .blank_detector import BlankPageDetector
from .photo_verifier import PhotoVerifier
from .excel_generator import ExcelReportGenerator, generate_excel_report
from .pipeline import AppraisalReportPipeline

__all__ = [
    "XMLAppraisalParser",
    "BlankPageDetector",
    "PhotoVerifier",
    "ExcelReportGenerator",
    "generate_excel_report",
    "AppraisalReportPipeline",
]
