package com.dxaplatform.backendapi.entity;

public enum JobStatus {
    PENDING,
    PROCESSING,
    SUCCESS,
    FAILED,
    /** часть сканов в батче успешна, часть -- нет */
    PARTIAL
}
