package com.dxaplatform.backendapi.dto;

public record ScanStatusCounts(
        long pending,
        long queued,
        long processing,
        long success,
        long failed
) {
}
