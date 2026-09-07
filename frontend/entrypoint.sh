#!/bin/sh
set -eu

api_upstream="${API_UPSTREAM:-http://api:8000}"
port="${PORT:-80}"

case "$api_upstream" in
  http://*|https://*) ;;
  *)
    echo "API_UPSTREAM_CONFIGURED: NO"
    echo "NGINX_UPSTREAM_TARGET: INVALID"
    echo "API_UPSTREAM must be an http(s) URL"
    exit 1
    ;;
esac

upstream_target="${api_upstream#*://}"
case "$upstream_target" in
  ""|*[!A-Za-z0-9._:/-]*)
    echo "API_UPSTREAM_CONFIGURED: NO"
    echo "NGINX_UPSTREAM_TARGET: INVALID"
    echo "API_UPSTREAM contains an invalid host or port"
    exit 1
    ;;
esac

case "$port" in
  ""|*[!0-9]*)
    echo "API_UPSTREAM_CONFIGURED: YES"
    echo "NGINX_UPSTREAM_TARGET: $upstream_target"
    echo "PORT must be numeric"
    exit 1
    ;;
esac

export API_UPSTREAM="$api_upstream" PORT="$port"
envsubst '${API_UPSTREAM} ${PORT}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

echo "API_UPSTREAM_CONFIGURED: YES"
echo "NGINX_UPSTREAM_TARGET: $upstream_target"
nginx -t
exec nginx -g 'daemon off;'
