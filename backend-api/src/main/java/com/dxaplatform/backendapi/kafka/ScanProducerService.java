package com.dxaplatform.backendapi.kafka;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;

import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

@Service
public class ScanProducerService {

    private static final Logger log = LoggerFactory.getLogger(ScanProducerService.class);

    private final KafkaTemplate<String, ScanProcessingMessage> kafkaTemplate;
    private final String topic;

    public ScanProducerService(
            KafkaTemplate<String, ScanProcessingMessage> kafkaTemplate,
            @Value("${app.kafka.scan-requests-topic}") String topic
    ) {
        this.kafkaTemplate = kafkaTemplate;
        this.topic = topic;
    }

    /**
     * СИНХРОННАЯ публикация -- намеренно, не fire-and-forget. Если к моменту
     * загрузки файла Kafka недоступна, вызывающий код (ScanUploadService)
     * должен узнать об этом СРАЗУ и пометить конкретный Scan как FAILED,
     * а не оставить его вечно висеть в статусе QUEUED без единого шанса
     * когда-либо быть обработанным. Ключ сообщения -- scanId, чтобы все
     * события по одному файлу шли в одну партицию (гарантия порядка).
     *
     * @throws KafkaPublishException если публикация не подтвердилась за 5 секунд
     */
    public void publish(ScanProcessingMessage message) {
        try {
            kafkaTemplate.send(topic, message.scanId().toString(), message)
                    .get(5, TimeUnit.SECONDS);
            log.info(
                    "Опубликовано в {}: scanId={} jobId={} filename={}",
                    topic, message.scanId(), message.jobId(), message.filename()
            );
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new KafkaPublishException("Прервано ожидание подтверждения от Kafka", e);
        } catch (ExecutionException | TimeoutException e) {
            log.error("Не удалось опубликовать сообщение для scanId={}", message.scanId(), e);
            throw new KafkaPublishException("Kafka недоступна или не подтвердила приём сообщения", e);
        }
    }
}
