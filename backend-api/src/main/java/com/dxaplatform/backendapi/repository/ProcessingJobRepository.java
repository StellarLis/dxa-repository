package com.dxaplatform.backendapi.repository;

import com.dxaplatform.backendapi.entity.ProcessingJob;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.util.UUID;

public interface ProcessingJobRepository extends JpaRepository<ProcessingJob, UUID> {

    /** Для проверки владения через цепочку job -> research -> owner. */
    Optional<ProcessingJob> findByIdAndResearchOwnerId(UUID id, UUID ownerId);
}
