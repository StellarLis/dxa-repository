package com.dxaplatform.backendapi.kafka;

/** Публикация в Kafka не подтвердилась (брокер недоступен/timeout). */
public class KafkaPublishException extends RuntimeException {
    public KafkaPublishException(String message, Throwable cause) {
        super(message, cause);
    }
}
