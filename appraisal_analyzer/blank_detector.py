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
        Analyzes a single PDF page for blankness using fast metadata checks,
        header-block bounding geometry, and OpenCV computer vision analysis.
        If a page contains only a header block (Borrower, Property Address, City, State, Zip, Lender/Client)
        and the rest of the body region is blank, it is strictly classified as a blank page.
        """
        h_pt = page.rect.height
        w_pt = page.rect.width
        blocks = page.get_text("blocks")
        raw_lines = [l.strip() for l in page.get_text().split("\n") if l.strip()]

        # 1. Identify header block presence and bounding Y coordinate
        header_keywords = [
            "borrower", "property address", "lender", "client", "lender/client",
            "appraisal of real property", "subject property", "file no", "case no"
        ]
        header_blocks = [
            b for b in blocks 
            if b[1] < (h_pt * 0.22) and any(kw in b[4].lower() for kw in header_keywords)
        ]
        has_header = len(header_blocks) > 0

        if header_blocks:
            header_bottom_y = max(b[3] for b in header_blocks)
        else:
            top_blocks = [b for b in blocks if b[3] <= (h_pt * 0.15)]
            header_bottom_y = max((b[3] for b in top_blocks), default=h_pt * 0.10)

        # 2. Identify footer boundary
        footer_blocks = [b for b in blocks if b[1] >= (h_pt * 0.93)]
        footer_top_y = min((b[1] for b in footer_blocks), default=h_pt * 0.93)

        # 3. Determine the body region below the header block
        body_y0 = max(header_bottom_y + 4, h_pt * 0.13)
        body_y1 = min(footer_top_y - 4, h_pt * 0.93)

        # 4. Check for placed images in the body region (do NOT use get_images which counts unused catalog assets)
        image_infos = page.get_image_info()
        body_images = [
            img for img in image_infos
            if img.get("bbox", [0, 0, 0, 0])[3] > body_y0
            and img.get("bbox", [0, 0, 0, 0])[1] < body_y1
            and img.get("width", 0) >= 30
            and img.get("height", 0) >= 30
        ]

        # 5. Check for body text blocks strictly within the body region
        body_text_blocks = [
            b for b in blocks
            if b[1] >= (body_y0 - 2) and b[3] <= (body_y1 + 2) and b[4].strip()
        ]
        filtered_body_blocks = []
        for b in body_text_blocks:
            txt_lower = b[4].strip().lower()
            # Ignore standard form software footer branding or template table residual lines
            if any(ign in txt_lower for ign in [
                "total appraisal software",
                "form tadd", "form 1004", "form gadd", "form uad", "form map", "form skt", "form ga1",
                "produced using", "a la mode", "aci", "clickforms", "alamode",
                "file no.", "file #"
            ]):
                continue
            if b[3] <= (header_bottom_y + 8):
                continue
            filtered_body_blocks.append(b)

        # 6. OpenCV analysis of the page body area
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

        h_px, w_px = gray.shape
        y0_px = int(h_px * (body_y0 / h_pt))
        y1_px = int(h_px * (body_y1 / h_pt))
        x0_px = int(w_px * 0.04)
        x1_px = int(w_px * 0.96)

        if y1_px <= y0_px:
            y0_px = int(h_px * 0.14)
            y1_px = int(h_px * 0.92)

        body = gray[y0_px:y1_px, x0_px:x1_px]
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

        # 7. Decision logic
        is_blank = False
        classification = "NON_BLANK"

        # If there are placed images or multiple body text blocks, it is definitely NOT blank
        if len(body_images) > 0 or len(filtered_body_blocks) >= 2:
            is_blank = False
            classification = "NON_BLANK"
        elif content_pixel_pct < 0.05 and edge_density < 0.01 and len(filtered_body_blocks) == 0:
            is_blank = True
            classification = "COMPLETELY_BLANK"
        elif has_header and len(body_images) == 0 and len(filtered_body_blocks) == 0:
            # User revision requirement: page contains header block and rest is blank -> blank page
            if (
                content_pixel_pct < self.content_pct_threshold
                and edge_density < self.edge_density_threshold
            ) or laplacian_var < self.laplacian_var_threshold:
                is_blank = True
                classification = "TEMPLATE_HEADER_ONLY_BLANK"
        elif len(filtered_body_blocks) == 0 and len(body_images) == 0:
            if (
                content_pixel_pct < self.content_pct_threshold
                and edge_density < self.edge_density_threshold
            ) or laplacian_var < self.laplacian_var_threshold:
                is_blank = True
                classification = "LOW_CONTENT_BLANK"

        return {
            "page_number": page_number,
            "is_blank": is_blank,
            "classification": classification,
            "content_pixel_pct": round(float(content_pixel_pct), 3),
            "laplacian_var": round(float(laplacian_var), 2),
            "edge_density_pct": round(float(edge_density), 3),
            "total_text_lines": len(raw_lines),
            "body_blocks_count": len(filtered_body_blocks),
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
