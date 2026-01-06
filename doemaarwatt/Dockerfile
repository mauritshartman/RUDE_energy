# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

ENV S6_KEEP_ENV=1

# Create a group and user for nginx
# RUN addgroup -S nginx && adduser -S nginx -G nginx
# USER nginx

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
    mkdir -p /var/log/nginx && \
    mkdir -p /var/lib/nginx && \
    mkdir -p /var/lib/nginx/logs && \
    mkdir -p /var/lib/nginx/tmp

# Set permissions
RUN \
    chown -R root:root  /var/log/nginx && \
    chmod -R 777        /var/log/nginx && \
    chown -R root:root  /var/lib/nginx && \
    chmod -R 777        /var/lib/nginx
    chown -R root:root  /var/lib/nginx/tmp && \
    chmod -R 777        /var/lib/nginx/tmp

# Copy root filesystem
COPY rootfs /
