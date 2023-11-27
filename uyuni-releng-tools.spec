#
# spec file for package uyuni-releng-tools
#
# Copyright (c) 2023 SUSE LLC
#
# All modifications and additions to the file contributed by third parties
# remain the property of their copyright owners, unless otherwise agreed
# upon. The license for this file, and modifications and additions to the
# file, is the same license as for the pristine package itself (unless the
# license for the pristine package is not an Open Source License, in which
# case the license is the MIT License). An "Open Source License" is a
# license that conforms to the Open Source Definition (Version 1.9)
# published by the Open Source Initiative.

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
