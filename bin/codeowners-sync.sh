#!/bin/bash
# SPDX-FileCopyrightText: 2026 SUSE LLC
# SPDX-License-Identifier: Apache-2.0
#
# Usage:
# Execute this script from the spacewalk root directory.
#
# It reads the contents of .github/CODEOWNERS, substitutes the team names and removes nonexisting
# ones according to the rules defined in SUBSTITUTION_COMMANDS below.
#
# The resulting file is saved into file named 'CODEOWNERS_spacewalk_temp'
#
set -e

# --- Configuration ---
SOURCE_FILE=".github/CODEOWNERS"
TARGET_FILE="CODEOWNERS_spacewalk_temp"

# Define the substitution and filtering using an array of sed commands.
# We use /d for filtering (deleting lines matching the pattern) and s/find/replace/g for substitution.

# IMPORTANT: The substitution patterns are escaped for sed.
SUBSTITUTION_COMMANDS=(
    # Remove lines for the teams that dont't exist in Spacewalk:
    '/@uyuni-project\/workflows-reviewers/d'
    '/@uyuni-project\/sumaform-developers/d'

    # Substitutions
    # Release Engineering
    's/@uyuni-project\/release-engineering/@SUSE\/multi-linux-manager-releng/g'
    # Python
    's/@uyuni-project\/python/@SUSE\/multi-linux-manager-python/g'
    # Frontend
    's/@uyuni-project\/frontend/@SUSE\/multi-linux-manager-frontend/g'
    # QE
    's/@uyuni-project\/qe/@SUSE\/multi-linux-manager-qe/g'
    # Java
    's/@uyuni-project\/java/@SUSE\/multi-linux-manager-java/g'
    # Naica
    's/@uyuni-project\/naica/@SUSE\/multi-linux-manager-naica/g'
)

# --- Execution ---

echo "Starting CODEOWNERS substitution for Spacewalk repository..."

# Start with cat and pipe through sed for each command in the array
COMMAND_CHAIN="cat $SOURCE_FILE"

for cmd in "${SUBSTITUTION_COMMANDS[@]}"; do
    # Add the sed command to the chain
    COMMAND_CHAIN="${COMMAND_CHAIN} | sed -e '${cmd}'"
done

# Execute the final pipeline and direct the output to the temporary file
eval $COMMAND_CHAIN > "$TARGET_FILE"

echo "Filtering and substitution complete. Output saved to $TARGET_FILE"
