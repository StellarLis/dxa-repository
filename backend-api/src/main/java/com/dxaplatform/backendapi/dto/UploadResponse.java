package com.dxaplatform.backendapi.dto;

import java.util.List;
import java.util.UUID;

public record UploadResponse(
        UUID jobId,
        List<ScanSummaryResponse> scans
) {
}
