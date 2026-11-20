"""
blank_detector.py
OpenCV and PyMuPDF-based blank and low-content page detector for appraisal reports.
"""

import pymupdf
import cv2
import numpy as np
from typing import List, Dict, Any


class BlankPageDetector:
    def __init__(
        self,
        white_threshold: int = 242,
        content_pct_threshold: float = 0.35,
        edge_density_threshold: float = 0.04,
        laplacian_var_threshold: float = 8.0,
    ):
        self.white_threshold = white_threshold
        self.content_pct_threshold = content_pct_threshold
        self.edge_density_threshold = edge_density_threshold
        self.laplacian_var_threshold = laplacian_var_threshold

    def analyze_page(self, page: pymupdf.Page, page_number: int) -> Dict[str, Any]:
        """
        Analyzes a single PDF page for blankness using fast metadata checks and OpenCV.
        """
        text = page.get_text()
        raw_lines = [l.strip() for l in text.split("\n") if l.strip()]

        # Check text blocks located specifically in the body region
        blocks = page.get_text("blocks")
        h_pt = page.rect.height
        body_text_blocks = [
            b
            for b in blocks
            if b[1] >= (h_pt * 0.10) and b[3] <= (h_pt * 0.92) and b[4].strip()
        ]
        images = page.get_images()

        # Fast path: pages with attached images or 3+ body text blocks are definitely NOT blank
        if len(images) > 0 or len(body_text_blocks) >= 3:
            return {
                "page_number": page_number,
                "is_blank": False,
                "classification": "NON_BLANK",
                "content_pixel_pct": 5.0,
                "laplacian_var": 50.0,
                "edge_density_pct": 1.0,
                "total_text_lines": len(raw_lines),
                "body_blocks_count": len(body_text_blocks),
                "sample_header": raw_lines[:2] if raw_lines else [],
            }

        # Sparse candidate page: render at 72 DPI for fast edge/pixel analysis
        pix = page.get_pixmap(dpi=72)
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            (pix.height, pix.width, pix.n)
        )

        if pix.n == 4:
            gray = cv2.cvtColor(img_np, cv2.COLOR_RGBA2GRAY)
        elif pix.n == 3:
            gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_np

        h, w = gray.shape
        body_top = int(h * 0.11)
        body_bottom = int(h * 0.92)
        body_left = int(w * 0.04)
        body_right = int(w * 0.96)
        body = gray[body_top:body_bottom, body_left:body_right]

        total_pixels = max(1, body.size)
        non_white_mask = body < self.white_threshold
        non_white_count = np.sum(non_white_mask)
        content_pixel_pct = (non_white_count / total_pixels) * 100.0

        # Laplacian variance
        laplacian = cv2.Laplacian(body, cv2.CV_64F)
        laplacian_var = float(laplacian.var())

        # Canny edge density
        edges = cv2.Canny(body, 50, 150)
        edge_pixels = np.sum(edges > 0)
        edge_density = (edge_pixels / total_pixels) * 100.0

        # Determine blank status
        is_blank = False
        classification = "NON_BLANK"

        if content_pixel_pct < 0.05 and edge_density < 0.01:
            is_blank = True
            classification = "COMPLETELY_BLANK"
        elif (
            content_pixel_pct < self.content_pct_threshold
            and edge_density < self.edge_density_threshold
            and len(body_text_blocks) == 0
        ):
            is_blank = True
            classification = "TEMPLATE_HEADER_ONLY_BLANK"
        elif (
            laplacian_var < self.laplacian_var_threshold
            and content_pixel_pct < self.content_pct_threshold * 1.5
            and len(body_text_blocks) == 0
        ):
            is_blank = True
            classification = "LOW_CONTENT_BLANK"

        return {
            "page_number": page_number,
            "is_blank": is_blank,
            "classification": classification,
            "content_pixel_pct": round(content_pixel_pct, 3),
            "laplacian_var": round(laplacian_var, 2),
            "edge_density_pct": round(edge_density, 3),
            "total_text_lines": len(raw_lines),
            "body_blocks_count": len(body_text_blocks),
            "sample_header": raw_lines[:2] if raw_lines else [],
        }

    def detect_blank_pages(self, pdf_path: str) -> List[Dict[str, Any]]:
        """
        Scans all pages in a PDF and returns detailed results for every page,
        marking which ones are blank.
        """
        doc = pymupdf.open(pdf_path)
        try:
            results = []
            for i in range(len(doc)):
                res = self.analyze_page(doc[i], page_number=i + 1)
                results.append(res)
            return results
        finally:
            doc.close()
