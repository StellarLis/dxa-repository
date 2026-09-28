package com.dxaplatform.backendapi.repository;

import com.dxaplatform.backendapi.entity.Research;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface ResearchRepository extends JpaRepository<Research, UUID> {

    List<Research> findByOwnerIdOrderByUpdatedAtDesc(UUID ownerId);

    /** Для проверки владения: найдёт запись, только если она принадлежит этому owner_id. */
    Optional<Research> findByIdAndOwnerId(UUID id, UUID ownerId);
}
