ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache python3

WORKDIR /app
COPY read_jk_bms.py jk_bms_mqtt.py run.sh ./
RUN chmod +x /app/run.sh /app/read_jk_bms.py /app/jk_bms_mqtt.py

CMD ["/app/run.sh"]
