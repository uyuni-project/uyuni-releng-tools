#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2025 SUSE LLC and contributors
#
# SPDX-License-Identifier: Apache-2.0

"""
Automate maintenance and protection for special OBS subprojects (e.g., snapshots).

Declines open delete requests, assigns group maintainer/reviewer roles,
configures the OBS:RejectRequests attribute, and safely handles project locks.
"""

import xml.etree.ElementTree as ET
import urllib.parse
import subprocess
import argparse
import datetime
import logging
import shutil
import sys

OSC_PATH = shutil.which("osc")

if not OSC_PATH:
    print("❌ The 'osc' command is not available.")
    sys.exit(1)

def setup_logger(log_file):
    """Configures dual logging to both console and a file."""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.INFO)
    fh_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    fh.setFormatter(fh_format)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch_format = logging.Formatter('%(message)s')
    ch.setFormatter(ch_format)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger

def run_osc_command(args_list, logger, input_data=None):
    """Helper to run generic osc commands via subprocess."""
    cmd = [OSC_PATH] + args_list
    input_bytes = input_data.encode('utf-8') if input_data else None

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if input_bytes else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout_bytes, stderr_bytes = proc.communicate(input=input_bytes)
        stdout = stdout_bytes.decode('utf-8', errors='replace')
        stderr = stderr_bytes.decode('utf-8', errors='replace')
        return proc.returncode, stdout, stderr
    except OSError as e:
        logger.error(f"❌ System Error executing osc: {e}")
        sys.exit(1)

def get_subprojects(args, logger):
    """Fetches subprojects via API search and parses the XML response."""
    logger.info(f"🔍 Searching for subprojects under '{args.base_project}' on '{args.apiurl}'...")

    query = f"/search/project?match=starts_with(@name,'{args.base_project}')"
    code, stdout, stderr = run_osc_command(["-A", args.apiurl, "api", query], logger)

    if code != 0:
        logger.error(f"❌ Error fetching projects: {stderr}")
        return []

    projects = []
    root = ET.fromstring(stdout)
    for prj in root.findall('project'):
        projects.append(prj.attrib['name'])
    return projects

def process_project(prj, args, logger):
    """Processes a single project and returns a status dictionary."""
    logger.info("\n========================================")
    logger.info(f" Processing project: {prj}")
    logger.info("========================================")

    # ---------------------------------------------------------
    # Check Lock State and Build Safety
    logger.info(" ℹ️ Checking project state (locked / build disabled)...")

    meta_api_url = f"/source/{prj}/_meta"
    code, meta_xml, err = run_osc_command(["-A", args.apiurl, "api", meta_api_url], logger)

    build_disabled = False
    is_locked = False

    if code == 0:
        try:
            meta_root = ET.fromstring(meta_xml)
            build_node = meta_root.find('build')
            if build_node is not None and build_node.find('disable') is not None:
                build_disabled = True

            if meta_root.find('lock') is not None:
                is_locked = True
        except ET.ParseError:
            pass

    # Fallback lock check: Look at the directory root element
    dir_code, dir_xml, _ = run_osc_command(["-A", args.apiurl, "api", f"/source/{prj}"], logger)
    if dir_code == 0:
        try:
            dir_root = ET.fromstring(dir_xml)
            if dir_root.attrib.get('lock') == '1':
                is_locked = True
        except ET.ParseError:
            pass

    was_locked = is_locked
    if is_locked:
        if not args.unlock:
            logger.warning("   ⚠️ Project is locked. Skipping. (Use --unlock flag to process)")
            return {'declined': [], 'status': 'skipped_locked'}

        if not build_disabled:
            logger.warning("   ⚠️ Project is locked and NOT build-disabled. Unsafe to unlock. Skipping.")
            return {'declined': [], 'status': 'skipped_unsafe'}

        logger.info("   🔓 Project is locked but build is disabled. Unlocking for processing...")
        encoded_unlock_msg = urllib.parse.quote(args.unlock_msg)
        unlock_url = f"/source/{prj}?cmd=unlock&comment={encoded_unlock_msg}"
        code, out, err = run_osc_command(["-A", args.apiurl, "api", "-X", "POST", unlock_url], logger)
        if code != 0:
            logger.error(f"   ❌ Failed to unlock project: {err}")
            return {'declined': [], 'status': 'failed_unlock'}

    declined_requests = []

    # ---------------------------------------------------------
    # Review open requests of type delete_request via API
    logger.info(" ℹ️ Finding open delete requests...")

    xpath = f"action/target/@project='{prj}' and action/@type='delete' and (state/@name='new' or state/@name='review')"
    encoded_xpath = urllib.parse.quote(xpath)
    search_api_url = f"/search/request?match={encoded_xpath}"

    code, stdout, stderr = run_osc_command(["-A", args.apiurl, "api", search_api_url], logger)

    if code == 0:
        root = ET.fromstring(stdout)
        req_ids = [req.attrib['id'] for req in root.findall('request')]

        if not req_ids:
            logger.info("   -> No open delete requests found.")
        else:
            # ---------------------------------------------------------
            # Decline the delete request via native osc command
            for req_id in req_ids:
                logger.info(f"   -> Declining delete request ID: {req_id}")

                code, out, err = run_osc_command([
                    "-A", args.apiurl, "request", "decline", "-m", args.decline_msg, req_id
                ], logger)

                if code == 0:
                    logger.info("   -> Request declined successfully.")
                    declined_requests.append(req_id)
                else:
                    logger.error(f"   ❌ Failed to decline request: {err}")
    else:
        logger.error(f"   ❌ Failed to search requests: {stderr}")

    # ---------------------------------------------------------
    # Set the maintainers group via API Meta update
    logger.info(f" ℹ️ Updating maintainer and reviewer roles for group '{args.group}'...")

    code, meta_xml, _ = run_osc_command(["-A", args.apiurl, "api", meta_api_url], logger)

    if code == 0:
        root = ET.fromstring(meta_xml)
        modified = False

        for role in ["maintainer", "reviewer"]:
            exists = root.findall(f"./group[@groupid='{args.group}'][@role='{role}']")
            if not exists:
                ET.SubElement(root, "group", groupid=args.group, role=role)
                modified = True

        if modified:
            new_xml = ET.tostring(root, encoding='utf-8').decode()
            code, out, err = run_osc_command(["-A", args.apiurl, "api", "-X", "PUT", "-d", new_xml, meta_api_url], logger)

            if code == 0:
                logger.info("   -> Roles updated successfully.")
            else:
                logger.error(f"   ❌ Failed to update roles: {err}")
        else:
            logger.info("   -> Roles already present.")

    # ---------------------------------------------------------
    # Set OBS:RejectRequests attribute via native osc command
    logger.info(" ℹ️ Setting OBS:RejectRequests attribute (text, delete, submit)...")

    code, out, err = run_osc_command([
        "-A", args.apiurl, "meta", "attribute", prj, "--attribute", "OBS:RejectRequests", "--set", args.reject_text
    ], logger)

    if code == 0:
        code, out, err = run_osc_command([
            "-A", args.apiurl, "meta", "attribute", prj, "--attribute", "OBS:RejectRequests", "--add", "delete"
        ], logger)

    if code == 0:
        code, out, err = run_osc_command([
            "-A", args.apiurl, "meta", "attribute", prj, "--attribute", "OBS:RejectRequests", "--add", "submit"
        ], logger)

    if code == 0:
        logger.info("   -> Attribute applied successfully.")
    else:
        logger.error(f"   ❌ Failed to set attribute: {err}")

    # ---------------------------------------------------------
    # Lock Project Handling
    should_lock = was_locked or args.lock

    if should_lock:
        if args.lock and not was_locked and not build_disabled:
            logger.warning("   ⚠️ Requested --lock, but project does not have build disabled. Skipping lock.")
        else:
            reason = "Restoring lock" if was_locked else "Applying requested lock (--lock)"
            logger.info(f"   🔒 {reason} on project...")
            encoded_lock_msg = urllib.parse.quote(args.lock_msg)
            lock_url = f"/source/{prj}?cmd=lock&comment={encoded_lock_msg}"
            code, out, err = run_osc_command(["-A", args.apiurl, "api", "-X", "POST", lock_url], logger)
            if code != 0:
                logger.error(f"   ❌ Failed to lock project: {err}")

    return {'declined': declined_requests, 'status': 'processed'}

def main():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    default_log_file = f"obs_setup_special_projects_{timestamp}.log"

    parser = argparse.ArgumentParser(description="Automate OBS project cleanup: declines delete requests, assigns group roles, and sets RejectRequests attributes.")

    parser.add_argument("-A", "--apiurl",
                        default="https://api.opensuse.org",
                        help="OBS API URL (default: https://api.opensuse.org)")

    parser.add_argument("-p", "--base-project",
                        default="systemsmanagement:Uyuni:Snapshots:",
                        help="Base project name to search for subprojects (default: systemsmanagement:Uyuni:Snapshots:)")

    parser.add_argument("-g", "--group",
                        default="uyuni-maintainers",
                        help="Group ID to add as maintainer and reviewer (default: uyuni-maintainers)")

    parser.add_argument("--decline-msg",
                        default="Automated decline: Rejecting delete requests for snapshot projects.",
                        help="Message to use when declining delete requests")

    parser.add_argument("--reject-text",
                        default="Requests are automatically rejected for Snapshot projects. Please contact the uyuni-maintainers team.",
                        help="Text for the OBS:RejectRequests attribute")

    parser.add_argument("--log-file",
                        default=default_log_file,
                        help=f"Path to the log file (default: {default_log_file})")

    parser.add_argument("--unlock",
                        action="store_true",
                        help="Attempt to safely unlock and process locked projects (only if build is disabled)")

    parser.add_argument("--lock",
                        action="store_true",
                        help="Lock the project after all operations are complete (only if build is disabled)")

    parser.add_argument("--lock-msg",
                        default="Automated lock: Project locked by maintenance automation.",
                        help="Comment passed when locking a project")

    parser.add_argument("--unlock-msg",
                        default="Automated unlock: Temporary unlock for maintenance updates.",
                        help="Comment passed when unlocking a project")

    args = parser.parse_args()
    logger = setup_logger(args.log_file)

    projects = get_subprojects(args, logger)

    if not projects:
        logger.warning("No projects found.")
        return

    overview_declined = {}
    skipped_locked = []
    skipped_unsafe = []

    for prj in projects:
        res = process_project(prj, args, logger)

        if res['status'] == 'skipped_locked':
            skipped_locked.append(prj)
        elif res['status'] == 'skipped_unsafe':
            skipped_unsafe.append(prj)

        if res.get('declined'):
            overview_declined[prj] = res['declined']

    # ---------------------------------------------------------
    # Final Overview Section
    logger.info("\n" + "="*40)
    logger.info(" FINAL OVERVIEW")
    logger.info("="*40)

    if skipped_locked:
        logger.info("\n ⚠️ Skipped (Locked, run with --unlock to process):")
        for p in skipped_locked:
            logger.info(f"    - {p}")

    if skipped_unsafe:
        logger.info("\n ⚠️ Skipped (Locked but unsafe to unlock - build NOT disabled):")
        for p in skipped_unsafe:
            logger.info(f"    - {p}")

    if not overview_declined:
        logger.info("\n ℹ️ No delete requests were declined during this run.")
    else:
        logger.info("\n ℹ️ The following delete requests were declined:")
        total_declined = 0
        for prj, reqs in overview_declined.items():
            logger.info(f"    - {prj}: {', '.join(reqs)}")
            total_declined += len(reqs)
        logger.info(f"\n Total requests declined: {total_declined}")

    logger.info(f"\n  Detailed execution log saved to: {args.log_file}")

if __name__ == "__main__":
    main()
