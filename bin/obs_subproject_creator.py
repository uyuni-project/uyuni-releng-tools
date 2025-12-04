#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2025 SUSE LLC and contributors
#
# SPDX-License-Identifier: Apache-2.0

"""
OBS Subproject Creator Utility

This script is an interactive command-line utility designed to streamline the creation of new
subprojects within the Open Build Service (OBS). It communicates with the OBS API endpoints
by leveraging the official **'osc' command** for all authenticated network operations.

* Secure and native authentication: Relies entirely on the system's 'osc' configuration.
* Intelligent Defaults: Suggests API URLs (e.g., api.opensuse.org) and template projects based on the target API endpoint.
* Input Validation: Strictly validates Project names, User IDs, and Group IDs against the API before proceeding.
* Template Merging: Supports cloning meta-data from a project template, allowing the user to selectively import Roles, Repositories, Release Targets, and Build Tags.
* Dynamic Repositories: Enables defining multi-path repositories and automatically discovers the available architecture list from the specified source repository/path.
* Consolidated Role Input: Streamlines the process of assigning multiple roles (Maintainer/Reviewer) to users or groups.
* Post-Creation Action: Offers to execute 'osc browse' to immediately open the newly created project in the web browser.
"""

import xml.etree.ElementTree as ET
import os
import sys
import subprocess
import shutil
import re

# Defaults for OBS setup
OSC_PATH = shutil.which("osc")

DEFAULT_API_URL = "https://api.opensuse.org"
DEFAULT_ARCHITECTURES = [
    'x86_64',
    'ppc64le',
    's390x',
    'aarch64'
]

TEMPLATE_MAP = {
    "https://api.opensuse.org": "systemsmanagement:Uyuni:Master",
    "https://api.suse.de": "Devel:Galaxy:Manager:Head"
}

# --- CORE OSC COMMAND(Python 3.6 Compatible) ---


def run_osc_command(args, input_data=None):
    """
    Helper to run generic osc commands via subprocess.
    Handles byte-stream piping to avoid temp files.
    """
    if not OSC_PATH:
        raise RuntimeError("❌ The 'osc' command is not available.")

    cmd = [OSC_PATH] + args

    # Prepare input bytes if data is provided
    input_bytes = None
    if input_data:
        input_bytes = input_data.encode('utf-8')

    try:
        # Use Popen with PIPE for all streams to ensure compatibility and control
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if input_bytes else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Communicate handles reading/writing and waiting for the process to end
        stdout_bytes, stderr_bytes = proc.communicate(input=input_bytes)

        # Decode output manually (replace errors to avoid crashes on binary garbage)
        stdout = stdout_bytes.decode('utf-8', errors='replace')
        stderr = stderr_bytes.decode('utf-8', errors='replace')

        return proc.returncode, stdout, stderr

    except OSError as e:
        print(f"❌ System Error executing osc: {e}")
        sys.exit(1)


def run_osc_api_get(api_url, endpoint):
    """
    Executes a GET request using 'osc api'.
    """
    # osc -A <url> api <endpoint> --method GET
    args = ["-A", api_url, "api", endpoint, "--method", "GET"]

    code, stdout, stderr = run_osc_command(args)

    if code != 0:
        # Check for common HTTP errors in stderr
        if "HTTP Error 404" in stderr:
            return "HTTP_ERROR:404"
        elif "HTTP Error 403" in stderr:
            return "HTTP_ERROR:403"
        elif "HTTP Error 401" in stderr:
            print(
                f"❌ AUTHENTICATION FAILED: Check your credentials in oscrc for {api_url}.")
            sys.exit(1)
        else:
            # Return None on generic failure so caller handles it
            return None

    return stdout


# --- API HELPER FUNCTIONS ---

def get_authenticated_username(api_url):
    """
    Uses 'osc api /person' to get the authenticated user's login.
    """
    endpoint = "/person"
    response_text = run_osc_api_get(api_url, endpoint)

    if not response_text or response_text.startswith("HTTP_ERROR"):
        print("⚠️ WARNING: Could not determine authenticated user. Defaulting to system username.")
        return os.environ.get('USER', 'user')

    try:
        root = ET.fromstring(response_text)
        return root.attrib.get('login', os.environ.get('USER', 'user'))
    except ET.ParseError:
        return os.environ.get('USER', 'user')


def check_project_exists(api_url, project_name):
    """Checks if an OBS project exists."""
    endpoint = f"/source/{project_name}/_meta"
    result = run_osc_api_get(api_url, endpoint)

    if result == "HTTP_ERROR:404":
        return False
    elif result == "HTTP_ERROR:403":
        # 403 means it exists but we can't see details. Treat as exists.
        return True
    elif result:
        return True
    return False


def check_entity_exists(api_url, name, entity_type):
    """
    Checks if a User or Group exists in OBS.
    entity_type should be 'User' or 'Group'.
    """
    if entity_type == 'User':
        endpoint = f"/person/{name}"
    elif entity_type == 'Group':
        endpoint = f"/group/{name}"
    else:
        return False

    result = run_osc_api_get(api_url, endpoint)

    if result == "HTTP_ERROR:404":
        return False
    elif result and not result.startswith("HTTP_ERROR"):
        return True
    return False


def fetch_project_meta(api_url, project_name):
    """Fetches the project meta XML for a given project."""
    endpoint = f"/source/{project_name}/_meta"
    result = run_osc_api_get(api_url, endpoint)

    if not result or result.startswith("HTTP_ERROR"):
        print(f"❌ Error fetching template metadata: {result}")
        return None

    print(" ℹ️ Successfully retrieved template metadata.")
    return result


def fetch_source_architectures(api_url, project_name, repo_name):
    """
    Fetches the metadata for a given project and extracts the architectures.
    """
    endpoint = f"/source/{project_name}/_meta"
    response_text = run_osc_api_get(api_url, endpoint)

    if not response_text or response_text.startswith("HTTP_ERROR"):
        return None

    try:
        root = ET.fromstring(response_text)
        repo_elem = root.find(f"repository[@name='{repo_name}']")
        if repo_elem is None:
            return None

        architectures = [arch.text.strip()
                         for arch in repo_elem.findall('arch') if arch.text]
        return sorted(architectures)

    except ET.ParseError:
        return None


def get_template_architectures(template_meta_xml):
    """Extracts all unique architectures from repository elements in the template meta."""
    if not template_meta_xml:
        return []

    try:
        root = ET.fromstring(template_meta_xml)
        architectures = set()

        for repo in root.findall('repository'):
            for arch in repo.findall('arch'):
                if arch.text:
                    architectures.add(arch.text.strip())

        return sorted(list(architectures))
    except ET.ParseError:
        print("⚠️ WARNING: Failed to parse template XML for architectures.")
        return []


# --- USER INPUT HELPERS ---

def sanitize_repo_name(name):
    # Only replace the restricted URL/Path separators
    sanitized_name = name.replace(':', '_').replace('/', '_')
    return sanitized_name


def get_role_assignments(api_url, entity_type):
    """
    Prompts the user for a list of Users or Groups, validates their existence,
    and determines their roles.
    """
    entity_roles = []
    print(f"\n❓ Configure {entity_type} Roles (Enter blank line to finish) ")
    while True:
        entity_id = input(
            f" ❓ Enter {entity_type} ID (or blank to finish): ").strip()
        if not entity_id:
            break

        # Validate existence
        print(f"  ℹ️ Checking existence of {entity_type} '{entity_id}'...")
        if not check_entity_exists(api_url, entity_id, entity_type):
            print(
                f"  ❌ ERROR: {entity_type} '{entity_id}' not found on {api_url}. Please check the name.")
            if input("  ❓ Proceed anyway (risks failure)? (y/N): ").strip().lower() != 'y':
                continue

        print(f"  ❓ Configuring roles for **{entity_id}**:")

        is_maintainer = input(
            "  ❓ Assign Maintainer role? (y/N): ").strip().lower() == 'y'
        is_reviewer = input(
            "  ❓ Assign Reviewer role? (y/N): ").strip().lower() == 'y'

        if is_maintainer or is_reviewer:
            entity_roles.append({
                'id': entity_id,
                'maintainer': is_maintainer,
                'reviewer': is_reviewer
            })
        else:
            print(f"  ℹ️ {entity_id} skipped as no role was assigned.")

    return entity_roles


def get_repository_details(repo_input_name, api_url, custom_repo_arches):
    """
    Gathers detailed configuration for a single repository, supporting multiple path
    definitions and dynamic architecture merging.
    """
    repo_name = sanitize_repo_name(repo_input_name)
    if repo_name != repo_input_name:
        print(
            f"  ℹ️ Repository name sanitized: '{repo_input_name}' changed to '{repo_name}'")

    print(f"\nConfiguring repository: **{repo_name}**")

    paths = []
    current_architectures = custom_repo_arches

    path_count = 0
    while True:
        path_count += 1
        print(f"\n ℹ️ Paths Definition for '{repo_name}'")

        # PATH PROJECT VALIDATION
        path_project_default = paths[-1]['project'] if paths else repo_input_name

        while True:
            path_project_prompt = f" ❓ Enter Path Project {path_count} (Default: {path_project_default}): "
            path_project = input(
                path_project_prompt).strip() or path_project_default

            # Allow user to quit path definition if it's not the first path
            if path_count > 1 and not path_project:
                path_count -= 1
                print("  ℹ️ Finished adding paths for this repository. ---")
                return {
                    "repo_name": sanitize_repo_name(paths[0]['project']) if paths else repo_name,
                    "paths": paths,
                    "architectures": current_architectures
                }

            print(
                f" ℹ️ Checking existence of source project: {path_project}...")
            project_exists = check_project_exists(api_url, path_project)

            if project_exists:
                print("  ✅ Source project found.")
                break
            else:
                print(
                    f"  ⚠️ WARNING: Project '{path_project}' does NOT exist (or access denied).")
                if input(" ❓ Do you want to proceed anyway? (y/N): ").strip().lower() != 'y':
                    pass  # loop again
                else:
                    break  # user override

            path_project_default = path_project

        # PATH REPOSITORY INPUT
        path_repository_default = paths[-1]['repository'] if paths else "standard"
        path_repository = input(f" ❓ Enter Path Repository {path_count} (Default: {path_repository_default}): ").strip(
        ) or path_repository_default

        paths.append({
            "project": path_project,
            "repository": path_repository
        })

        # DYNAMIC ARCHITECTURE CHECK
        source_arches = fetch_source_architectures(
            api_url, path_project, path_repository)

        if source_arches and set(source_arches) != set(current_architectures):
            print(
                f"\n ✨ Found DIFFERENT architectures in the new path ({path_project}/{path_repository}):")
            print(f"  ℹ️ Current Set: {', '.join(current_architectures)}")
            print(f"  ℹ️ New Set: {', '.join(source_arches)}")

            if input(" ❓ Do you want to REPLACE the current architecture set with the new set? (y/N): ").strip().lower() == 'y':
                current_architectures = source_arches
                print("  ℹ️ Architecture set updated.")
            else:
                print("  ℹ️ Keeping previous architecture set.")

        elif source_arches:
            if path_count == 1:
                current_architectures = source_arches
                print(
                    f"  ℹ️ Using architectures found in the source project: {', '.join(current_architectures)}")
        else:
            print(
                " ⚠️ Could not dynamically fetch architectures; using the current default set.")

        # Update repo name based on the first path added
        if path_count == 1:
            final_repo_name = sanitize_repo_name(path_project)
        else:
            final_repo_name = sanitize_repo_name(paths[0]['project'])

        path_project_default = path_project

        if input(" ❓ Add another path definition for this repository? (y/N): ").strip().lower() != 'y':
            break

    return {
        "repo_name": final_repo_name,
        "paths": paths,
        "architectures": current_architectures
    }


# --- XML CONSTRUCTION ---

def _add_role_element(parent, element_tag, id_attr, id_value, role):
    if element_tag == "person":
        attrs = {"userid": id_value, "role": role}
    elif element_tag == "group":
        attrs = {"groupid": id_value, "role": role}
    else:
        return
    ET.SubElement(parent, element_tag, **attrs)


def create_project_meta_xml(new_project_name, title, description,
                            maintainer_users, maintainer_groups,
                            reviewer_users, reviewer_groups,
                            repositories_config, template_meta_xml=None,
                            include_template_repos=False,
                            include_template_roles=False,
                            include_template_targets=False,
                            include_template_build_tags=False):
    """Constructs the final <project> XML."""
    if template_meta_xml:
        root = ET.fromstring(template_meta_xml)
        if 'name' in root.attrib:
            del root.attrib['name']

        elements_to_remove = []
        for child in root:
            if child.tag in ('person', 'group') and not include_template_roles:
                elements_to_remove.append(child)
            elif child.tag == 'repository' and not include_template_repos:
                elements_to_remove.append(child)
            elif child.tag == 'releasetarget' and not include_template_targets:
                elements_to_remove.append(child)
            elif child.tag == 'build' and not include_template_build_tags:
                elements_to_remove.append(child)
        for child in elements_to_remove:
            root.remove(child)

        if not include_template_targets:
            for repo_elem in root.findall('repository'):
                releasetargets_to_remove = [
                    t for t in repo_elem.findall('releasetarget')]
                for target_elem in releasetargets_to_remove:
                    repo_elem.remove(target_elem)
    else:
        root = ET.Element("project")

    root.set("name", new_project_name)

    def update_tag(parent, tag_name, text_content):
        tag = parent.find(tag_name)
        if tag is None:
            tag = ET.SubElement(parent, tag_name)
        tag.text = text_content

    update_tag(root, "title", title)
    update_tag(root, "description", description)

    for user_id in maintainer_users:
        _add_role_element(root, "person", "userid", user_id, "maintainer")
    for group_id in maintainer_groups:
        _add_role_element(root, "group", "groupid", group_id, "maintainer")
    for user_id in reviewer_users:
        _add_role_element(root, "person", "userid", user_id, "reviewer")
    for group_id in reviewer_groups:
        _add_role_element(root, "group", "groupid", group_id, "reviewer")

    for repo_data in repositories_config:
        repo_elem = ET.SubElement(
            root, "repository", name=repo_data['repo_name'])
        for path_data in repo_data['paths']:
            ET.SubElement(
                repo_elem, "path", project=path_data['project'], repository=path_data['repository'])
        for arch in repo_data['architectures']:
            arch_elem = ET.SubElement(repo_elem, "arch")
            arch_elem.text = arch

    xml_string = ET.tostring(root, encoding='utf-8').decode()
    return f'<?xml version="1.0"?>\n{xml_string}'


def create_subproject_with_meta_cmd(api_url, full_project_name, xml_payload):
    """
    Uses 'osc meta prj ... -F -' to create/update the project.
    The '-F -' flag tells osc to read the config from STDIN.
    """
    print(f"\nℹ️ Attempting to create project: {full_project_name} ---")

    # osc -A <url> meta prj <project> -F -
    args = ["-A", api_url, "meta", "prj", full_project_name, "-F", "-"]

    code, stdout, stderr = run_osc_command(args, input_data=xml_payload)

    if code == 0:
        print(
            f"\n✅ SUCCESS! Project '{full_project_name}' created/updated successfully.")

        if input(f"❓ Do you want to open project '{full_project_name}' using 'osc browse'? (y/N): ").strip().lower() == 'y':
            try:
                subprocess.Popen(
                    [OSC_PATH, "-A", api_url, "browse", full_project_name])
            except OSError as e:
                print(f" ❌ Could not execute 'osc browse'. Error: {e}")
    else:
        print(f"\n❌ Failed to create project. Exit Code: {code}")
        print(f"Error Output:\n{stderr}")
        sys.exit(1)


# --- Main Execution ---

def main():
    if not OSC_PATH:
        print("❌ ERROR: 'osc' command not found.")
        sys.exit(1)

    print("OBS Project Creation Script")
    print("--------------------------------------------------")

    target_api_input = input(
        f"❓ Enter the Target OBS API URL (Default: {DEFAULT_API_URL}): ").strip()
    api_url = target_api_input if target_api_input else DEFAULT_API_URL
    api_url = api_url.rstrip('/')

    username_guess = get_authenticated_username(api_url)
    print(f" ℹ️ Authenticated OBS User: {username_guess}")
    print(" ℹ️ NOTE: All API communication is handled by the 'osc' client.")
    print("--------------------------------------------------")

    while True:
        parent_project = input(
            f"❓ Enter the Parent Project (e.g., 'home:{username_guess}'): ").strip()
        if not parent_project:
            print("❌ Parent Project cannot be empty.")
            continue

        print(f" ℹ️ Checking existence of Parent Project: {parent_project}...")
        project_exists = check_project_exists(api_url, parent_project)
        if project_exists:
            print(" ✅ Parent Project found.")
            break
        else:
            print(
                f"❌ ERROR: Parent Project '{parent_project}' does NOT exist. Please enter a valid project.")

    # --- SUBPROJECT NAME VALIDATION (STRICT WHITELIST) ---
    while True:
        subproject_name = input(
            "❓ Enter the New Subproject Name (e.g., 'my_library'): ").strip()

        if not subproject_name:
            print("❌ Subproject name cannot be empty.")
            continue

        # Allowed: alphanumeric, dot, underscore, dash
        if not re.match(r'^[a-zA-Z0-9._-]+$', subproject_name):
            print("❌ Invalid name. Only alphanumeric characters, dots (.), dashes (-), and underscores (_) are allowed.")
            print(
                "   Colons (:) and slashes (/) are strictly forbidden in a subproject name.")
            continue

        break

    full_project_name = f"{parent_project}:{subproject_name}"
    title = input(" ❓ Enter the Project Title: ").strip()
    description = input(" ❓ Enter the Project Description: ").strip()

    template_default = TEMPLATE_MAP.get(api_url, "")
    template_input = input(
        f"\n❓ Optional Template Project: Enter a name, or leave blank to skip. (Suggested: {template_default}): ").strip()

    if not template_input:
        template_project = ''
        print(" ℹ️ Skipping template import.")
    else:
        template_project = template_input

    include_template_roles = False
    include_template_repos = False
    include_template_targets = False
    include_template_build_tags = False
    template_arches = []
    template_meta_xml = None

    if template_project:
        template_meta_xml = fetch_project_meta(api_url, template_project)
        if template_meta_xml:
            template_arches = get_template_architectures(template_meta_xml)
        else:
            template_arches = DEFAULT_ARCHITECTURES

        print(f"\n ℹ️ Template Content Import for '{template_project}'")
        if input("  ❓ Do you want to IMPORT default maintainers/reviewers? (y/N): ").strip().lower() == 'y':
            include_template_roles = True

        if input("  ❓ Do you want to IMPORT repositories? (y/N): ").strip().lower() == 'y':
            include_template_repos = True
            if input("    ❓ Do you want to IMPORT release targets for the imported repositories? (y/N): ").strip().lower() == 'y':
                include_template_targets = True
            if input("    ❓ Do you want to IMPORT build settings for the imported repositories? (y/N): ").strip().lower() == 'y':
                include_template_build_tags = True
        else:
            print("  ℹ️ Skipping dependent template items (repos, targets, build tags).")
            template_arches = DEFAULT_ARCHITECTURES
    else:
        template_arches = DEFAULT_ARCHITECTURES

    custom_repo_arches = template_arches if template_arches else DEFAULT_ARCHITECTURES

    # Gather Roles (Using new validation)
    group_assignments = get_role_assignments(api_url, "Group")
    user_assignments = get_role_assignments(api_url, "User")

    maintainer_users, reviewer_users = [], []
    maintainer_groups, reviewer_groups = [], []

    for item in group_assignments:
        if item['maintainer']:
            maintainer_groups.append(item['id'])
        if item['reviewer']:
            reviewer_groups.append(item['id'])
    for item in user_assignments:
        if item['maintainer']:
            maintainer_users.append(item['id'])
        if item['reviewer']:
            reviewer_users.append(item['id'])

    # Gather Repositories
    repositories_config = []
    print("\nℹ️ Configure Custom Repositories")
    while True:
        repo_input_name = input(
            f"\n❓ Enter custom Repository to add (e.g., 'SUSE:SLE-15-SP7:Update' or blank to finish): ").strip()
        if not repo_input_name:
            break
        repo_data = get_repository_details(
            repo_input_name, api_url, custom_repo_arches)
        repositories_config.append(repo_data)

    # Build XML
    project_xml_payload = create_project_meta_xml(
        full_project_name, title, description,
        maintainer_users, maintainer_groups, reviewer_users, reviewer_groups,
        repositories_config, template_meta_xml,
        include_template_repos, include_template_roles,
        include_template_targets, include_template_build_tags
    )

    print("\n ℹ️ Generated Project XML Payload")
    if len(project_xml_payload) > 1500:
        print(project_xml_payload[:1500] +
              "...\n(  ℹ️ Payload truncated for display)")
    else:
        print(project_xml_payload)
    print("-------------------------------------")

    # Execute Creation
    create_subproject_with_meta_cmd(
        api_url, full_project_name, project_xml_payload)


if __name__ == "__main__":
    main()
