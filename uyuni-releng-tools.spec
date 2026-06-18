# Copyright (c) 2023 SUSE LLC
# SPDX-FileCopyrightText: 2023 SUSE LLC
#
# SPDX-License-Identifier: Apache-2.0

# Please submit bugfixes or comments via https://bugs.opensuse.org/
#

Name:           uyuni-releng-tools
Version:        0.0.10
Release:        0
Summary:        Tools helping Uyuni release engineers
License:        Apache-2.0
Group:          System/Management
URL:            https://github.com/uyuni-project/uyuni-releng-tools/
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       build
Requires:       cpio
Requires:       git-core
Requires:       git-lfs
Requires:       osc
Requires:       tito
Requires:       dpkg
Requires:       curl
Requires:       gawk
%if 0%{?suse_version} || 0%{?rhel} || 0%{?fedora}
Requires:       rpmdevtools
%endif

%description
Tools helping to prepare Uyuni release submissions.

%prep
%autosetup

%build

%install
install -m 0755 -vd %{buildroot}%{_bindir}
install -m 0755 -vd %{buildroot}%{_datadir}/%{name}
install -m 0755 -vd %{buildroot}%{_datadir}/%{name}/scripts/
install -m 0755 -vp ./bin/* %{buildroot}%{_bindir}/
install -m 0644 -cp ./_service %{buildroot}%{_datadir}/%{name}/
install -m 0755 -vp ./share/* %{buildroot}%{_datadir}/%{name}/scripts/

%files
%defattr(-,root,root)
%doc README.md
%license LICENSES/Apache-2.0.txt
%{_bindir}/*
%{_datadir}/%{name}/

%changelog
