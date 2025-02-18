#!/bin/sh

set -eu -o pipefail # Fail on error , debug all lines

if [ $# -ge 1 ] && [ -n "$1" ] ; then
    cd $(dirname $0)/../center-for-threat-informed-defense_attack-flow/attack_flow_builder && {
        if [ $1 = "run" ]; then
            NODE_OPTIONS=--openssl-legacy-provider npm run serve
        elif [ $1 = "build" ]; then
            #NODE_OPTIONS=--openssl-legacy-provider npm run update-intel
            NODE_OPTIONS=--openssl-legacy-provider npm run build
        elif [ $1 = "deploy" ]; then
            perl -ne 'print "$1" if /<\/title>(.*)<\/head>/' dist/index.html > $(dirname $0)/../app/preport/templates/home/template_attack_flow_header.html
            perl -ne 'print "$1" if /<\/div>(.*)<\/body>/' dist/index.html   > $(dirname $0)/../app/preport/templates/home/template_attack_flow_body.html
            rsync -a --progress --delete --exclude "*.map" --exclude "index.html" --exclude "favicon.ico" dist/ $(dirname $0)/../app/petereport/static/attackflow/
            #fd ".*\.map" $(dirname $0)/../app/petereport/static/attackflow/ -tf -X rm
            #rm -f $(dirname $0)/../app/petereport/static/attackflow/{index.html,favicon.ico}
        else
            echo "Attack Flow Command not found"
        fi
    }
fi