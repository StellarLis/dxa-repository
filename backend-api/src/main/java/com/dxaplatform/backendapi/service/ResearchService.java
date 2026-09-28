package com.dxaplatform.backendapi.service;

import com.dxaplatform.backendapi.dto.CreateResearchRequest;
import com.dxaplatform.backendapi.dto.ResearchResponse;
import com.dxaplatform.backendapi.entity.Research;
import com.dxaplatform.backendapi.entity.Role;
import com.dxaplatform.backendapi.entity.User;
import com.dxaplatform.backendapi.exception.ApiException;
import com.dxaplatform.backendapi.repository.ResearchRepository;
import com.dxaplatform.backendapi.repository.ScanRepository;
import com.dxaplatform.backendapi.repository.UserRepository;
import com.dxaplatform.backendapi.security.AuthenticatedUser;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;

/**
 * Проверка владения ("только владелец или ADMIN") сделана здесь, а не в
 * контроллере -- единственное место, где решается, кто что может, чтобы
 * не разойтись при добавлении новых эндпоинтов позже.
 *
 * Намеренно возвращаем 404, а не 403, когда чужой ресурс запрошен не-владельцем:
 * это не даёт постороннему узнать даже сам факт существования чужого id.
 */
@Service
public class ResearchService {

    private final ResearchRepository researchRepository;
    private final ScanRepository scanRepository;
    private final UserRepository userRepository;

    public ResearchService(
            ResearchRepository researchRepository,
            ScanRepository scanRepository,
            UserRepository userRepository
    ) {
        this.researchRepository = researchRepository;
        this.scanRepository = scanRepository;
        this.userRepository = userRepository;
    }

    public List<ResearchResponse> listForUser(UUID ownerId) {
        return researchRepository.findByOwnerIdOrderByUpdatedAtDesc(ownerId).stream()
                .map(this::toResponse)
                .toList();
    }

    @Transactional
    public ResearchResponse create(UUID ownerId, CreateResearchRequest request) {
        User owner = userRepository.findById(ownerId)
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "Пользователь не найден"));

        Research research = Research.builder()
                .owner(owner)
                .name(request.name())
                .description(request.description())
                .build();
        researchRepository.save(research);

        return toResponse(research);
    }

    public ResearchResponse getDetail(UUID researchId, AuthenticatedUser user) {
        return toResponse(findOwnedOrAdmin(researchId, user));
    }

    @Transactional
    public void delete(UUID researchId, AuthenticatedUser user) {
        Research research = findOwnedOrAdmin(researchId, user);
        researchRepository.delete(research); // ON DELETE CASCADE подчистит jobs/scans в БД
    }

    /** Используется другими сервисами (upload, scans) -- та же проверка владения, но отдаёт сущность. */
    Research findOwnedOrAdmin(UUID researchId, AuthenticatedUser user) {
        if (user.role() == Role.ADMIN) {
            return researchRepository.findById(researchId)
                    .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "Исследование не найдено"));
        }
        return researchRepository.findByIdAndOwnerId(researchId, user.id())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "Исследование не найдено"));
    }

    private ResearchResponse toResponse(Research r) {
        long scanCount = scanRepository.countByResearchId(r.getId());
        return new ResearchResponse(
                r.getId(), r.getName(), r.getDescription(), scanCount, r.getCreatedAt(), r.getUpdatedAt()
        );
    }
}
