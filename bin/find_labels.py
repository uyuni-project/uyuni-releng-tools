#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 SUSE LLC and contributors
#
# SPDX-License-Identifier: Apache-2.0

"""
OBS Package Label Finder

This script searches an Open Build Service (OBS) project to find all packages
that have a specific label assigned to them.

Because OBS does not natively expose package labels to the XPath search API,
this script works around the limitation in three steps:
  1. It checks the project's _meta configuration. If the project is directly
     managed via scmsync (Git workflow), it exits early. OBS currently
     has a known backend bug where SCM virtual packages do not exist in the
     database, meaning label lookups will fail. (This can be bypassed with --force).
  2. It uses osc ls to reliably fetch the list of packages in the project.
  3. It iterates through the packages, querying the /labels API endpoint for each,
     and parses the XML response to check for the target label.

Prerequisites:
  - The osc command-line client must be installed.
  - You must have valid OBS credentials configured (usually in ~/.config/osc/oscrc).
"""

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Search an OBS project for packages matching a specific label. "
            "Since OBS does not support native label search, this script discovers "
            "packages using 'osc ls' and checks their labels individually via the API. "
            "Note: Projects fully managed by scmsync (Git workflow) are skipped by default "
            "due to an OBS backend limitation."
        )
    )

    parser.add_argument("-p", "--project", required=True, help="Project name (e.g., systemsmanagement:Uyuni:Utils)")
    parser.add_argument("-l", "--label", required=True, help="Label name to search for (e.g., deleteme)")
    parser.add_argument("-a", "--api-url", default="https://api.opensuse.org", help="OBS API URL (default: https://api.opensuse.org)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print debug information")
    parser.add_argument("-f", "--force", action="store_true", help="Force label checking even on scmsync projects")

    args = parser.parse_args()

    print(f"Searching for packages with label '{args.label}' in {args.project}...\n")

    # Check if the project itself is scmsync managed
    meta_cmd = ["osc", "api", "-A", args.api_url, f"/source/{args.project}/_meta"]

    if args.verbose:
        print(f"[DEBUG] Running: {' '.join(meta_cmd)}")

    meta_result = subprocess.run(
        meta_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
    )

    if meta_result.returncode != 0:
        print(f"Error fetching project metadata: {meta_result.stderr}", file=sys.stderr)
        sys.exit(1)

    try:
        meta_root = ET.fromstring(meta_result.stdout)
        # If <scmsync> exists in the project meta, handle the known OBS bug
        if meta_root.find('scmsync') is not None:
            print(f"Notice: Project '{args.project}' is directly scmsync managed.")
            if not args.force:
                print("Skipping label checks because OBS currently has a known bug where SCM virtual packages")
                print("do not fully exist in the database, meaning labels won't resolve.")
                print("Use --force to bypass this check and search anyway.")
                sys.exit(0)
            else:
                print("Warning: --force provided. Proceeding with label checks despite scmsync.\n")
    except ET.ParseError as e:
        print(f"Error parsing project metadata XML: {e}", file=sys.stderr)
        # We don't exit here, just in case there's a weird XML quirk, we can still try to run the rest

    # Fetch package list using 'osc ls'
    ls_cmd = ["osc", "-A", args.api_url, "ls", args.project]

    if args.verbose:
        print(f"[DEBUG] Running: {' '.join(ls_cmd)}")

    ls_result = subprocess.run(
        ls_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
    )

    if ls_result.returncode != 0:
        print(f"Error fetching packages: {ls_result.stderr}", file=sys.stderr)
        sys.exit(1)

    # 'osc ls' returns plain text, one package name per line. No XML parsing needed!
    packages = [line.strip() for line in ls_result.stdout.strip().split('\n') if line.strip()]

    if args.verbose:
        print(f"[DEBUG] Parsed {len(packages)} packages from osc ls.")

    if not packages:
        print(f"No packages found in project {args.project}!")
        sys.exit(0)

    # Iterate and check labels via API
    for pkg in packages:
        if args.verbose:
            print(f"[DEBUG] Checking labels for package: {pkg}")

        labels_cmd = ["osc", "api", "-A", args.api_url, f"/labels/projects/{args.project}/packages/{pkg}"]
        labels_result = subprocess.run(
            labels_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
        )

        if labels_result.returncode != 0:
            continue

        try:
            labels_root = ET.fromstring(labels_result.stdout)
            for label in labels_root.findall('label'):
                template_name = label.find('label_template_name')
                if template_name is not None and template_name.text == args.label:
                    print(f"Found: {pkg}")
                    break
        except ET.ParseError:
            continue

if __name__ == "__main__":
    main()
