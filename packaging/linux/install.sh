#!/bin/sh
set -eu

prefix="${HOME}/.local"
mkdir -p "${prefix}/bin" "${prefix}/share/applications"
install -m 755 BlueLCMS "${prefix}/bin/BlueLCMS"
install -m 644 BlueLCMS.desktop "${prefix}/share/applications/BlueLCMS.desktop"
printf '%s\n' "BlueLCMS installed to ${prefix}/bin/BlueLCMS"
