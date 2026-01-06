# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

ENV S6_KEEP_ENV=1

# Create a group and user for nginx
RUN adduser -S www-data -G www-data
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
    mkdir -p /var/lib/nginx/tmp && \
    mkdir -p /var/lib/nginx/tmp/client_body && \
    mkdir -p /var/lib/nginx/tmp/fastcgi && \
    mkdir -p /var/lib/nginx/tmp/uwsgi && \
    mkdir -p /var/lib/nginx/tmp/scgi && \
    mkdir -p /var/lib/nginx/tmp/proxy

# # Set permissions
RUN \
    chown -R www-data:www-data  /var/log/nginx && \
    chmod -R 755                /var/log/nginx && \
    chown -R www-data:www-data  /var/lib/nginx && \
    chmod -R 755                /var/lib/nginx

# Copy root filesystem
COPY rootfs /

RUN \
    chown -R www-data:www-data  /src/web/dist && \
    chmod -R 755                /src/web/dist
