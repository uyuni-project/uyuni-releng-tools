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
