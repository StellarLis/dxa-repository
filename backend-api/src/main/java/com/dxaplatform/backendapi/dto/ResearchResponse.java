package com.dxaplatform.backendapi.dto;

import java.time.Instant;
import java.util.UUID;

/** scanCount нужен для главной страницы "My Researches" (п.3 ТЗ: "showing name, scan count, last updated"). */
public record ResearchResponse(
        UUID id,
        String name,
        String description,
        long scanCount,
        Instant createdAt,
        Instant updatedAt
) {
}
