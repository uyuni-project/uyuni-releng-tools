<!--
SPDX-FileCopyrightText: 2025 SUSE LLC

SPDX-License-Identifier: Apache-2.0
-->

[![REUSE status](https://api.reuse.software/badge/git.fsfe.org/reuse/api)](https://api.reuse.software/info/git.fsfe.org/reuse/api)

These are tools used to help Uyuni release engineers package and submit the various projects.
These used to be in the `uyuni` repository and have been extracted to be used for other repositories.

# Dependencies

* `tito` from [systemsmanagement:Uyuni:Utils](https://build.opensuse.org/project/show/systemsmanagement:Uyuni:Utils)

# Existing tools

## mkchlog

This tool creates a changelog entry that can be later on tagged with tito.

~~~
Usage: mkchlog [OPTIONS] [MESSAGE]

When called from a subdirectory of any Uyuni package, create a changelog file in
the following format:

    <package_name>.changes.<username>.<feature_name>

If not explicitly specified, fetch username and feature_name from git email's
username part and the current branch name.

With no MESSAGE, open a text editor for manual input.
The default editor can be specified by setting the EDITOR environment variable.

  -f, --feature         set the feature name to use as a filename part
  -u, --username        set the username to use as a filename part
  -r, --remove          remove existing changelog file
  -c, --commit          do a git commit with MESSAGE as the commit message
  -n, --no-wrap         do not wrap automatically the message at 67 characters
  -h, --help            display this help and exit
~~~

## build-packages-for-obs and push-packages-to-obs

The script `build-packages-for-obs` is used together with `push-packages-to-obs` for building a source from git and pushing it to a project on the Open Build Service and build it there.

A comprehensive how-to is available at the following wiki page [Building-an-RPM-in-an-OBS-branch-package](https://github.com/uyuni-project/uyuni/wiki/Building-an-RPM-in-an-OBS-branch-package)


## push-images-to-git and push-packages-to-git

These scripts push package or image sources prepared with `build-packages-for-obs` into git (src.opensuse.org or src.suse.de) which act as source storage for the Open Build Service.


## push-to-obs.sh

The script `push-to-obs.sh` run a container to push SUSE Multi-Linux Manager/Uyuni packages to IBS/OBS and git.

Internally it uses build-packages-for-obs, push-packages-to-obs, push-images-to-git and push-packages-to-git to perform the final tasks.


## check-obs-project-status

The script `check-obs-project-status` is used to verify that all packages, products, containers and images are successfully building in the given projects.
By default it check Uyuni repositories in build.opensuse.org

The following environment variables can be set to configure the behavior:
~~~
OSCAPI       (Default: https://api.opensuse.org)
OSCCNF       (Default: $HOME/.oscrc)
OBS_PRJS_URL (Default: https://build.opensuse.org/project/show)
OBS_PROJS    The projects to check. Seperated by space.
             (Default: systemsmanagement:Uyuni:Master systemsmanagement:Uyuni:Master:Other ...)
~~~

## obs_subproject_creator.py

The script  `obs_subproject_creator.py` is used for generating an OBS/IBS subproject.

This script is an interactive command-line utility designed to streamline the creation of new
subprojects within the Open Build Service (OBS). It communicates with the OBS API endpoints
by leveraging the official **'osc' command** for all authenticated network operations.

Key Features:

* Secure and native authentication: Relies entirely on the system's 'osc' configuration.
* Intelligent Defaults: Suggests API URLs (e.g., api.opensuse.org) and template projects based on the target API endpoint.
* Input Validation: Strictly validates Project names, User IDs, and Group IDs against the API before proceeding.
* Template Merging: Supports cloning meta-data from a project template, allowing the user to selectively import Roles, Repositories, Release Targets, and Build Tags.
* Dynamic Repositories: Enables defining multi-path repositories and automatically discovers the available architecture list from the specified source repository/path.
* Consolidated Role Input: Streamlines the process of assigning multiple roles (Maintainer/Reviewer) to users or groups.
* Post-Creation Action: Offers to execute 'osc browse' to immediately open the newly created project in the web browser.
