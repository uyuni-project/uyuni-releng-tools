# Copyright (c) 2023 SUSE LLC
# SPDX-FileCopyrightText: 2023 SUSE LLC
#
# SPDX-License-Identifier: Apache-2.0

# Please submit bugfixes or comments via https://bugs.opensuse.org/
#

Name:           uyuni-releng-tools
Version:        0.0.1
Release:        1
Summary:        Tools helping Uyuni release engineers
License:        Apache-2.0
Group:          System/Management
URL:            https://github.com/uyuni-project/uyuni-releng-tools/
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

%description
Tools helping to prepare Uyuni release submissions.

%prep
%autosetup

%build
# Test comment

%install
install -m 0755 -vd %{buildroot}%{_bindir}
install -m 0755 -vp ./bin/* %{buildroot}%{_bindir}/
install -m 0755 -vd %{buildroot}%{_datadir}/%{name}
install -m 0644 -cp ./_service %{buildroot}%{_datadir}/%{name}/

%files
%defattr(-,root,root)
%doc README.md
%license LICENSES/Apache-2.0.txt
%{_bindir}/*
%{_datadir}/%{name}/

%changelog
