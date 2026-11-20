"""
photo_verifier.py
Extracts photos and their corresponding labels from appraisal reports,
detects missing labels, and provides photo dimensions and quality metrics.
Supports Subject Photos, Interior Photos, Comparable Sales, Comparable Listings, and Rentals.
"""

import pymupdf
import cv2
import numpy as np
from PIL import Image
import io
import re
import os
from typing import List, Dict, Any, Optional, Tuple


class PhotoVerifier:
    def __init__(self):
        # Mapping for label text keywords to standard categories
        self.label_keyword_map = {
            "bedroom": "Bedroom",
            "bed": "Bedroom",
            "mbr": "Bedroom",
            "master bed": "Bedroom",
            "bathroom": "Bathroom",
            "full bath": "Bathroom",
            "half bath": "Bathroom",
            "bath": "Bathroom",
            "bth": "Bathroom",
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
            "blank": "Blank",
            "left blank intentionally": "Blank",
        }

    def is_photo_page(self, page: pymupdf.Page) -> Tuple[bool, str]:
        """
        Determines if a page is a photo page and returns the form title.
        """
        text = page.get_text()
        first_lines = [l.strip() for l in text.split("\n") if l.strip()][:10]
        header_text = " ".join(first_lines).lower()

        last_lines = [l.strip() for l in text.split("\n") if l.strip()][-6:]
        footer_text = " ".join(last_lines).lower()

        # Exclude non-photo attachments, maps, sketches, and data charts
        # NOTE: 'listing' is NOT excluded here so listing photo pages (Listing 1, 2, 3) are captured!
        exclude_keywords = [
            "license", "roster", "e & o", "e&o", "tax record",
            "form map.loc", "form map.plat", "form map.aerial",
            "location map", "plat map", "building sketch", "form skt",
            "flood map", "aerial", "zoning map", "assessor",
            "analytics addendum", "market conditions addendum",
            "invoice", "thank you"
        ]
        if any(ex in header_text or ex in footer_text for ex in exclude_keywords):
            return False, ""

        photo_keywords = [
            "photo", "photograph", "picpix", "picsix", "picint", "form pic",
            "subject photo", "photograph addendum", "photo addendum",
            "interior photo", "comparable photo", "additional photo", "rental photo",
            "listing photo", "listing", "dlstrnt", "form dlst", "comparable listing"
        ]

        # Check header
        for l in first_lines:
            l_lower = l.lower()
            if any(k in l_lower for k in photo_keywords):
                return True, l

        # Check footer form codes
        if any(k in footer_text for k in ["picpix", "picsix", "picint", "form pic", "dlstrnt", "form dlst"]):
            title = first_lines[0] if first_lines else "Photo Page"
            for l in first_lines:
                if any(w in l.lower() for w in ["photo", "photograph", "addendum", "interior", "comparable", "subject", "listing", "rental"]):
                    title = l
                    break
            return True, title

        # Check for cover page with property photo
        if (
            "form ga1" in header_text
            or "form ga1" in footer_text
            or "appraisal of real property" in header_text
        ):
            img_infos = [
                img for img in page.get_image_info(xrefs=True)
                if img["width"] > 300 and img["height"] > 300 and img["bbox"][1] > 100
            ]
            if img_infos:
                return True, "Cover Page"

        return False, ""

    def _extract_slots_on_page(
        self, page: pymupdf.Page, page_title: str
    ) -> List[Dict[str, Any]]:
        """
        Extracts photos and matches each photo with its corresponding text label
        based on page layout geometry, dynamically adapting to letter/legal sizes.
        """
        H = page.rect.height
        W = page.rect.width

        img_infos = [
            img for img in page.get_image_info(xrefs=True)
            if img["width"] > 200 and img["height"] > 200 and img["bbox"][1] > (0.07 * H)
        ]

        text_blocks = [
            b for b in page.get_text("blocks")
            if b[1] > (0.07 * H) and b[3] < (H - 25)
        ]

        title_lower = page_title.lower()
        page_text_lower = page.get_text().lower()

        # Check for cover page (Form GA1 / Cover Page)
        is_cover = "cover page" in title_lower or (
            "appraisal of real property" in page_text_lower[:300] and len(img_infos) == 1
        ) or (
            "form ga1" in page_text_lower[:300] and len(img_infos) == 1
        )

        # Check if 6-grid layout (2 columns)
        has_right_col_image = any(
            (img["bbox"][0] + img["bbox"][2]) / 2.0 > (W * 0.48) for img in img_infos
        )
        is_6grid = has_right_col_image or any(
            k in title_lower or k in page_text_lower[:250]
            for k in [
                "picsix", "picint", "six", "interior photos",
                "photograph addendum", "additional photos"
            ]
        )

        slots = []
        matched_xrefs = set()

        if is_cover:
            img = img_infos[0] if img_infos else None
            if img:
                matched_xrefs.add(img["xref"])
            slots.append(
                {
                    "slot_name": "Cover Photo",
                    "row": 0,
                    "col": 0,
                    "image_info": img,
                    "label_text": "Subject Property (Cover Photo)",
                }
            )
        elif is_6grid:
            # 6-photo layout: 3 rows x 2 columns
            row_ranges = [
                (0.08 * H, 0.38 * H, "Row 1"),
                (0.38 * H, 0.68 * H, "Row 2"),
                (0.68 * H, 0.96 * H, "Row 3"),
            ]
            x_split = W / 2.0

            for row_idx, (r_min, r_max, r_name) in enumerate(row_ranges):
                for col_idx, col_name in enumerate(["Left", "Right"]):
                    slot_name = f"{r_name} - {col_name}"
                    slot_img = None

                    # Find photo in this grid cell
                    for img in img_infos:
                        cx = (img["bbox"][0] + img["bbox"][2]) / 2.0
                        cy = (img["bbox"][1] + img["bbox"][3]) / 2.0
                        if r_min <= cy <= r_max:
                            if col_idx == 0 and cx < x_split:
                                if slot_img is None:
                                    slot_img = img
                                matched_xrefs.add(img["xref"])
                            elif col_idx == 1 and cx >= x_split:
                                if slot_img is None:
                                    slot_img = img
                                matched_xrefs.add(img["xref"])

                    # Find label blocks located in the label band for this row
                    slot_label = ""
                    cand_blocks = []
                    for b in text_blocks:
                        b_text = b[4].strip()
                        if not b_text or any(
                            ign in b_text.lower()
                            for ign in ["serial#", "esign", "total appraisal software", "alamode", "form pic", "borrower", "lender"]
                        ):
                            continue
                        # Text band directly below this row's photos
                        if (r_min + 0.16 * H) <= b[1] <= (r_max + 0.05 * H):
                            cand_blocks.append(b)

                    # Extract label for this column
                    for b in cand_blocks:
                        b_text = b[4].strip()
                        b_cx = (b[0] + b[2]) / 2.0
                        b_w = b[2] - b[0]
                        lines = [ln.strip() for ln in b_text.split("\n") if ln.strip()]

                        # Multi-column block spanning both sides
                        if b_w > (W * 0.35) and len(lines) >= 2:
                            lbl = lines[col_idx] if col_idx < len(lines) else ""
                            if lbl:
                                slot_label = lbl
                                break
                        else:
                            # Single column block
                            if (col_idx == 0 and b_cx < x_split) or (col_idx == 1 and b_cx >= x_split):
                                slot_label = lines[0] if lines else b_text
                                break

                    slots.append(
                        {
                            "slot_name": slot_name,
                            "row": row_idx,
                            "col": col_idx,
                            "image_info": slot_img,
                            "label_text": slot_label.replace("\n", " ").strip(),
                        }
                    )
        else:
            # 3-photo vertical layout (Subject Photo Page / PICPIX / DLSTRNT Listing Page)
            row_ranges = [
                (0.08 * H, 0.38 * H, "Photo 1 (Top)"),
                (0.38 * H, 0.67 * H, "Photo 2 (Middle)"),
                (0.67 * H, 0.96 * H, "Photo 3 (Bottom)"),
            ]

            for row_idx, (r_min, r_max, s_name) in enumerate(row_ranges):
                slot_img = None
                for img in img_infos:
                    cy = (img["bbox"][1] + img["bbox"][3]) / 2.0
                    if r_min <= cy <= r_max:
                        if slot_img is None:
                            slot_img = img
                        # Account for this and any segmented image tiles belonging to this slot
                        matched_xrefs.add(img["xref"])

                slot_label = ""
                if slot_img:
                    img_top = slot_img["bbox"][1]
                    img_right = slot_img["bbox"][2]

                    # Find candidate label block
                    candidate_blocks = []
                    for b in text_blocks:
                        b_text = b[4].strip()
                        if not b_text or any(
                            ign in b_text.lower()
                            for ign in ["serial#", "esign", "total appraisal software", "alamode", "form pic", "borrower", "lender"]
                        ):
                            continue
                        # Ignore table field list blocks
                        b_text_lower = b_text.lower()
                        if "sales price" in b_text_lower and "gross living" in b_text_lower:
                            continue
                        if "prox. to subject" in b_text_lower and "total rooms" in b_text_lower:
                            continue
                        if "proximity to subjec" in b_text_lower and "list price" in b_text_lower:
                            continue

                        # Check if block is to the right of image and aligned with top of image
                        if b[0] >= (img_right - 30) and b[0] < (W - 30):
                            dy = abs(b[1] - img_top)
                            if dy < 35.0:
                                candidate_blocks.append((dy, b_text))

                    if candidate_blocks:
                        candidate_blocks.sort(key=lambda x: x[0])
                        first_line = candidate_blocks[0][1].split("\n")[0].strip()
                        slot_label = first_line
                    else:
                        # Fallback: check text block directly above or below this image
                        for b in text_blocks:
                            b_text = b[4].strip()
                            if not b_text or any(ign in b_text.lower() for ign in ["serial#", "esign", "total appraisal software", "alamode", "form pic", "borrower"]):
                                continue
                            if (r_min - 25) <= b[1] <= (r_min + 40):
                                slot_label = b_text.split("\n")[0].strip()
                                break
                else:
                    # Slot has no image, check if a label is declared in this row
                    for b in text_blocks:
                        b_text = b[4].strip()
                        if not b_text or any(ign in b_text.lower() for ign in ["serial#", "esign", "total appraisal software", "alamode", "form pic", "borrower"]):
                            continue
                        if (r_min - 35) <= b[1] <= (r_min + 50):
                            lines = [ln.strip() for ln in b_text.split("\n") if ln.strip()]
                            if lines and not any(ign in lines[0].lower() for ign in ["prox. to subject", "proximity to subjec", "sales price", "list price"]):
                                if any(w in lines[0].lower() for w in ["subject", "comparable", "comp", "listing", "rental", "photo", "rear", "front", "street"]):
                                    slot_label = lines[0]
                                    break

                slots.append(
                    {
                        "slot_name": s_name,
                        "row": row_idx,
                        "col": 0,
                        "image_info": slot_img,
                        "label_text": slot_label.replace("\n", " ").strip(),
                    }
                )

        # SAFETY FALLBACK: Catch any image on the page that was not matched to a grid slot
        unmatched_imgs = [img for img in img_infos if img["xref"] not in matched_xrefs]
        for idx, u_img in enumerate(unmatched_imgs):
            u_cx = (u_img["bbox"][0] + u_img["bbox"][2]) / 2.0
            best_lbl = ""
            best_d = 9999.0
            for b in text_blocks:
                b_text = b[4].strip()
                if not b_text or any(
                    h in b_text.lower()
                    for h in ["serial#", "esign", "form pic", "borrower", "alamode"]
                ):
                    continue
                if b[1] >= u_img["bbox"][3] - 10:
                    d = (b[1] - u_img["bbox"][3]) + abs((b[0] + b[2]) / 2.0 - u_cx) * 0.5
                    if d < best_d and d < 100:
                        best_lbl = b_text.split("\n")[0]
                        best_d = d
            slots.append(
                {
                    "slot_name": f"Additional Photo {idx + 1}",
                    "row": 90 + idx,
                    "col": 0,
                    "image_info": u_img,
                    "label_text": best_lbl,
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
            "image_xref": img_info["xref"] if img_info else None,
            "photo_path": None,
            "raw_label": label,
            "normalized_label": normalized_label,
            "status": "VALID",
            "is_missing_label": False,
            "verification_note": "",
            "image_quality": {},
        }

        # Case 1: Empty slot (marked blank or placeholder)
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
                xref = img_info["xref"]
                pix = pymupdf.Pixmap(doc, xref)
                if pix.n >= 5:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)

                # Save photo to disk
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

                # Fast image quality metrics using direct pixmap buffer (no slow re-encoding)
                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                if pix.n >= 3:
                    gray = cv2.cvtColor(img_np[:, :, :3], cv2.COLOR_RGB2GRAY)
                else:
                    gray = img_np

                # Resize if high-res for ultra-fast Laplacian blur & brightness
                max_dim = max(pix.height, pix.width)
                if max_dim > 600:
                    scale = 600.0 / max_dim
                    eval_gray = cv2.resize(gray, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                else:
                    eval_gray = gray

                blur_var = float(cv2.Laplacian(eval_gray, cv2.CV_64F).var())
                mean_brightness = float(np.mean(eval_gray))

                result["image_quality"] = {
                    "width": img_info["width"],
                    "height": img_info["height"],
                    "aspect_ratio": round(
                        img_info["width"] / max(1, img_info["height"]), 2
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
        Inspects all pages, finds photo pages, extracts photos and labels, and saves photos to disk.
        """
        if output_dir is None:
            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            output_dir = os.path.join(
                os.path.dirname(os.path.abspath(pdf_path)),
                "extracted_photos",
                base_name,
            )

        doc = pymupdf.open(pdf_path)
        all_slots = []
        bedroom_photos = 0
        bathroom_photos = 0
        labeled_photos_count = 0
        missing_label_count = 0

        try:
            for p_idx, page in enumerate(doc):
                is_photo, title = self.is_photo_page(page)
                if not is_photo:
                    continue

                slots = self._extract_slots_on_page(page, title)
                for slot in slots:
                    res = self.verify_photo_slot(
                        doc, slot, page_num=p_idx + 1, output_dir=output_dir
                    )
                    # If both photo and label are missing, or it's an unused empty slot, omit it
                    if not res.get("has_image") and not res.get("raw_label"):
                        continue
                    if res.get("status") == "EMPTY_SLOT" and not res.get("has_image"):
                        continue

                    all_slots.append(res)

                    if res.get("is_missing_label"):
                        missing_label_count += 1

                    if res.get("has_image") and res.get("raw_label"):
                        labeled_photos_count += 1

                    # Count bed & bath photos based on label
                    cat = res.get("normalized_label") or res.get("raw_label")
                    if cat and res.get("has_image"):
                        cat_lower = cat.lower()
                        if "bedroom" in cat_lower or "bed" in cat_lower:
                            bedroom_photos += 1
                        elif "bathroom" in cat_lower or "bath" in cat_lower:
                            bathroom_photos += 1
        finally:
            doc.close()

        return {
            "total_slots_scanned": len(all_slots),
            "labeled_photos_count": labeled_photos_count,
            "missing_label_count": missing_label_count,
            "bedroom_photos_identified": bedroom_photos,
            "bathroom_photos_identified": bathroom_photos,
            "extracted_photos_dir": output_dir,
            "slots": all_slots,
        }
