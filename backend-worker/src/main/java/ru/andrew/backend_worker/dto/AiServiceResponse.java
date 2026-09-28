package ru.andrew.backend_worker.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

@Data
public class AiServiceResponse {
    @JsonProperty("job_id")
    private String job_id;

    @JsonProperty("results")
    private List<FileReportResponse> fileReports;
}
