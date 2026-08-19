#!/bin/sh
#
# Turn HTTPS on only if there is a certificate to turn it on with.
#
# nginx treats a missing ssl_certificate file as a fatal configuration error:
# it refuses to start, the container exits, and the deploy's own
# exited-container check turns that into a failed deploy. Which is correct
# behaviour, and exactly why the 443 block cannot simply be present all the
# time -- adding HTTPS would take the site down on every server that has not
# had certificates installed yet, including a fresh one.
#
# So the TLS server block is staged outside the config tree and copied in only
# when both files exist. nginx.conf globs the directory, an empty glob matches
# nothing, and a server without certificates serves plain HTTP and stays up.
#
# There is no redirect from 80 to 443 here on purpose. Cloudflare's
# "Always Use HTTPS" does that at the edge, before the request ever leaves the
# browser's network, which is both faster and one less thing to configure
# twice. Port 80 also has to keep answering locally: the container healthcheck
# and the deploy's smoke test both use it, and redirecting them would report a
# healthy site as broken.

set -e

CERT=/etc/nginx/certs/origin.pem
KEY=/etc/nginx/certs/origin.key

mkdir -p /etc/nginx/tls

if [ -f "$CERT" ] && [ -f "$KEY" ]; then
  # Refuse a key that anyone can read. A private key at 0644 in a bind mount is
  # a private key on the host filesystem for every process on the box.
  PERMS=$(stat -c %a "$KEY" 2>/dev/null || echo "")
  case "$PERMS" in
  600 | 400 | 640 | 440) ;;
  *)
    echo "nginx-entrypoint: WARNING key $KEY has permissions ${PERMS:-unknown}; 600 is expected" >&2
    ;;
  esac

  cp /etc/nginx/tls-available/tls.conf /etc/nginx/tls/tls.conf
  echo "nginx-entrypoint: origin certificate found, HTTPS enabled on 443"
else
  # Leave the directory empty. Said out loud rather than silently, because
  # "why is my site still HTTP" is otherwise a long afternoon.
  rm -f /etc/nginx/tls/tls.conf
  echo "nginx-entrypoint: no origin certificate at $CERT, serving HTTP only"
fi

exec "$@"
