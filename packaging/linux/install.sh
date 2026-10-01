#!/bin/sh
set -eu

prefix="${HOME}/.local"
mkdir -p "${prefix}/bin" "${prefix}/share/applications" "${prefix}/share/icons/hicolor/scalable/apps"
rm -rf "${prefix}/share/BlueLCMS"
cp -R BlueLCMS "${prefix}/share/BlueLCMS"
ln -sf "../share/BlueLCMS/BlueLCMS" "${prefix}/bin/BlueLCMS"
install -m 644 BlueLCMS.desktop "${prefix}/share/applications/BlueLCMS.desktop"
install -m 644 bluelcms.svg "${prefix}/share/icons/hicolor/scalable/apps/bluelcms.svg"
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f "${prefix}/share/icons/hicolor"
fi
printf '%s\n' "BlueLCMS installed to ${prefix}/bin/BlueLCMS"
