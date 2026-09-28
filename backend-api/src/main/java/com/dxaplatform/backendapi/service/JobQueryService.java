package com.dxaplatform.backendapi.service;

import com.dxaplatform.backendapi.dto.JobStatusResponse;
import com.dxaplatform.backendapi.dto.ScanStatusCounts;
import com.dxaplatform.backendapi.entity.ProcessingJob;
import com.dxaplatform.backendapi.entity.ProcessingStatus;
import com.dxaplatform.backendapi.entity.Role;
import com.dxaplatform.backendapi.entity.Scan;
import com.dxaplatform.backendapi.exception.ApiException;
import com.dxaplatform.backendapi.repository.ProcessingJobRepository;
import com.dxaplatform.backendapi.repository.ScanRepository;
import com.dxaplatform.backendapi.security.AuthenticatedUser;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.UUID;

@Service
public class JobQueryService {

    private final ProcessingJobRepository processingJobRepository;
    private final ScanRepository scanRepository;

    public JobQueryService(ProcessingJobRepository processingJobRepository, ScanRepository scanRepository) {
        this.processingJobRepository = processingJobRepository;
        this.scanRepository = scanRepository;
    }

    public JobStatusResponse getStatus(UUID jobId, AuthenticatedUser user) {
        ProcessingJob job = findOwnedOrAdmin(jobId, user);
        List<Scan> scans = scanRepository.findByJobId(jobId);

        long pending = count(scans, ProcessingStatus.PENDING);
        long queued = count(scans, ProcessingStatus.QUEUED);
        long processing = count(scans, ProcessingStatus.PROCESSING);
        long success = count(scans, ProcessingStatus.SUCCESS);
        long failed = count(scans, ProcessingStatus.FAILED);

        return new JobStatusResponse(
                job.getId(),
                job.getStatus().name(),
                scans.size(),
                new ScanStatusCounts(pending, queued, processing, success, failed),
                job.getCreatedAt(),
                job.getCompletedAt()
        );
    }

    private ProcessingJob findOwnedOrAdmin(UUID jobId, AuthenticatedUser user) {
        if (user.role() == Role.ADMIN) {
            return processingJobRepository.findById(jobId)
                    .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "Задание не найдено"));
        }
        return processingJobRepository.findByIdAndResearchOwnerId(jobId, user.id())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "Задание не найдено"));
    }

    private long count(List<Scan> scans, ProcessingStatus status) {
        return scans.stream().filter(s -> s.getProcessingStatus() == status).count();
    }
}
