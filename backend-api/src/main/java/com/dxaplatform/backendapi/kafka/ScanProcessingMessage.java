package com.dxaplatform.backendapi.kafka;

import java.util.UUID;

/**
 * JSON-контракт сообщения в топик dicom-processing-requests (раздел 4.4 ТЗ).
 * Имена полей -- camelCase, ровно как в спецификации; это намеренно
 * ПРОСТОЙ JSON, не завязанный на Java-классы producer'а (см. application.yml,
 * spring.json.add.type.headers: false) -- backend-worker десериализует его
 * в свой собственный такой же DTO, не наш.
 */
public record ScanProcessingMessage(
        UUID scanId,
        UUID jobId,
        UUID researchId,
        UUID userId,
        String filename,
        String fileBase64
) {
}
