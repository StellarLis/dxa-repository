package ru.andrew.backend_worker.service;

import lombok.AllArgsConstructor;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.MediaType;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import ru.andrew.backend_worker.dto.AiServiceResponse;
import ru.andrew.backend_worker.dto.FileReportResponse;
import ru.andrew.backend_worker.dto.ScanProcessingMessage;
import ru.andrew.backend_worker.entity.ProcessingStatus;
import ru.andrew.backend_worker.entity.Scan;
import ru.andrew.backend_worker.repository.ScanRepository;

import java.util.Base64;
import java.util.List;
import java.time.Instant;
import java.util.Locale;
import java.util.Objects;

@Service
@AllArgsConstructor
public class ConsumerService {
    private static final Logger log = LoggerFactory.getLogger(ConsumerService.class);

    private final RestClient restClient;

    private final ScanRepository scanRepository;

    @KafkaListener(topics = "dicom-processing-requests", groupId = "my-consumer-group")
    public void consume(ScanProcessingMessage message) {
        Scan scan = scanRepository.findById(message.scanId()).orElse(null);
        if (scan == null) {
            log.warn("Ignoring processing message for unknown scanId={} jobId={}",
                    message.scanId(), message.jobId());
            return;
        }

        try {
            AiServiceResponse response = uploadToAiService(message);
            FileReportResponse report = findReport(response, message.filename());
            applyReport(scan, report);
        } catch (RuntimeException exception) {
            log.error("AI processing failed for scanId={} jobId={}",
                    message.scanId(), message.jobId(), exception);
            markFailed(scan, exception.getMessage());
        }
    }

    private FileReportResponse findReport(AiServiceResponse response, String filename) {
        if (response == null || response.getFileReports() == null || response.getFileReports().isEmpty()) {
            throw new IllegalStateException("AI service returned no file results");
        }

        List<FileReportResponse> reports = response.getFileReports();
        return reports.stream()
                .filter(report -> report != null && Objects.equals(report.getFilename(), filename))
                .findFirst()
                .orElseGet(() -> reports.size() == 1 ? reports.get(0) : null);
    }

    private void applyReport(Scan scan, FileReportResponse report) {
        if (report == null) {
            markFailed(scan, "AI service returned no result for the uploaded file");
            return;
        }

        scan.setStudyUid(report.getStudyUid());
        scan.setImageUid(report.getImageUid());
        scan.setAnatomicalRegion(report.getAnatomicalRegion());
        scan.setQualityClass(report.getQualityClass());
        scan.setViolationType(report.getViolationType());
        scan.setComment(report.getComment());
        scan.setErrorMessage(report.getErrorMessage());
        scan.setTimeOfProcessing(report.getTimeOfProcessing());
        scan.setThumbnailPngB64(report.getThumbnailPngB64());
        scan.setProcessingStatus(isFailure(report.getProcessingStatus())
                ? ProcessingStatus.FAILED
                : ProcessingStatus.SUCCESS);
        scan.setProcessedAt(Instant.now());
        scanRepository.saveAndFlush(scan);
    }

    private void markFailed(Scan scan, String message) {
        scan.setProcessingStatus(ProcessingStatus.FAILED);
        scan.setErrorMessage(message == null || message.isBlank()
                ? "AI service processing failed"
                : message);
        scan.setProcessedAt(Instant.now());
        scanRepository.saveAndFlush(scan);
    }

    private boolean isFailure(String status) {
        if (status == null) {
            return false;
        }
        String normalized = status.trim().toLowerCase(Locale.ROOT);
        return normalized.equals("failure") || normalized.equals("failed") || normalized.equals("error");
    }

    private AiServiceResponse uploadToAiService(ScanProcessingMessage message) {
        MultiValueMap<String, Object> body = convertToMultiValueMap(
                message.filename(),
                message.fileBase64()
        );

        return restClient.post()
                .uri("/api/process")
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .body(body)
                .retrieve()
                .body(AiServiceResponse.class);
    }

    private MultiValueMap<String, Object> convertToMultiValueMap(
            String filename,
            String base64File
    ) {
        if (base64File.contains(",")) {
            base64File = base64File.split(",")[1];
        }
        byte[] fileBytes = Base64.getDecoder().decode(base64File);
        ByteArrayResource fileResource = new ByteArrayResource(fileBytes) {
            @Override
            public String getFilename() {
                return filename;
            }
        };
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("files", fileResource);

        return body;
    }
}
