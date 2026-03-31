# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# ENV S6_KEEP_ENV=1

# Install Python requisites:
COPY requirements.txt requirements.txt
RUN apk add --no-cache --virtual .build-deps gcc g++ musl-dev python3-dev \
    && pip install -r requirements.txt --break-system-packages \
    && apk del .build-deps

# Copy root filesystem
COPY rootfs /

COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
