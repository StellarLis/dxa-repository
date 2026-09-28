package com.dxaplatform.backendapi.exception;

import java.time.Instant;

/** Единый формат тела ошибки для всех эндпоинтов (см. п.9 ТЗ). */
public record ErrorResponse(
        Instant timestamp,
        int status,
        String error,
        String message
) {
    public static ErrorResponse of(int status, String error, String message) {
        return new ErrorResponse(Instant.now(), status, error, message);
    }
}
