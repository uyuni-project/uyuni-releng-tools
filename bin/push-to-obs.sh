#! /bin/sh -e

# Copyright (c) 2026 SUSE LLC
# SPDX-FileCopyrightText: 2023 SUSE LLC
#
# SPDX-License-Identifier: Apache-2.0


# Set pipefail so the result of a pipe is different to zero if one of the commands fail.
# This way, we can add tee but be sure the result would be non zero if the command before has failed.
set -o pipefail


SCRIPT=$(basename ${0})
help() {
  echo ""
  echo "Script to run a container to push SUSE Multi-Linux Manager/Uyuni packages to IBS/OBS"
  echo ""
  echo "Syntax: "
  echo ""
  echo "${SCRIPT} -d <API1|PROJECT1>[,<API2|PROJECT2>...] -c OSC_CFG_FILE -s SSH_PRIVATE_KEY [-p PACKAGE1,PACKAGE2,...,PACKAGEN] [-v] [-t] [-n PROJECT]"
  echo ""
  echo "Where: "
  echo "  -d  Comma separated list of destionations in the format API/PROJECT,"
  echo "      for example https://api.opensuse.org|systemsmanagement:Uyuni:Master"
  echo "  -c  Path to the OSC credentials (usually ~/.osrc)"
  echo "  -C  Container to use (default: registry.opensuse.org/systemsmanagement/uyuni/master/docker/containers/uyuni-push-to-obs)"
  echo "  -s  Path to the private key used for MFA, a file ending with .pub must also"
  echo "      exist, containing the public key"
  echo "  -g  Path to TEA config (usually ~/.config/tea/config.yml)"
  echo "  -p  Comma separated list of packages. If absent, all packages are submitted"
  echo "  -v  Verbose mode"
  echo "  -t  For tito, use current branch HEAD instead of latest package tag"
  echo "  -n  If used, update PROJECT instead of the projects specified with -d,"
  echo "      for example, if you want to package only the changes from a PR on"
  echo "      a separate project"
  echo "  -e  If used, when checking out projects from obs, links will be expanded. Useful for comparing packages that are links"
  echo "  -N  Set as user name in git config"
  echo "  -E  Set as user email address in git config"
  echo ""
  echo "By default 'docker' is used to run the container. To use podman instead set EXECUTOR=podman"
  echo "Extra options for the executor please provide set EXECUTOR_OPTS"
  echo ""
}

EXECUTOR="${EXECUTOR:=docker}"
EXECUTOR_OPTS="${EXECUTOR_OPTS}"

SCRIPTDIR="/usr/share/uyuni-releng-tools/scripts"

while getopts ":d:c:C:s:g:p:n:N:E:vthe" opts; do
  case "${opts}" in
    d) DESTINATIONS=${OPTARG};;
    p) PACKAGES=${OPTARG};;
    c) CREDENTIALS=${OPTARG};;
    C) CONTAINER=${OPTARG};;
    s) SSHKEY=${OPTARG};;
    g) TEACONF=${OPTARG};;
    v) VERBOSE="-v"; set -x;;
    t) TEST="-t";;
    n) OBS_TEST_PROJECT="-n ${OPTARG}";;
    e) EXTRA_OPTS="-e";;
    N) GITUSERNAME=${OPTARG};;
    E) GITUSEREMAIL=${OPTARG};;
    h) help
       exit 0;;
    *) echo "Invalid syntax. Use ${SCRIPT} -h"
       exit 1;;
  esac
done
shift $((OPTIND-1))

GITROOT=$(git rev-parse --show-toplevel)
RELENGDIR="$GITROOT"/rel-eng/packages/
if [ -d "$GITROOT"/.tito/packages/ ]; then
    RELENGDIR="$GITROOT"/.tito/packages/
elif [ ! -d "$RELENGDIR" ]; then
    echo "ERROR: tito packages dir not found"
    exit 1
fi

test -n "$PACKAGES" || {
    PACKAGES=$(ls "$RELENGDIR"|tr ' ' ',')
}

if grep -q -E "[[:space:]]" <<<"$PACKAGES"; then
    echo "ERROR: found whitespace in package list"
    exit 1
fi

test -n "$CONTAINER" || {
    CONTAINER="registry.opensuse.org/systemsmanagement/uyuni/master/docker/containers/uyuni-push-to-obs"
}

if [ "${DESTINATIONS}" == "" ]; then
  echo "ERROR: Mandatory parameter -d is missing!"
  exit 1
fi
if grep -q -E "[[:space:]]" <<<"${DESTINATIONS}"; then
    echo "ERROR: found whitespace in destinations list"
    exit 1
fi

if [ "${CREDENTIALS}" == "" ]; then
  echo "ERROR: Mandatory paramenter -c is missing!"
  exit 1
fi

if [ ! -f ${CREDENTIALS} ]; then
  echo "ERROR: File ${CREDENTIALS} does not exist!"
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
  # Hint: every key provided is mounted as is_rsa, also when it is not an RSA key. It works also for other key types
  MOUNTSSHKEY="--mount type=bind,source=${SSHKEY},target=/root/.ssh/id_rsa --mount type=bind,source=${SSHKEY}.pub,target=/root/.ssh/id_rsa.pub"
  USESSHKEY="-s /root/.ssh/id_rsa"
  SSHDIR=$(dirname ${SSHKEY})
  if [ -f ${SSHDIR}/known_hosts ]; then
    MOUNTSSHKEY="$MOUNTSSHKEY --mount type=bind,source=${SSHDIR}/known_hosts,target=/root/.ssh/known_hosts"
  fi
fi

if [ "${TEACONF}" != "" ]; then
  if [ ! -f ${TEACONF} ]; then
    echo "ERROR: File ${TEACONF} does not exist!"
    exit 1
  fi
  MOUNTTEA="--mount type=bind,source=${TEACONF},target=/root/.config/tea/config.yml"
  USETEACONF="-g /root/.config/tea/config.yml"
fi

COOKIEJAR=$(mktemp /tmp/osc_cookiejar.XXXXXX)
MOUNTCOOKIEJAR="--mount type=bind,source=${COOKIEJAR},target=/root/.osc_cookiejar"

$EXECUTOR pull $CONTAINER

echo "Starting building and submission at $(date)"
date

[ -d ${GITROOT}/logs ] || mkdir ${GITROOT}/logs

export C_UID=$(id -u)
export C_GID=$(id -g)

CMD="$SCRIPTDIR/push-to-obs.sh ${VERBOSE} ${TEST} -d '${DESTINATIONS}' -c /tmp/.oscrc ${USESSHKEY} ${USETEACONF} -E ${GITUSEREMAIL@Q} -N ${GITUSERNAME@Q} -p '${PACKAGES}' ${OBS_TEST_PROJECT} ${EXTRA_OPTS}"
$EXECUTOR run --rm=true -v ${GITROOT}:/manager ${EXECUTOR_OPTS} --mount type=bind,source=${CREDENTIALS},target=/tmp/.oscrc \
	-e C_UID \
	-e C_GID \
	${MOUNTCOOKIEJAR} ${MOUNTSSHKEY} ${MOUNTTEA} ${CONTAINER} /bin/bash -c "${CMD}" | tee ${GITROOT}/logs/${p}.log

echo "End of task at ($(date). Logs for each package at ${GITROOT}/logs/"

# cleanup temp file
rm -f ${COOKIEJAR}
