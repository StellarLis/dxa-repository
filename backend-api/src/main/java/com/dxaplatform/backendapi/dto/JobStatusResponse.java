package com.dxaplatform.backendapi.dto;

import java.time.Instant;
import java.util.UUID;

/**
 * Раздел 4.3 ТЗ: "job status summary (counts by status), for polling" --
 * фронтенд опрашивает этот эндпоинт каждые 2-3с, пока status не станет
 * терминальным (SUCCESS/FAILED/PARTIAL), не дергая список сканов целиком.
 */
public record JobStatusResponse(
        UUID jobId,
        String status,
        int totalScans,
        ScanStatusCounts counts,
        Instant createdAt,
        Instant completedAt
) {
}
