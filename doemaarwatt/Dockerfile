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
    mkdir -p /var/log/nginx

# Set permissions
RUN \
    chown -R root:root /var/log/nginx && \
    chmod -R 755 /var/log/nginx

# Copy root filesystem
COPY rootfs /
