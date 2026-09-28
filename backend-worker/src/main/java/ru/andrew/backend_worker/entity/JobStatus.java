package ru.andrew.backend_worker.entity;

public enum JobStatus {
    PENDING,
    PROCESSING,
    SUCCESS,
    FAILED,
    /** часть сканов в батче успешна, часть -- нет */
    PARTIAL
}
