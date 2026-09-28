package com.dxaplatform.backendapi.dto;

import java.time.Instant;
import java.util.UUID;

/** Раздел 3 ТЗ: "Scan detail -- click a scan to see full result (all fields)". */
public record ScanDetailResponse(
        UUID id,
        UUID researchId,
        UUID jobId,
        String originalFilename,
        String studyUid,
        String imageUid,
        String anatomicalRegion,
        Short qualityClass,
        String violationType,
        String comment,
        String processingStatus,
        String errorMessage,
        Double timeOfProcessing,
        String thumbnailPngB64,
        Instant uploadedAt,
        Instant processedAt
) {
}
