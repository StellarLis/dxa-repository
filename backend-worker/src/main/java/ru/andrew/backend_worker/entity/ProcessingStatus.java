package ru.andrew.backend_worker.entity;

public enum ProcessingStatus {
    PENDING,
    QUEUED,
    PROCESSING,
    SUCCESS,
    FAILED
}
