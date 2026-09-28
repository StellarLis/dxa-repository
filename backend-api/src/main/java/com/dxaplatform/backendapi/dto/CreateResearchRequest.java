package com.dxaplatform.backendapi.dto;

import jakarta.validation.constraints.NotBlank;

public record CreateResearchRequest(
        @NotBlank String name,
        String description // необязательное поле, см. п.2 ТЗ (nullable)
) {
}
