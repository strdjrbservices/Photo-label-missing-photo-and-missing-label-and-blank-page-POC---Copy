"""
photo_verifier.py
Strict and robust extraction of property photos and their corresponding labels
across all appraisal software formats (TOTAL, ACI, ClickFORMS, Appraise-It, SFREP, narrative).
Includes dual-engine text coordinate matching (PyMuPDF + pdfplumber fallback),
missing photo and missing label detection, and ultra-fast image quality metrics.
"""

import os
import io
import re
from typing import List, Dict, Any, Optional, Tuple
import cv2
import numpy as np
from PIL import Image
import pymupdf

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


class PhotoVerifier:
    def __init__(self):
        # Comprehensive mapping of label keywords to standard appraisal categories
        self.label_keyword_map = {
            "bedroom": "Bedroom",
            "bed": "Bedroom",
            "mbr": "Bedroom",
            "master bed": "Bedroom",
            "primary bed": "Bedroom",
            "bathroom": "Bathroom",
            "full bath": "Bathroom",
            "half bath": "Bathroom",
            "bath": "Bathroom",
            "bth": "Bathroom",
            "primary bath": "Bathroom",
            "kitchen": "Kitchen",
            "living": "Living Room",
            "dining": "Dining Room",
            "front": "Exterior Front",
            "subject front": "Exterior Front",
            "rear": "Exterior Rear",
            "subject rear": "Exterior Rear",
            "back": "Exterior Rear",
            "yard": "Exterior Rear",
            "street": "Street View",
            "subject street": "Street View",
            "comparable": "Comparable",
            "comp": "Comparable",
            "listing": "Comparable Listing",
            "comparable listing": "Comparable Listing",
            "rental": "Rental Comparable",
            "rental comparable": "Rental Comparable",
            "garage": "Garage",
            "patio": "Porch / Patio",
            "porch": "Porch / Patio",
            "gazebo": "Porch / Patio",
            "deck": "Porch / Patio",
            "driveway": "Driveway / Gate",
            "gate": "Driveway / Gate",
            "water heater": "Water Heater / HVAC",
            "hvac": "Water Heater / HVAC",
            "heater": "Water Heater / HVAC",
            "furnace": "Water Heater / HVAC",
            "a/c": "Water Heater / HVAC",
            "air handler": "Water Heater / HVAC",
            "air condition": "Water Heater / HVAC",
            "breaker": "Electrical Panel",
            "electric": "Electrical Panel",
            "panel": "Electrical Panel",
            "smoke": "Smoke / CO Detector",
            "co detector": "Smoke / CO Detector",
            "co2": "Smoke / CO Detector",
            "alarm": "Smoke / CO Detector",
            "detector": "Smoke / CO Detector",
            "solar": "Solar Panels",
            "family room": "Family Room",
            "utility": "Utility / Laundry",
            "laundry": "Utility / Laundry",
            "basement": "Basement",
            "attic": "Attic",
            "outlet": "Electrical / Repairs",
            "repair": "Repairs / Condition",
            "pool": "Pool / Spa",
            "spa": "Pool / Spa",
            "blank": "Blank",
            "left blank intentionally": "Blank",
        }

    def is_photo_page(self, page: pymupdf.Page) -> Tuple[bool, str]:
        """
        Determines if a page is a photo page and returns the form title.
        Uses fast metadata checks (< 5ms) without slow xref decompressive traversal.
        """
        H = page.rect.height
        W = page.rect.width

        text = page.get_text()
        first_lines = [l.strip() for l in text.split("\n") if l.strip()][:12]
        header_text = " ".join(first_lines).lower()

        last_lines = [l.strip() for l in text.split("\n") if l.strip()][-6:]
        footer_text = " ".join(last_lines).lower()

        # Exclude non-photo attachments, maps, sketches, charts, invoices, and certificates
        exclude_keywords = [
            "license", "roster", "e & o", "e&o", "tax record",
            "form map.loc", "form map.plat", "form map.aerial",
            "location map", "plat map", "building sketch", "form skt",
            "flood map", "aerial map", "zoning map", "assessor",
            "floorplan", "sketch",
            "analytics addendum", "market conditions addendum",
            "invoice", "thank you", "qualifications of appraiser"
        ]
        if any(ex in header_text or ex in footer_text for ex in exclude_keywords):
            return False, ""

        # Fast scan embedded images in body area without xrefs=True
        img_infos = [
            img for img in page.get_image_info(xrefs=False)
            if img["width"] >= 100 and img["height"] >= 80
            and img["bbox"][1] > (0.04 * H) and img["bbox"][3] < (0.96 * H)
        ]

        # Rule 1: 2 or more real photos in body area -> Guaranteed photo page across all appraisal formats!
        if len(img_infos) >= 2:
            title = first_lines[0] if first_lines else "Photo Page"
            for l in first_lines:
                if any(w in l.lower() for w in [
                    "photo", "photograph", "addendum", "interior", "comparable",
                    "subject", "listing", "rental", "inspection"
                ]):
                    title = l
                    break
            return True, title

        # Rule 2: 1 large photo on Cover Page or Subject Photo Addendum
        if len(img_infos) == 1:
            im = img_infos[0]
            if (im["width"] >= 200 and im["height"] >= 180) or (im["bbox"][3] - im["bbox"][1] > 0.20 * H):
                if any(k in header_text or k in footer_text for k in [
                    "ga1", "appraisal of real property", "cover", "subject photo",
                    "photo addendum", "subject property", "photo page"
                ]):
                    return True, "Subject Property (Cover / Photo)"

        # Rule 3: Known photo form codes in footer or header (TOTAL, ACI, ClickFORMS, Appraise-It)
        photo_form_codes = [
            "pht6", "pht3", "pht12", "phtc", "phtr", "picpix", "picsix", "picint",
            "dlstrnt", "form dlst", "form pic", "photo addendum", "photograph addendum",
            "interior photos", "comparable photos", "subject photos"
        ]
        if any(k in footer_text or k in header_text for k in photo_form_codes):
            title = first_lines[0] if first_lines else "Photo Page"
            for l in first_lines:
                if any(w in l.lower() for w in [
                    "photo", "photograph", "addendum", "interior", "comparable",
                    "subject", "listing", "rental"
                ]):
                    title = l
                    break
            return True, title

        return False, ""

    def _extract_slots_on_page(
        self,
        page: pymupdf.Page,
        page_title: str,
        doc: Optional[pymupdf.Document] = None,
        plumber_doc: Optional[Any] = None,
        page_num: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Strictly extracts photos and matches each photo with its corresponding text label
        based on page layout geometry, column awareness, and word-level coordinate matching.
        """
        H = page.rect.height
        W = page.rect.width

        # Retrieve images on this photo page with xrefs
        img_infos = [
            img for img in page.get_image_info(xrefs=True)
            if img["width"] >= 100 and img["height"] >= 80
            and img["bbox"][1] > (0.04 * H) and img["bbox"][3] < (0.96 * H)
        ]

        # Fallback if xref was not attached in get_image_info
        raw_page_imgs = page.get_images()
        for idx, img in enumerate(img_infos):
            if "xref" not in img or not img["xref"]:
                if idx < len(raw_page_imgs):
                    img["xref"] = raw_page_imgs[idx][0]

        words = page.get_text("words")
        text_blocks = [b for b in page.get_text("blocks") if b[1] > (0.04 * H) and b[3] < (H - 20)]

        # Check if cover page
        title_lower = page_title.lower()
        page_text_lower = page.get_text().lower()
        is_cover = (
            "cover" in title_lower
            or "appraisal of real property" in page_text_lower[:300]
            or "form ga1" in page_text_lower[:300]
        ) and len(img_infos) <= 1

        if is_cover and img_infos:
            img = img_infos[0]
            return [
                {
                    "slot_name": "Cover Photo",
                    "row": 0,
                    "col": 0,
                    "image_info": img,
                    "label_text": "Subject Property (Cover Photo)",
                }
            ]

        # Spatial sorting: top-to-bottom, left-to-right
        sorted_imgs = sorted(
            img_infos,
            key=lambda im: (round(im["bbox"][1] / 50.0) * 50, im["bbox"][0])
        )

        left_imgs = [im for im in img_infos if (im["bbox"][0] + im["bbox"][2]) / 2.0 < (W * 0.5)]
        right_imgs = [im for im in img_infos if (im["bbox"][0] + im["bbox"][2]) / 2.0 >= (W * 0.5)]
        is_two_col = bool(left_imgs and right_imgs)
        x_split = W * 0.48

        slots = []

        for idx, img in enumerate(sorted_imgs):
            ix0, iy0, ix1, iy1 = img["bbox"]
            icx = (ix0 + ix1) / 2.0
            icy = (iy0 + iy1) / 2.0

            is_left = icx < (W * 0.5)
            row_num = 1 if icy < (0.38 * H) else (2 if icy < (0.68 * H) else 3)
            col_name = "Left" if is_left else "Right"
            slot_name = f"Row {row_num} - {col_name}" if (len(img_infos) > 3 or is_two_col) else f"Photo {idx + 1}"

            label = ""

            # Priority 1: Check to the right of the image (TOTAL 3-photo layouts: Subject & Comps)
            if ix1 < (W * 0.65) and not is_two_col:
                cand_right = []
                for b in text_blocks:
                    b_text = b[4].strip()
                    if not b_text:
                        continue
                    b_lower = b_text.lower()
                    if any(
                        ign in b_lower
                        for ign in [
                            "serial#", "esign", "total appraisal", "alamode",
                            "borrower", "lender", "file no", "sales price", "gross living"
                        ]
                    ):
                        continue
                    if b[0] >= (ix1 - 25) and b[0] < (W - 20):
                        if abs(b[1] - iy0) < 35.0:
                            first_line = b_text.split("\n")[0].strip()
                            cand_right.append((abs(b[1] - iy0), first_line))
                if cand_right:
                    cand_right.sort(key=lambda x: x[0])
                    label = cand_right[0][1]

            # Priority 2: Directly below the image using word-level spatial bounding boxes
            if not label:
                below_words = []
                for w in words:
                    wx0, wy0, wx1, wy1, word = w[:5]
                    # Vertical band directly below photo
                    if (iy1 - 5) <= wy0 <= (iy1 + 65):
                        if is_two_col:
                            in_col = (wx1 <= x_split) if is_left else (wx0 >= x_split)
                            if in_col:
                                w_lower = word.lower().strip(",.:;")
                                if w_lower in [
                                    "borrower", "lender", "file", "produced", "using",
                                    "aci", "software", "pht6", "pht3", "pht12", "alamode"
                                ]:
                                    continue
                                below_words.append(w)
                        else:
                            if (ix0 - 30) <= wx0 <= (ix1 + 30):
                                w_lower = word.lower().strip(",.:;")
                                if w_lower in [
                                    "borrower", "lender", "file", "produced", "using",
                                    "aci", "software", "alamode"
                                ]:
                                    continue
                                below_words.append(w)

                if below_words:
                    below_words.sort(key=lambda w: (round(w[1] / 6.0) * 6, w[0]))
                    first_line_y = round(below_words[0][1] / 6.0) * 6
                    line_words = [
                        w[4] for w in below_words
                        if abs(round(w[1] / 6.0) * 6 - first_line_y) <= 6
                    ]
                    label = " ".join(line_words).strip()

            # Priority 3: Directly above the image using word-level spatial bounding boxes
            if not label:
                above_words = []
                for w in words:
                    wx0, wy0, wx1, wy1, word = w[:5]
                    if (iy0 - 35) <= wy1 <= (iy0 + 5):
                        if is_two_col:
                            in_col = (wx1 <= x_split) if is_left else (wx0 >= x_split)
                        else:
                            in_col = (ix0 - 30) <= wx0 <= (ix1 + 30)
                        if in_col:
                            w_lower = word.lower().strip(",.:;")
                            if w_lower in [
                                "borrower", "lender", "file", "produced", "using",
                                "aci", "software", "subject", "alamode"
                            ]:
                                continue
                            above_words.append(w)

                if above_words:
                    above_words.sort(key=lambda w: (round(w[1] / 6.0) * 6, w[0]))
                    first_line_y = round(above_words[0][1] / 6.0) * 6
                    line_words = [
                        w[4] for w in above_words
                        if abs(round(w[1] / 6.0) * 6 - first_line_y) <= 6
                    ]
                    label = " ".join(line_words).strip()

            # Priority 4: Secondary fallback with pdfplumber if installed and label still empty
            if not label and plumber_doc is not None:
                try:
                    p_page = plumber_doc.pages[page_num - 1]
                    # Crop to column band below image
                    c_x0 = 0 if is_left else x_split
                    c_x1 = x_split if is_left else W
                    c_y0 = max(0, iy1 - 5)
                    c_y1 = min(H, iy1 + 65)
                    cropped = p_page.crop((c_x0, c_y0, c_x1, c_y1))
                    plumber_text = cropped.extract_text()
                    if plumber_text:
                        p_lines = [ln.strip() for ln in plumber_text.split("\n") if ln.strip()]
                        for pl in p_lines:
                            if not any(
                                ign in pl.lower()
                                for ign in ["borrower", "lender", "file no", "produced", "aci", "pht6"]
                            ):
                                label = pl
                                break
                except Exception:
                    pass

            # Filter table data residue
            if label:
                lbl_lower = label.lower()
                if any(ign in lbl_lower for ign in ["sales price", "gross living", "prox. to subject", "proximity to subjec", "list price"]):
                    label = ""

            slots.append(
                {
                    "slot_name": slot_name,
                    "row": row_num - 1,
                    "col": 0 if is_left else 1,
                    "image_info": img,
                    "label_text": label.replace("\n", " ").strip(),
                }
            )

        return slots

    def _normalize_label(self, label_text: str) -> Optional[str]:
        """
        Maps a label string (e.g. 'Unit 1 Kitchen', 'Subject Rear', 'Listing 1') to a normalized category.
        """
        if not label_text:
            return None
        text_lower = label_text.lower()
        if text_lower in ["blank", "none", "n/a"] or "blank" in text_lower:
            return "Blank"

        for kw, cat in self.label_keyword_map.items():
            pattern = rf"\b{re.escape(kw)}\b"
            if re.search(pattern, text_lower):
                return cat
        return label_text

    def verify_photo_slot(
        self,
        doc: pymupdf.Document,
        slot: Dict[str, Any],
        page_num: int,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extracts photo slot info, saves photo to disk, calculates image quality metrics, and evaluates label status.
        """
        img_info = slot["image_info"]
        label = slot["label_text"]
        normalized_label = self._normalize_label(label)

        has_image = img_info is not None
        has_label = bool(label and label.lower() not in ["blank", ""])

        clean_img_info = None
        if img_info:
            clean_img_info = {
                "xref": img_info.get("xref"),
                "width": img_info.get("width"),
                "height": img_info.get("height"),
                "bbox": list(img_info.get("bbox", [])),
                "size": img_info.get("size"),
            }

        result = {
            "page_number": page_num,
            "slot_name": slot["slot_name"],
            "has_image": has_image,
            "image_info": clean_img_info,
            "image_xref": img_info["xref"] if (img_info and "xref" in img_info) else None,
            "photo_path": None,
            "raw_label": label,
            "normalized_label": normalized_label,
            "status": "VALID",
            "is_missing_label": False,
            "verification_note": "",
            "image_quality": {},
        }

        # Case 1: Empty slot
        if normalized_label == "Blank" or "blank" in label.lower():
            result["status"] = "EMPTY_SLOT"
            result["is_missing_label"] = False
            result["verification_note"] = "Empty photo slot explicitly marked as Blank."
            return result

        if not has_image and not has_label:
            result["status"] = "EMPTY_SLOT"
            result["verification_note"] = "Empty photo slot."
            return result

        # Case 2: Missing label (photo present, but no label)
        if has_image and not has_label:
            result["status"] = "MISSING_LABEL"
            result["is_missing_label"] = True
            result["verification_note"] = (
                "Photo present in report, but label is missing or empty."
            )

        # Case 3: Missing photo (label present, but no photo)
        if not has_image and has_label:
            result["status"] = "MISSING_PHOTO"
            result["verification_note"] = (
                f"Label '{label}' defined, but no photo is attached in this slot."
            )
            return result

        # Case 4: Photo present
        if has_image:
            photo_path = None
            try:
                xref = img_info.get("xref")
                if xref:
                    pix = pymupdf.Pixmap(doc, xref)
                    # Convert to standard 24-bit RGB if CMYK, grayscale or has alpha/mask
                    if pix.n != 3 or pix.alpha != 0:
                        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)

                    # Save photo to disk with sanitized filename
                    if output_dir:
                        os.makedirs(output_dir, exist_ok=True)
                        clean_slot = re.sub(
                            r"[^\w\-]+", "_", slot["slot_name"]
                        ).strip("_")
                        clean_lbl = (
                            re.sub(r"[^\w\-]+", "_", label[:30]).strip("_")
                            if label
                            else "unlabeled"
                        )
                        img_name = (
                            f"p{page_num}_{clean_slot}_{clean_lbl}_xref{xref}.png"
                        )
                        save_full_path = os.path.join(output_dir, img_name)
                        pix.save(save_full_path)
                        photo_path = os.path.abspath(save_full_path)

                    # Ultra-fast quality metrics directly from pixmap sample buffer
                    img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                    if pix.n >= 3:
                        gray = cv2.cvtColor(img_np[:, :, :3], cv2.COLOR_RGB2GRAY)
                    else:
                        gray = img_np

                    max_dim = max(pix.height, pix.width)
                    if max_dim > 600:
                        scale = 600.0 / max_dim
                        eval_gray = cv2.resize(gray, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                    else:
                        eval_gray = gray

                    blur_var = float(cv2.Laplacian(eval_gray, cv2.CV_64F).var())
                    mean_brightness = float(np.mean(eval_gray))

                    result["image_quality"] = {
                        "width": img_info.get("width", pix.width),
                        "height": img_info.get("height", pix.height),
                        "aspect_ratio": round(
                            img_info.get("width", pix.width) / max(1, img_info.get("height", pix.height)), 2
                        ),
                        "blur_score": round(blur_var, 1),
                        "brightness": round(mean_brightness, 1),
                        "is_blurry": blur_var < 30.0,
                    }
            except Exception:
                pass

            result["photo_path"] = photo_path
            if clean_img_info:
                clean_img_info["photo_path"] = photo_path

            if has_label:
                result["status"] = "LABELED"
                result["verification_note"] = f"Photo labeled as '{label}'."

        return result

    def verify_all_photos(
        self, pdf_path: str, output_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Inspects all pages, finds photo pages across all appraisal software vendors,
        extracts photos and labels strictly, and saves photos to disk.
        """
        if output_dir is None:
            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            output_dir = os.path.join(
                os.path.dirname(os.path.abspath(pdf_path)),
                "extracted_photos",
                base_name,
            )

        doc = pymupdf.open(pdf_path)
        plumber_doc = None
        if pdfplumber is not None:
            try:
                plumber_doc = pdfplumber.open(pdf_path)
            except Exception:
                plumber_doc = None

        all_slots = []
        bedroom_photos = 0
        bathroom_photos = 0
        total_room_photos = 0
        labeled_photos_count = 0
        missing_label_count = 0

        try:
            for p_idx, page in enumerate(doc):
                is_photo, title = self.is_photo_page(page)
                if not is_photo:
                    continue

                slots = self._extract_slots_on_page(
                    page=page,
                    page_title=title,
                    doc=doc,
                    plumber_doc=plumber_doc,
                    page_num=p_idx + 1
                )
                for slot in slots:
                    res = self.verify_photo_slot(
                        doc, slot, page_num=p_idx + 1, output_dir=output_dir
                    )
                    # If both photo and label are missing, omit from inventory
                    if not res.get("has_image") and not res.get("raw_label"):
                        continue
                    if res.get("status") == "EMPTY_SLOT" and not res.get("has_image"):
                        continue

                    all_slots.append(res)

                    if res.get("is_missing_label"):
                        missing_label_count += 1

                    if res.get("has_image") and res.get("raw_label"):
                        labeled_photos_count += 1

                    cat = res.get("normalized_label") or res.get("raw_label")
                    if cat and res.get("has_image"):
                        cat_lower = cat.lower()
                        if "bedroom" in cat_lower or "bed" in cat_lower:
                            bedroom_photos += 1
                            total_room_photos += 1
                        elif "bathroom" in cat_lower or "bath" in cat_lower:
                            bathroom_photos += 1
                        elif any(r in cat_lower for r in ["kitchen", "living", "dining", "family", "den", "office", "sunroom"]):
                            total_room_photos += 1
        finally:
            doc.close()
            if plumber_doc:
                try:
                    plumber_doc.close()
                except Exception:
                    pass

        return {
            "total_slots_scanned": len(all_slots),
            "labeled_photos_count": labeled_photos_count,
            "missing_label_count": missing_label_count,
            "bedroom_photos_identified": bedroom_photos,
            "bathroom_photos_identified": bathroom_photos,
            "total_room_photos_identified": total_room_photos,
            "extracted_photos_dir": output_dir,
            "slots": all_slots,
        }
