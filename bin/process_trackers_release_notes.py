#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 SUSE LLC and contributors
#
# SPDX-License-Identifier: Apache-2.0

"""
SUSE CVE & Bugzilla AsciiDoc Formatter

This script processes text files containing CVE references and SUSE Bugzilla IDs,
standardizing them into a clean, uniform AsciiDoc list format.

Key capabilities:
  - Validates SUSE CVE URLs (checks for 404s) and applies AsciiDoc link formatting.
  - Queries the SUSE Bugzilla REST API to find missing Bug IDs for a given CVE.
  - Performs reverse-lookups to find missing CVEs from a given Bugzilla ID.
  - Normalizes bullet points and list indentation.
  - Groups multiple Bugzilla references (bsc#, boo#, bnc#) at the end of a line
    into a single formatted block.
  - Normalize boo#, bnc# references to bsc#
  - Formats FATE references (fate#) into valid AsciiDoc links.
  - Always appends a wrapped summary of all trackers (Security fixes & Bugs mentioned)
    at the bottom of the output file.
  - "Tracker summary" mode (-b) to output ONLY the wrapped summary, skipping the
    formatted text entirely.
  - Automatically detects and drops duplicate entries to keep lists clean.
  - Securely manages the Bugzilla API token using the system keyring.
"""

import argparse
import getpass
import re
import sys
import time
import requests
from pathlib import Path

try:
    import keyring
except ImportError:
    print("Error: The 'keyring' library is not installed.", file=sys.stderr)
    print("Please run: pip install keyring", file=sys.stderr)
    sys.exit(1)

KEYRING_SERVICE_NAME = "bugzilla-suse"
KEYRING_TOKEN_KEY = "bugzilla_api_key"

def get_bugzilla_credentials(cli_token=None):
    """Retrieve Bugzilla API token from CLI args, Keyring, or interactive prompt."""
    api_token = cli_token or keyring.get_password(KEYRING_SERVICE_NAME, KEYRING_TOKEN_KEY)

    if not api_token:
        print("SUSE Bugzilla API token not found in keyring.", file=sys.stderr)
        api_token = getpass.getpass("Enter your SUSE Bugzilla API token: ").strip()
        if api_token:
            keyring.set_password(KEYRING_SERVICE_NAME, KEYRING_TOKEN_KEY, api_token)
            print("API Token saved to system keyring for future use.", file=sys.stderr)
        else:
            print("Error: No API token provided. Exiting.", file=sys.stderr)
            sys.exit(1)

    return api_token

def is_valid_cve_page(cve_id: str) -> bool:
    """Checks if the SUSE CVE page actually exists using a fast streaming GET request."""
    url = f"https://www.suse.com/security/cve/{cve_id}.html"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, allow_redirects=True, timeout=5, stream=True)
        is_valid = response.status_code == 200
        response.close()
        return is_valid
    except requests.RequestException:
        return False

def wrap_and_write(items, outfile, max_len=67):
    """Helper to write a list of items wrapped at max_len characters with a bullet point."""
    if not items:
        return
    current_line = "- "
    for item in items:
        if current_line == "- ":
            current_line += item
        else:
            candidate = f"{current_line}, {item}"
            if len(candidate) > max_len:
                outfile.write(current_line + "\n")
                current_line = f"- {item}"
            else:
                current_line = candidate

    if current_line != "- ":
        outfile.write(current_line + "\n")

def process_cve_file(input_filepath: Path, output_filepath: Path, api_token: str = None, bugs_only: bool = False) -> tuple:
    cve_pattern = re.compile(r'(CVE-\d{4}-\d+)')
    bug_id_extractor = re.compile(r'(?i)(?:bsc|boo|bnc)#(\d+)')
    fate_extractor = re.compile(r'(?i)fate#(\d+)')

    trailing_bugs_pattern = re.compile(
        r'([ \t]*\(?[ \t]*(?:(?:https?://[^\[\s]+\[)?(?:bsc|boo|bnc)#\d+\]?[ \t,]*\)?)+)$',
        re.IGNORECASE
    )
    unformatted_bug_pattern = re.compile(r'(?<!\[)(?:bsc|boo|bnc)#(\d+)', re.IGNORECASE)
    unformatted_fate_pattern = re.compile(r'(?<!\[)fate#(\d+)', re.IGNORECASE)

    invalid_cves_report = []
    duplicates_report = []
    seen_processed_lines = set()  # Tracks processed lines to prevent duplicates

    # Collections for the summary block
    summary_cves = []
    summary_trackers = []

    headers = {
        "X-BUGZILLA-API-KEY": api_token,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    } if api_token else {}

    def has_tracker(text: str) -> bool:
        """Helper to check if a line has either a CVE, Bugzilla ID, or FATE ID."""
        return bool(cve_pattern.search(text) or bug_id_extractor.search(text) or fate_extractor.search(text))

    with open(input_filepath, 'r', encoding='utf-8') as infile, open(output_filepath, 'w', encoding='utf-8') as outfile:
        lines = infile.readlines()
        total_lines = len(lines)

        # Identify empty lines that interrupt lists
        skip_indices = set()
        for i, line in enumerate(lines):
            if not line.strip():
                prev_is_tracker = False
                for j in range(i - 1, -1, -1):
                    if lines[j].strip():
                        prev_is_tracker = has_tracker(lines[j])
                        break

                next_is_tracker = False
                for j in range(i + 1, total_lines):
                    if lines[j].strip():
                        next_is_tracker = has_tracker(lines[j])
                        break

                if prev_is_tracker and next_is_tracker:
                    skip_indices.add(i)

        # MAIN PROCESSING LOOP
        for i, line in enumerate(lines):
            if i in skip_indices:
                continue

            idx = i + 1
            clean_line = line.rstrip('\n')
            clean_line = clean_line.replace("http://", "https://")

            if not clean_line.strip():
                if not bugs_only:
                    outfile.write('\n')
                continue

            cve_match = cve_pattern.search(clean_line)
            bug_match = bug_id_extractor.search(clean_line)
            fate_match = fate_extractor.search(clean_line)

            # If the line has NEITHER a CVE, a Bug ID, nor a FATE ID write it as-is and continue
            if not cve_match and not bug_match and not fate_match:
                if not bugs_only:
                    outfile.write(clean_line + '\n')
                continue

            # Provide a clean, single-line progress update
            tracker_name = cve_match.group(1) if cve_match else (f"bug bsc#{bug_match.group(1)}" if bug_match else f"fate#{fate_match.group(1)}")
            print(f"[{idx}/{total_lines}] Processing {tracker_name}...")

            # Normalize Bullet Point First
            clean_line = re.sub(r'^\s*(?:[-*]\s*)?', '- ', clean_line)

            # Reverse Lookup (If we have a bug ID but NO CVE)
            if not cve_match and bug_match:
                bug_id = bug_match.group(1)
                api_url = f"https://bugzilla.suse.com/rest/bug/{bug_id}"
                try:
                    response = requests.get(api_url, headers=headers, timeout=10)
                    response.raise_for_status()
                    data = response.json()

                    if "bugs" in data and len(data["bugs"]) > 0:
                        bug_data = data["bugs"][0]
                        aliases = bug_data.get("alias", [])
                        found_cves = [a for a in aliases if cve_pattern.search(a)]

                        if not found_cves:
                            summary = bug_data.get("summary", "")
                            summary_match = cve_pattern.search(summary)
                            if summary_match:
                                found_cves.append(summary_match.group(1))

                        if found_cves:
                            injected_cve = found_cves[0]
                            print(f"  -> Reverse lookup found {injected_cve} for bug {bug_id}")

                            if clean_line.startswith('- '):
                                clean_line = clean_line.replace('- ', f'- {injected_cve}: ', 1)
                            else:
                                clean_line = f"{injected_cve}: {clean_line}"

                            cve_match = cve_pattern.search(clean_line)

                except requests.RequestException as e:
                    print(f"  -> Error querying Bugzilla for {bug_id}: {e}")

                time.sleep(0.5)

            # Format CVE URL
            if cve_match:
                cve_id = cve_match.group(1)
                cve_is_valid = is_valid_cve_page(cve_id)

                if cve_is_valid:
                    if "suse.com/security/cve" not in clean_line:
                        cve_url = f"https://www.suse.com/security/cve/{cve_id}.html[{cve_id}]"
                        clean_line = clean_line.replace(cve_id, cve_url, 1)
                else:
                    print(f"  -> Warning: SUSE page for {cve_id} is a 404.")
                    invalid_cves_report.append(f"Line {idx}: {cve_id}")

                    bad_link_pattern = rf"https://www\.suse\.com/security/cve/{cve_id}\.html\[{cve_id}\]"
                    clean_line = re.sub(bad_link_pattern, cve_id, clean_line)

            # Format FATE IDs
            if unformatted_fate_pattern.search(clean_line):
                clean_line = unformatted_fate_pattern.sub(
                    lambda m: f"https://fate.suse.com/{m.group(1)}[fate#{m.group(1)}]",
                    clean_line
                )
                print("  -> Formatted inline FATE references")

            # Format & Group Bugzilla IDs
            trailing_match = trailing_bugs_pattern.search(clean_line)

            if trailing_match:
                block_text = trailing_match.group(1)
                bug_ids = bug_id_extractor.findall(block_text)

                clean_line = clean_line[:trailing_match.start()]
                clean_line = clean_line.rstrip(' ,()')

                unique_bugs = list(dict.fromkeys(bug_ids))

                links = [f"https://bugzilla.suse.com/show_bug.cgi?id={b}[bsc#{b}]" for b in unique_bugs]
                bug_block = " (" + ", ".join(links) + ")"

                clean_line = f"{clean_line}{bug_block}"
                if len(unique_bugs) > 1:
                    print(f"  -> Grouped {len(unique_bugs)} bug reference(s) into a single block")

            else:
                if bug_id_extractor.search(clean_line):
                    clean_line = unformatted_bug_pattern.sub(
                        lambda m: f"https://bugzilla.suse.com/show_bug.cgi?id={m.group(1)}[bsc#{m.group(1)}]",
                        clean_line
                    )
                    print("  -> Formatted inline bug references")
                elif cve_match:
                    api_url = f"https://bugzilla.suse.com/rest/bug/{cve_id}"
                    try:
                        response = requests.get(api_url, headers=headers, timeout=10)
                        response.raise_for_status()
                        data = response.json()

                        if "bugs" in data and len(data["bugs"]) > 0:
                            bug_id = data["bugs"][0]["id"]
                            bsc_suffix = f"(https://bugzilla.suse.com/show_bug.cgi?id={bug_id}[bsc#{bug_id}])"
                            clean_line = f"{clean_line} {bsc_suffix}"
                        else:
                            print(f"  -> Warning: No Bugzilla entry found for {cve_id}")

                    except requests.RequestException as e:
                        print(f"  -> Error querying Bugzilla for {cve_id}: {e}")

                    time.sleep(0.5)

            # OUTPUT HANDLING
            # 1. Standard Mode Deduplication
            if clean_line in seen_processed_lines:
                print("  -> Duplicate detected, skipping.")
                primary_id = cve_match.group(1) if cve_match else (f"bsc#{bug_match.group(1)}" if bug_match else f"fate#{fate_match.group(1)}")
                duplicates_report.append(f"Line {idx}: {primary_id}")
                continue

            seen_processed_lines.add(clean_line)

            # 2. Extract for Summary (always)
            for cve in cve_pattern.findall(clean_line):
                if cve not in summary_cves:
                    summary_cves.append(cve)

            for bug in bug_id_extractor.findall(clean_line):
                b_str = f"bsc#{bug}"
                if b_str not in summary_trackers:
                    summary_trackers.append(b_str)

            for fate in fate_extractor.findall(clean_line):
                f_str = f"fate#{fate}"
                if f_str not in summary_trackers:
                    summary_trackers.append(f_str)

            # 3. Write standard formatted text if not in bugs-only mode
            if not bugs_only:
                outfile.write(clean_line + '\n')
                outfile.flush()

        # FINAL SUMMARY OUTPUT
        if summary_cves or summary_trackers:
            if not bugs_only:
                outfile.write("\n\n")

            if summary_cves:
                outfile.write("Security fixes:\n\n")
                wrap_and_write(summary_cves, outfile, max_len=67)
                outfile.write("\n")

            if summary_trackers:
                outfile.write("Bugs mentioned:\n\n")
                wrap_and_write(summary_trackers, outfile, max_len=67)
                outfile.write("\n")

    return invalid_cves_report, duplicates_report

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Bugzilla IDs for SUSE CVEs and reformat them for AsciiDoc release notes.")
    parser.add_argument("input_file", type=str, help="Path to the input text file containing CVEs")
    parser.add_argument("-o", "--output", type=str, help="Path to the output file (optional)", default=None)
    parser.add_argument("-t", "--token", type=str, help="Your SUSE Bugzilla API token (default: fetched from keyring)", default=None)
    parser.add_argument("-b", "--bugs-only", action="store_true", help="Extract and output ONLY the wrapped bug/CVE/FATE tracker summary, skipping the formatted text.")

    args = parser.parse_args()

    input_path = Path(args.input_file)

    if not input_path.is_file():
        print(f"Error: Could not find '{input_path}'. Please ensure the file exists.", file=sys.stderr)
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_name(f"{input_path.stem}_with_bsc{input_path.suffix}")

    api_token = get_bugzilla_credentials(args.token)

    print(f"\nReading from: {input_path}")
    print(f"Saving to:    {output_path}\n")

    invalid_cves, duplicates = process_cve_file(input_path, output_path, api_token, args.bugs_only)

    print(f"\nDone! Successfully processed file. Check '{output_path}'.")

    if invalid_cves:
        print("\n" + "="*60)
        print("REPORT: INVALID CVE URLs DETECTED (404)")
        print("="*60)
        print("The following CVEs do not have a valid SUSE CVE page:")
        for item in invalid_cves:
            print(f" - {item}")
        print("="*60)

    if duplicates:
        print("\n" + "="*60)
        print("REPORT: DUPLICATE ENTRIES REMOVED")
        print("="*60)
        print("The following lines were identical to earlier entries and were dropped:")
        for item in duplicates:
            print(f" - {item}")
        print("="*60)
