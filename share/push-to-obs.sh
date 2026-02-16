#!/bin/sh -e

# Copyright (c) 2026 SUSE LLC
# SPDX-FileCopyrightText: 2023 SUSE LLC
#
# SPDX-License-Identifier: Apache-2.0

REL_ENG_FOLDER="/manager/rel-eng"
if [ -d "/manager/.tito/" ]; then
  REL_ENG_FOLDER="/manager/.tito"
elif [ ! -d "${REL_ENG_FOLDER}" ]; then
  echo "ERROR: Missing rel-eng folder"
  exit 1
fi

exists() {
  [ -n "$1" -a -e "$1" ]
}

is_package() {
  test -e /tmp/push-packages-to-obs/SRPMS/$1/Dockerfile && { echo "$1 is not a package"; return 1; }
  test -e /tmp/push-packages-to-obs/SRPMS/$1/Chart.yaml && { echo "$1 is not a package"; return 1; }
  exists /tmp/push-packages-to-obs/SRPMS/$1/*.kiwi && { echo "$1 is not a package"; return 1; }
  return 0
}

help() {
  echo ""
  echo "Script to push SUSE Manager/Uyuni packages to IBS/OBS"
  echo ""
  echo "Syntax: "
  echo ""
  echo "${SCRIPT} -d <API1|PROJECT1>[,<API2|PROJECT2>...] -c OSC_CFG_FILE -s SSH_PRIVATE_KEY [-p PACKAGE1,PACKAGE2,...,PACKAGEN] [-v] [-t] [-n PROJECT]"
  echo ""
  echo "Where: "
  echo "  -d  Comma separated list of destinations in the format API|PROJECT or GITURL|BRANCH,"
  echo "      for example https://api.opensuse.org|systemsmanagement:Uyuni:Master,gitea@src.opensuse.org:Galaxy|mlmtools-stable"
  echo "  -p  Comma separated list of packages. If absent, all packages are submitted"
  echo "  -c  Path to the OSC credentials (usually ~/.osrc)"
  echo "  -s  Path to the private key used for MFA, a file ending with .pub must also"
  echo "      exist, containing the public key"
  echo "  -g  Path to TEA config (usually ~/.config/tea/config.yml)"
  echo "  -v  Verbose mode"
  echo "  -t  For tito, use current branch HEAD instead of latest package tag"
  echo "  -n  If used, update PROJECT instead of the projects specified with -d"
  echo "  -e  If used, when checking out projects from obs, links will be expanded. Useful for comparing packages that are links"
  echo "  -N  Set as user name in git config"
  echo "  -E  Set as user email address in git config"
  echo ""
}

OSC_EXPAND="FALSE"

while getopts ":d:c:s:g:p:n:N:E:vthe" opts; do
  case "${opts}" in
    d) DESTINATIONS=${OPTARG};;
    p) PACKAGES="$(echo ${OPTARG}|tr ',' ' ')";;
    c) export OSCRC=${OPTARG};;
    s) export SSHKEY=${OPTARG};;
    g) export TEACONF=${OPTARG};;
    v) export VERBOSE=1; set -x ;;
    t) export TEST=1;;
    n) export OBS_TEST_PROJECT=${OPTARG};;
    e) export OSC_EXPAND="TRUE";;
    N) GITUSERNAME=${OPTARG};;
    E) GITUSEREMAIL=${OPTARG};;
    h) help
       exit 0;;
    *) echo "Invalid syntax. Use ${SCRIPT} -h"
       exit 1;;
  esac
done
shift $((OPTIND-1))

if [ "${DESTINATIONS}" == "" ]; then
  echo "ERROR: Mandatory parameter -d is missing!"
  exit 1
fi

if [ "${OSCRC}" == "" ]; then
  echo "ERROR: Mandatory paramenter -c is missing!"
  exit 1
fi

if [ ! -f ${OSCRC} ]; then
  echo "ERROR: File ${OSCRC} does not exist!"
  exit 1
fi

if [ "${SSHKEY}" != "" ]; then
  if [ ! -f ${SSHKEY} ]; then
    echo "ERROR: File ${SSHKEY} does not exist!"
    exit 1
  fi
  if [ ! -f ${SSHKEY}.pub ]; then
    echo "ERROR: File ${SSHKEY}.pub does not exist!"
    exit 1
  fi
fi

if [ ! -f ${TEACONF} ]; then
  echo "ERROR: File ${TEACONF} does not exist!"
  exit 1
fi

SCRIPTDIR="/usr/share/uyuni-releng-tools/scripts"

# store init permissions
$SCRIPTDIR/initial-objects.sh

# declare /manager as "safe"
git config --global --add safe.directory /manager

cd ${REL_ENG_FOLDER}

# If we have more than one destinations, keep SRPMS so we don't
# need to rebuild for each submission
if [ "$(echo ${DESTINATIONS}|cut -d',' -f2)" != "" ]; then
  export KEEP_SRPMS=TRUE
fi

# Build SRPMS
echo "*************** BUILDING PACKAGES ***************"
build-packages-for-obs ${PACKAGES}

SUBMITTO=""
CHECKED_GIT=no

# Submit
for DESTINATION in $(echo ${DESTINATIONS}|tr ',' ' '); do

  FIRST=$(echo ${DESTINATION}|cut -d'|' -f1)
  SECOND=$(echo ${DESTINATION}|cut -d'|' -f2)

  if [ "${FIRST:0:7}" == "https:/" -o "${FIRST:0:7}" == "http://" ]; then
    # http URL looks like OBS
    SUBMITTO="OBS"
  elif echo ${FIRST} | grep '@.\+:' >/dev/null ; then
    SUBMITTO="GIT"
  fi

  if [ "${SUBMITTO}" = "OBS" ]; then
    export OSCAPI=${FIRST}
    export OBS_PROJ=${SECOND}
    echo "*************** PUSHING TO ${OBS_PROJ} ***************"
    push-packages-to-obs ${PACKAGES}
  elif [ "${SUBMITTO}" = "GIT" ]; then

    if [ "${CHECKED_GIT}" = "no" ]; then
      # we have to have a value; either it is configured or we set one
      if [ -n "$GITUSEREMAIL" ]; then
          git config --global user.email "$GITUSEREMAIL"
      elif [ -z "$(git config --global user.email)" ]; then
          echo "ERROR: no git user email address configured"
          exit 1
      fi
      if [ -n "$GITUSERNAME" ]; then
          git config --global user.name "$GITUSERNAME"
      elif [ -z "$(git config --global user.name)" ]; then
          echo "ERROR: no git user email address configured"
          exit 1
      fi
      CHECKED_GIT=yes
    fi

    export GIT_USR=$(echo ${FIRST}|cut -d'@' -f1)
    export GIT_SRV=$(echo ${FIRST}|cut -d'@' -f2 | cut -d':' -f1)
    export GIT_ORG=$(echo ${FIRST}|cut -d':' -f2 | cut -d'/' -f1)
    export GIT_PRODUCT_REPO=$(echo ${FIRST}|cut -d':' -f2 | cut -d'/' -f2)
    test "${GIT_ORG}" = ${GIT_PRODUCT_REPO} && export GIT_PRODUCT_REPO=""
    export BRANCH=${SECOND}
    PKS=""
    IMS=""
    for P in ${PACKAGES}; do
      is_package $P && PKS="$PKS $P" || IMS="$IMS $P"
    done

    PKS=$(echo "${PKS}" | awk '{$1=$1;print}')
    IMS=$(echo "${IMS}" | awk '{$1=$1;print}')

    if [  -n "${PKS}" -a -z "${GIT_PRODUCT_REPO}" ]; then
      # Push packages only to destinations which do not define a GIT_PRODUCT_REPO
      echo "*************** PUSHING PACKAGES TO ${GIT_USR}@${GIT_SRV}:${GIT_ORG}#${BRANCH} ***************"
      push-packages-to-git ${PKS}
    fi

    if [  -n "${IMS}" -a -n "${GIT_PRODUCT_REPO}" ]; then
      # Push images only to destinations which do define a GIT_PRODUCT_REPO
      echo "*************** PUSHING IMAGES TO ${GIT_USR}@${GIT_SRV}:${GIT_ORG}/${GIT_PRODUCT_REPO}#${BRANCH} ***************"
      push-images-to-git ${IMS}
    fi
  else
    echo "ERROR: unknown where to submit to"
    break
  fi
done

$SCRIPTDIR/chown-objects.sh $C_UID $C_GID

