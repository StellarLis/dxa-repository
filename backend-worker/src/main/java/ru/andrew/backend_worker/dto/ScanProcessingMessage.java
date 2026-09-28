package ru.andrew.backend_worker.dto;

import java.util.UUID;

public record ScanProcessingMessage(
        UUID scanId,
        UUID jobId,
        UUID researchId,
        UUID userId,
        String filename,
        String fileBase64
) {
}