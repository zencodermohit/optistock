# The edge: builds the React application and serves it alongside the API proxy.
#
# One nginx, not two. The frontend is static files once built, and the edge is
# already terminating every request -- giving the UI its own container would add
# a second hop and a second place for the two to disagree about routing.

# --- build -------------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Manifests first, so `npm ci` is only re-run when dependencies actually change.
# Copying the whole source first would invalidate this layer on every edit and
# reinstall the world for a one-line CSS change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# `npm run build` is `tsc -b && vite build`, so a type error fails the image
# build rather than shipping a broken bundle.
RUN npm run build

# --- serve -------------------------------------------------------------------
FROM nginx:alpine

COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/app.conf /etc/nginx/app.conf
# Staged, not installed. The entrypoint moves this into /etc/nginx/tls/ only
# when an origin certificate is present -- see nginx/docker-entrypoint.sh.
COPY nginx/tls.conf /etc/nginx/tls-available/tls.conf
COPY nginx/redirect.conf.template /etc/nginx/tls-available/redirect.conf.template
COPY nginx/docker-entrypoint.sh /docker-entrypoint-tls.sh
RUN chmod +x /docker-entrypoint-tls.sh && mkdir -p /etc/nginx/tls
COPY --from=build /app/dist /usr/share/nginx/html

# No `nginx -t` here, deliberately. It resolves every upstream as part of the
# check, and `api` only exists on the compose network at run time -- so the
# check fails on a perfectly valid config. Faking the name out of /etc/hosts
# doesn't help either; BuildKit mounts it read-only. A broken config is caught
# instead by the container healthcheck and by the deploy step, which fails when
# any container exits on startup.

EXPOSE 80 443

# Wraps the stock nginx entrypoint rather than replacing it: the base image's
# own /docker-entrypoint.sh does the envsubst and IPv6 setup that the official
# image is expected to do, and skipping it would be a silent behaviour change.
ENTRYPOINT ["/docker-entrypoint-tls.sh", "/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
