# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

ENV S6_KEEP_ENV 1


#Add nginx and create the run folder for nginx.
RUN apk add --no-cache nginx nodejs npm


COPY requirements.txt requirements.txt

RUN pip install -r requirements.txt --break-system-packages

# Copy root filesystem
COPY rootfs /
