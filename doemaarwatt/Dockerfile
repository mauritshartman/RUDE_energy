# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

ENV S6_KEEP_ENV=1


# Install required packages:
RUN \
    apk add --no-cache \
        nginx \
        nodejs \
        npm

# Install Python requisites:
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt --break-system-packages

# Create required directories
RUN \
    mkdir -p /run/nginx && \
    mkdir -p /usr/bin/static/css /usr/bin/static/js && \
    mkdir -p /data && \
    mkdir -p /data/nginx/logs /data/nginx/tmp/client_body && \
    mkdir -p /etc/nginx/http.d && \
    mkdir -p /var/lib/nginx && \
    mkdir -p /var/lib/nginx/logs

# Set permissions
RUN \
    chown -R root:root /data && \
    chmod -R 755 /data && \
    chmod -R 755 /data/nginx && \
    chmod -R 755 /etc/nginx && \
    chmod -R 755 /usr/bin/static && \
    chown -R root:root /var/lib/nginx && \
    chmod -R 755 /var/lib/nginx && \
    chmod -R 755 /var/lib/nginx/logs && \
    chmod -R 755 /run/nginx

# Copy root filesystem
COPY rootfs /
