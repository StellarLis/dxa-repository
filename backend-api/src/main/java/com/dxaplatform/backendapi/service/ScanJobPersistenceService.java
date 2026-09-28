package com.dxaplatform.backendapi.service;

import com.dxaplatform.backendapi.entity.*;
import com.dxaplatform.backendapi.repository.ProcessingJobRepository;
import com.dxaplatform.backendapi.repository.ScanRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * Вынесено В ОТДЕЛЬНЫЙ бин намеренно: @Transactional работает через
 * Spring AOP прокси, а вызов метода того же класса изнутри другого метода
 * ЭТОГО ЖЕ класса (self-invocation) идёт напрямую, МИМО прокси -- аннотация
 * при этом молча игнорируется, без единой ошибки. Если бы этот метод жил
 * внутри ScanUploadService и вызывался как this.persistJobAndScans(...),
 * транзакция бы не работала. Отдельный бин с внешним вызовом через
 * DI-ссылку -- стандартное решение этой проблемы.
 */
@Service
public class ScanJobPersistenceService {

    private final ProcessingJobRepository processingJobRepository;
    private final ScanRepository scanRepository;

    public ScanJobPersistenceService(
            ProcessingJobRepository processingJobRepository,
            ScanRepository scanRepository
    ) {
        this.processingJobRepository = processingJobRepository;
        this.scanRepository = scanRepository;
    }

    public record ValidatedFile(String filename, byte[] bytes) {
    }

    public record PersistedFile(ProcessingJob job, Scan scan, byte[] fileBytes) {
    }

    @Transactional
    public List<PersistedFile> persistJobAndScans(
            Research research, User requestedBy, List<ValidatedFile> files
    ) {
        ProcessingJob job = ProcessingJob.builder()
                .id(UUID.randomUUID()) // генерируем сами -- см. комментарий в ProcessingJob.java
                .research(research)
                .requestedBy(requestedBy)
                .status(JobStatus.PENDING)
                .build();
        job = processingJobRepository.save(job);

        List<PersistedFile> result = new ArrayList<>();
        for (ValidatedFile vf : files) {
            Scan scan = Scan.builder()
                    .research(research)
                    .job(job)
                    .originalFilename(vf.filename())
                    .processingStatus(ProcessingStatus.QUEUED)
                    .build();
            scanRepository.save(scan);
            result.add(new PersistedFile(job, scan, vf.bytes()));
        }
        return result;
    }
}
