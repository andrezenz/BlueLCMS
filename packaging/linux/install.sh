#!/bin/sh
set -eu

prefix="${HOME}/.local"
mkdir -p "${prefix}/bin" "${prefix}/share/applications" "${prefix}/share/icons/hicolor/scalable/apps"
rm -rf "${prefix}/share/BlueLCMS"
cp -R BlueLCMS "${prefix}/share/BlueLCMS"
ln -sf "../share/BlueLCMS/BlueLCMS" "${prefix}/bin/BlueLCMS"
install -m 644 BlueLCMS.desktop "${prefix}/share/applications/BlueLCMS.desktop"
install -m 644 bluelcms.svg "${prefix}/share/icons/hicolor/scalable/apps/bluelcms-teal.svg"
sed "s|^Icon=.*|Icon=${prefix}/share/icons/hicolor/scalable/apps/bluelcms-teal.svg|" BlueLCMS.desktop > "${prefix}/share/applications/BlueLCMS.desktop"
printf '%s\n' "BlueLCMS installed to ${prefix}/bin/BlueLCMS"
