package com.dxaplatform.backendapi.dto;

import java.util.UUID;

public record ScanSummaryResponse(
        UUID id,
        String originalFilename,
        String processingStatus
) {
}
