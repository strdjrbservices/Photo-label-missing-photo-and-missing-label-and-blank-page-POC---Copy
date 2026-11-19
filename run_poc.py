"""
run_poc.py
Command-line execution script for the Appraisal Analysis PoC.
Processes XML reports (or companion PDFs) and prints analysis for:
1. Bed/Bath photo identification & label extraction
2. Missing photo labels
3. Blank page detection
"""

import os
import sys
import glob
import json
import argparse
from appraisal_analyzer import AppraisalReportPipeline


def print_separator(char="=", length=80):
    print(char * length)


def display_report_findings(report: dict):
    summary = report["summary"]
    findings = summary["findings"]
    xml_meta = summary["xml_property_metadata"]

    print_separator("=")
    print(f"  APPRAISAL REPORT ANALYSIS: {summary['file_name']}")
    print_separator("=")
    print(f"  PDF Document: {summary['pdf_analyzed']}")
    print(f"  Analysis Time: {summary['execution_time_seconds']} seconds")
    if xml_meta.get("address"):
        print(f"  Subject Property: {xml_meta['address']}, {xml_meta['city']}")
        print(
            f"  XML Records: Bedrooms={xml_meta['bedrooms']} | Bathrooms={xml_meta['bathrooms']} | GLA={xml_meta['gross_living_area']} sqft"
        )
    print_separator("-")

    # 1. Photo and Label Extraction
    p_task = findings.get("task1_photo_and_label_inventory") or findings.get(
        "task1_photo_identification_and_verification", {}
    )
    print("\n[TASK 1] Photo & Label Extraction:")
    print(f"  * Total Photo Slots Scanned: {p_task.get('total_photo_slots', 0)}")
    print(f"  * Total Photos with Labels: {p_task.get('labeled_photos_count', 0)}")
    print(
        f"  * Bedrooms Identified from Labels: {p_task.get('bedroom_photos_identified', 0)}"
    )
    print(
        f"  * Bathrooms Identified from Labels: {p_task.get('bathroom_photos_identified', 0)}"
    )

    labeled_photos = [
        s
        for s in p_task.get("photos", p_task.get("slots", []))
        if s.get("has_image") and s.get("raw_label")
    ]
    if labeled_photos:
        print("  -> Photo Inventory (Slot & Label):")
        for s in labeled_photos:
            cat_str = f" [{s['normalized_label']}]" if s.get("normalized_label") else ""
            print(
                f"     [Page {s['page_number']} | {s['slot_name']}] '{s['raw_label']}'{cat_str}"
            )
    else:
        print("  -> No labeled photos found.")

    # 2. Missing Labels
    m_task = findings["task2_missing_photo_labels"]
    print("\n[TASK 2] Missing Photo Labels:")
    print(f"  * Missing Label Count: {m_task['missing_label_count']}")
    if m_task["missing_labels"]:
        print("  -> Flagged Photos Missing Labels:")
        for ml in m_task["missing_labels"]:
            print(
                f"     [Page {ml['page_number']} | {ml['slot_name']}] Photo present without a label."
            )
    else:
        print(
            "  -> No unlabeled photos detected (all attached photos possess proper labels)."
        )

    # 3. Blank Pages
    b_task = findings["task3_blank_pages"]
    print("\n[TASK 3] Blank Page Detection (OpenCV):")
    print(f"  * Total Pages Evaluated: {b_task['total_pages_scanned']}")
    print(f"  * Blank Pages Detected: {b_task['blank_pages_count']}")
    if b_task["blank_pages"]:
        print("  -> Flagged Blank Pages:")
        for bp in b_task["blank_pages"]:
            print(
                f"     Page {bp['page_number']}: Type={bp['classification']} | Content={bp['content_pixel_pct']}% | Edge Density={bp['edge_density_pct']}%"
            )
    else:
        print("  -> No blank pages detected in report.")

    print_separator("=")


def main():
    parser = argparse.ArgumentParser(
        description="PoC: Appraisal XML/PDF Report Analysis"
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="2611-00509(1004).xml",
        help="Path to XML or PDF report",
    )
    parser.add_argument(
        "--all", action="store_true", help="Process all XML files in workspace"
    )
    parser.add_argument(
        "--task",
        "-t",
        default="all",
        help="Specify which task(s) to execute (comma-separated): all, photos (1 & 2), blank (3).",
    )
    parser.add_argument(
        "--save-json", action="store_true", help="Save results to JSON file"
    )
    parser.add_argument(
        "--excel",
        "-e",
        "--save-excel",
        dest="save_excel",
        action="store_true",
        default=True,
        help="Save audit results to Excel (.xlsx) report with photo paths (default: True)",
    )
    parser.add_argument(
        "--no-excel",
        dest="save_excel",
        action="store_false",
        help="Disable Excel report generation",
    )
    args = parser.parse_args()

    selected_tasks = [t.strip() for t in args.task.split(",")]
    pipeline = AppraisalReportPipeline()

    if args.all:
        xml_files = sorted(glob.glob("*.xml"))
        print(
            f"Running batch analysis on {len(xml_files)} XML reports (Tasks: {', '.join(selected_tasks)})..."
        )
        all_results = {}
        for xf in xml_files:
            rep = pipeline.run(xf, tasks=selected_tasks)
            display_report_findings(rep)
            all_results[xf] = rep["summary"]

            if args.save_excel:
                excel_out = os.path.splitext(xf)[0] + "_audit_report.xlsx"
                pipeline.generate_excel(rep, excel_out)
                print(f"[+] Saved Excel report to {excel_out}")

        if args.save_json:
            with open("all_reports_analysis.json", "w") as f:
                json.dump(all_results, f, indent=2, default=str)
            print("[+] Saved all results to all_reports_analysis.json")
    else:
        rep = pipeline.run(args.file, tasks=selected_tasks)
        display_report_findings(rep)
        if args.save_json:
            out_file = os.path.splitext(args.file)[0] + "_analysis.json"
            with open(out_file, "w") as f:
                json.dump(rep, f, indent=2, default=str)
            print(f"[+] Saved analysis results to {out_file}")

        if args.save_excel:
            excel_out = os.path.splitext(args.file)[0] + "_audit_report.xlsx"
            pipeline.generate_excel(rep, excel_out)
            print(f"[+] Saved Excel report with photo paths to {excel_out}")


if __name__ == "__main__":
    main()
