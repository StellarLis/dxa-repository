package ru.andrew.backend_worker.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
public class FileReportResponse {
    @JsonProperty("filename")
    private String filename;

    @JsonProperty("study_uid")
    private String studyUid;

    @JsonProperty("image_uid")
    private String imageUid;

    @JsonProperty("anatomical_region")
    private String anatomicalRegion;

    @JsonProperty("quality_class")
    private Short qualityClass;

    @JsonProperty("violation_type")
    private String violationType;

    @JsonProperty("comment")
    private String comment;

    @JsonProperty("processing_status")
    private String processingStatus;

    @JsonProperty("error_message")
    private String errorMessage;

    @JsonProperty("time_of_processing")
    private Double timeOfProcessing;

    @JsonProperty("thumbnail_png_b64")
    private String thumbnailPngB64;
}
