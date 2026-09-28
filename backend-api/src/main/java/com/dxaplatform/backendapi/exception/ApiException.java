package com.dxaplatform.backendapi.exception;

import org.springframework.http.HttpStatus;

/**
 * Общее исключение для ожидаемых бизнес-ошибок ("email уже занят", "исследование
 * не найдено или не принадлежит вам" и т.п.) -- GlobalExceptionHandler превращает
 * его в консистентный JSON-ответ с нужным HTTP-статусом.
 */
public class ApiException extends RuntimeException {

    private final HttpStatus status;

    public ApiException(HttpStatus status, String message) {
        super(message);
        this.status = status;
    }

    public HttpStatus getStatus() {
        return status;
    }
}
