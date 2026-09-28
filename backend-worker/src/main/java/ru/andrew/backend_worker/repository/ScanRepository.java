package ru.andrew.backend_worker.repository;

import ru.andrew.backend_worker.entity.ProcessingStatus;
import ru.andrew.backend_worker.entity.Scan;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface ScanRepository extends JpaRepository<Scan, UUID> {

    List<Scan> findByResearchIdOrderByUploadedAtDesc(UUID researchId);

    List<Scan> findByJobId(UUID jobId);

    /** Для проверки владения через цепочку scan -> research -> owner. */
    Optional<Scan> findByIdAndResearchOwnerId(UUID id, UUID ownerId);

    long countByResearchId(UUID researchId);

    long countByJobId(UUID jobId);

    long countByJobIdAndProcessingStatusIn(UUID jobId, Collection<ProcessingStatus> statuses);
}
