#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 SUSE LLC
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# Script Name: compare_uyuni_repos.sh
# Description: Compares package versions between a "Master" and "Stable" 
#              repositories for Uyuni. 
#              It automatically detects the repository format (RPM or DEB) 
#              and verifies that all packages in the Master repo have
#              "version-release" equal or newer than their counterparts
#              in the Stable repo.
#
# Dependencies:
#   - Common: curl, awk
#   - RPM Repos: rpmdev-vercmp (usually from the 'rpmdevtools' package)
#   - DEB Repos: dpkg
#
# Usage:
#   ./compare_uyuni_repos.sh <master_repo_url>
#
# Examples:
#   # RPM Example:
#   ./compare_uyuni_repos.sh https://download.opensuse.org/repositories/systemsmanagement:/Uyuni:/Master:/SLE15-Uyuni-Client-Tools/SLE_15/
#   
#   # Debian Example:
#   ./compare_uyuni_repos.sh https://download.opensuse.org/repositories/systemsmanagement:/Uyuni:/Master:/Debian13-Uyuni-Client-Tools/Debian_13/
#
# Exit Codes:
#   0 - Success: All matching Master packages are >= Stable.
#   1 - Failure: Missing dependencies, fetch error, or Stable > Master.
# ==============================================================================

# Exit immediately if a command exits with a non-zero status
set -euo pipefail

# Check for required tools
for cmd in curl awk; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "Error: Required tool '$cmd' is not installed." >&2
        exit 1
    fi
done

# Validate input
if [ $# -lt 1 ]; then
    echo "Usage: $0 <master_repo_url>"
    exit 1
fi

MASTER_URL="$1"
# Ensure URL ends with a trailing slash
[[ "${MASTER_URL}" != */ ]] && MASTER_URL="${MASTER_URL}/"

if [[ ! "$MASTER_URL" =~ "Master" ]]; then
    echo "Error: The provided URL does not contain 'Master'." >&2
    exit 1
fi
STABLE_URL="${MASTER_URL/Master/Stable}"

echo "Target Master Repo: $MASTER_URL"
echo "Target Stable Repo: $STABLE_URL"
echo "--------------------------------------------------"

# ---------------------------------------------------------
# Detect Repository Type
# ---------------------------------------------------------
REPO_TYPE="unknown"
if curl -sSL -I -f "${MASTER_URL}repodata/repomd.xml" > /dev/null 2>&1; then
    REPO_TYPE="rpm"
    echo "🔍 Detected Repository Type: RPM"
    if ! command -v rpmdev-vercmp &> /dev/null; then
        echo "Error: 'rpmdev-vercmp' is required for RPM repos (install rpmdevtools)." >&2
        exit 1
    fi
elif curl -sSL -I -f "${MASTER_URL}Packages.gz" > /dev/null 2>&1; then
    REPO_TYPE="deb"
    echo "🔍 Detected Repository Type: Debian (DEB)"
    if ! command -v dpkg &> /dev/null; then
        echo "Error: 'dpkg' is required for Deb repos to compare versions." >&2
        exit 1
    fi
else
    echo "Error: Could not determine repository type. Neither repodata/repomd.xml nor Packages.gz were found." >&2
    exit 1
fi

# Create a temporary directory for repo metadata caching
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# ---------------------------------------------------------
# Fetching Functions
# ---------------------------------------------------------

fetch_rpm_packages() {
    local repo_url="$1"
    local repo_name="$2"
    local out_file="$3"

    echo "Fetching RPM metadata for $repo_name..." >&2

    local repomd_url="${repo_url}repodata/repomd.xml"
    local repomd_xml
    
    if ! repomd_xml=$(curl -sSL -f "$repomd_url"); then
        echo "Error: Failed to fetch repomd.xml" >&2; exit 1
    fi

    local primary_href
    primary_href=$(echo "$repomd_xml" | grep -oE 'href="[^"]*primary\.xml\.(gz|zst|bz2)"' | head -n 1 | cut -d'"' -f2 || true)

    if [ -z "$primary_href" ]; then
        echo "Error: Could not find primary metadata location in repomd.xml" >&2; exit 1
    fi

    local primary_url="${repo_url}${primary_href}"
    local ext="${primary_href##*.}"
    local primary_file="$TMP_DIR/${repo_name}_primary.${ext}"

    if ! curl -sSL -f "$primary_url" -o "$primary_file"; then
         echo "Error: Failed to fetch $primary_url" >&2; exit 1
    fi

    local cat_cmd=""
    case "$ext" in
        gz)  cat_cmd="gzip -cd" ;;
        zst) cat_cmd="zstdcat" ;;
        bz2) cat_cmd="bzcat" ;;
    esac

    $cat_cmd "$primary_file" | awk '
        /<package type="rpm">/ { in_pkg=1; name=""; arch=""; ver=""; rel="" }
        in_pkg && /<name>/ { s=$0; sub(/.*<name>/,"",s); sub(/<\/name>.*/,"",s); name=s }
        in_pkg && /<arch>/ { s=$0; sub(/.*<arch>/,"",s); sub(/<\/arch>.*/,"",s); arch=s }
        in_pkg && /<version / {
            s=$0; 
            if (match(s, /ver="[^"]+"/)) ver = substr(s, RSTART+5, RLENGTH-6)
            if (match(s, /rel="[^"]+"/)) rel = substr(s, RSTART+5, RLENGTH-6)
        }
        in_pkg && /<\/package>/ {
            gsub(/^[ \t]+|[ \t]+$/, "", name); gsub(/^[ \t]+|[ \t]+$/, "", arch);
            if (name != "") printf "%s|%s|%s-%s\n", name, arch, ver, rel;
            in_pkg=0
        }
    ' | sort -u > "$out_file"
}

fetch_deb_packages() {
    local repo_url="$1"
    local repo_name="$2"
    local out_file="$3"

    echo "Fetching Debian metadata for $repo_name..." >&2

    local packages_url="${repo_url}Packages.gz"
    local packages_file="$TMP_DIR/${repo_name}_Packages.gz"

    if ! curl -sSL -f "$packages_url" -o "$packages_file"; then
         echo "Error: Failed to fetch $packages_url" >&2
         exit 1
    fi

    # Parse standard Debian Packages format
    gzip -cd "$packages_file" | awk '
        /^Package:/ { pkg=$2 }
        /^Architecture:/ { arch=$2 }
        /^Version:/ { ver=$2 }
        /^$/ {
            if (pkg != "") printf "%s|%s|%s\n", pkg, arch, ver;
            pkg=""; arch=""; ver="";
        }
        END {
            # Catch the last package if file does not end with an empty line
            if (pkg != "") printf "%s|%s|%s\n", pkg, arch, ver;
        }
    ' | sort -u > "$out_file"
}

# ---------------------------------------------------------
# Execution logic
# ---------------------------------------------------------

echo "--------------------------------------------------"

if [ "$REPO_TYPE" == "rpm" ]; then
    fetch_rpm_packages "$MASTER_URL" "master_repo" "$TMP_DIR/master_pkgs.txt"
    fetch_rpm_packages "$STABLE_URL" "stable_repo" "$TMP_DIR/stable_pkgs.txt"
elif [ "$REPO_TYPE" == "deb" ]; then
    fetch_deb_packages "$MASTER_URL" "master_repo" "$TMP_DIR/master_pkgs.txt"
    fetch_deb_packages "$STABLE_URL" "stable_repo" "$TMP_DIR/stable_pkgs.txt"
fi

echo "--------------------------------------------------"
echo "Comparing packages (Master vs Stable)..."
echo "--------------------------------------------------"

warnings=0
pkg_count=0

# Read the Master packages line by line (Format: name|arch|version-release)
while IFS='|' read -r pkg_name pkg_arch master_vr; do
    [ -z "$pkg_name" ] && continue
    pkg_count=$((pkg_count + 1))

    echo "📦 Checking: $pkg_name ($pkg_arch)"
    echo "   ├─ Master: $master_vr"

    # Look up the exact package name AND architecture in the Stable package list
    stable_lines=$(grep -F "${pkg_name}|${pkg_arch}|" "$TMP_DIR/stable_pkgs.txt" || true)

    if [ -z "$stable_lines" ]; then
        echo "   └─ Not found in Stable (Skipping)"
        continue
    fi

    while read -r s_line; do
        stable_vr="${s_line##*|}"
        echo "   ├─ Stable: $stable_vr"

        warn_triggered=0

        if [ "$REPO_TYPE" == "rpm" ]; then
            set +e
            rpmdev-vercmp "$master_vr" "$stable_vr" > /dev/null
            cmp_res=$?
            set -e
            # 0: equal, 11: master is newer, 12: stable is newer
            # We ONLY want to warn if stable is strictly newer (12)
            if [ "$cmp_res" -eq 12 ]; then
                warn_triggered=1
            fi
        elif [ "$REPO_TYPE" == "deb" ]; then
            # "lt" means strictly less-than. If master < stable, throw warning.
            if dpkg --compare-versions "$master_vr" lt "$stable_vr"; then
                warn_triggered=1
            fi
        fi

        if [ "$warn_triggered" -eq 1 ]; then
            echo "   └─ ⚠️  WARNING: Master is strictly older than Stable!"
            warnings=$((warnings + 1))
        else
            echo "   └─ ✅ OK (Master >= Stable)"
        fi
    done <<< "$stable_lines"

done < "$TMP_DIR/master_pkgs.txt"

echo "--------------------------------------------------"
echo "Total Master packages evaluated: $pkg_count"

if [ "$warnings" -eq 0 ]; then
    echo "✅ Success: All matching packages in Master are newer than or equal to their Stable counterparts."
else
    echo "❌ Completed with warnings: Found $warnings package(s) where Stable is strictly newer than Master."
    exit 1
fi
