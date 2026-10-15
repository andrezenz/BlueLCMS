#!/bin/sh
set -eu

prefix="${BLUELCMS_INSTALL_PREFIX:-${HOME}/.local}"
mkdir -p "${prefix}/bin" "${prefix}/share/applications" "${prefix}/share/icons/hicolor/scalable/apps" "${prefix}/share/thumbnailers" "${prefix}/share/mime/packages"
rm -rf "${prefix}/share/BlueLCMS"
cp -R BlueLCMS "${prefix}/share/BlueLCMS"
ln -sf "../share/BlueLCMS/BlueLCMS" "${prefix}/bin/BlueLCMS"
install -m 644 BlueLCMS.desktop "${prefix}/share/applications/BlueLCMS.desktop"
install -m 644 bluelcms.svg "${prefix}/share/icons/hicolor/scalable/apps/bluelcms-teal.svg"
sed "s|^Icon=.*|Icon=${prefix}/share/icons/hicolor/scalable/apps/bluelcms-teal.svg|" BlueLCMS.desktop > "${prefix}/share/applications/BlueLCMS.desktop"
thumbnailer_code=$(base64 < bluelcms-thumbnailer.py | tr -d '\n')
printf '%s\n' \
    '[Thumbnailer Entry]' \
    'TryExec=/usr/bin/python3' \
    "Exec=/usr/bin/python3 -c \"import base64;exec(compile(base64.b64decode('${thumbnailer_code}'),'<bluelcms-thumbnailer>','exec'))\" %s %i %o" \
    'MimeType=application/x-bluelcms-cache;application/x-bluelcms-mzml;application/x-bluelcms-mzml-gzip;' \
    > "${prefix}/share/thumbnailers/bluelcms.thumbnailer"
install -m 644 bluelcms-mime.xml "${prefix}/share/mime/packages/bluelcms.xml"
if command -v update-mime-database >/dev/null 2>&1; then
    update-mime-database "${prefix}/share/mime"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${prefix}/share/applications"
fi
printf '%s\n' "BlueLCMS Nautilus thumbnails registered; log out/in or restart Files to refresh file types."
printf '%s\n' "BlueLCMS installed to ${prefix}/bin/BlueLCMS"
