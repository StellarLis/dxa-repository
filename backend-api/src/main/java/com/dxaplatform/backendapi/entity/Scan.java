package com.dxaplatform.backendapi.entity;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;
import java.util.UUID;

/**
 * Одна строка на один загруженный DICOM-файл. Поля study_uid .. thumbnail_png_b64
 * заполняются backend-worker'ом после ответа ИИ-модуля (см. раздел 7 ТЗ) -- до
 * этого момента они null, а processingStatus = PENDING/QUEUED.
 */
@Entity
@Table(name = "scans")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Scan {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "research_id", nullable = false)
    private Research research;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "job_id", nullable = false)
    private ProcessingJob job;

    @Column(name = "original_filename", nullable = false, length = 500)
    private String originalFilename;

    @Column(name = "study_uid")
    private String studyUid;

    @Column(name = "image_uid")
    private String imageUid;

    @Column(name = "anatomical_region", length = 50)
    private String anatomicalRegion;

    /**
     * 0/1 -- есть нарушение или нет. null означает ЛИБО ещё не обработано,
     * ЛИБО критерии неприменимы (например, обнаружен эндопротез -- см. историю
     * решения детектора протеза в ai-service). Различать эти два случая нужно
     * по processingStatus (PENDING/QUEUED/PROCESSING -> ещё не обработано;
     * SUCCESS + qualityClass=null -> критерии сознательно неприменимы).
     */
    @Column(name = "quality_class")
    private Short qualityClass;

    @Column(name = "violation_type", length = 500)
    private String violationType;

    @Column(columnDefinition = "TEXT")
    private String comment;

    @Enumerated(EnumType.STRING)
    @Column(name = "processing_status", nullable = false, length = 20)
    @Builder.Default
    private ProcessingStatus processingStatus = ProcessingStatus.PENDING;

    @Column(name = "error_message", columnDefinition = "TEXT")
    private String errorMessage;

    @Column(name = "time_of_processing")
    private Double timeOfProcessing;

    @Column(name = "thumbnail_png_b64", columnDefinition = "TEXT")
    private String thumbnailPngB64;

    @Column(name = "uploaded_at", nullable = false, updatable = false)
    @Builder.Default
    private Instant uploadedAt = Instant.now();

    @Column(name = "processed_at")
    private Instant processedAt;
}
