package com.dxaplatform.backendapi.service;

import com.dxaplatform.backendapi.dto.ScanDetailResponse;
import com.dxaplatform.backendapi.entity.Research;
import com.dxaplatform.backendapi.entity.Role;
import com.dxaplatform.backendapi.entity.Scan;
import com.dxaplatform.backendapi.exception.ApiException;
import com.dxaplatform.backendapi.repository.ScanRepository;
import com.dxaplatform.backendapi.security.AuthenticatedUser;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.UUID;

@Service
public class ScanQueryService {

    private final ResearchService researchService;
    private final ScanRepository scanRepository;

    public ScanQueryService(ResearchService researchService, ScanRepository scanRepository) {
        this.researchService = researchService;
        this.scanRepository = scanRepository;
    }

    /** GET /api/researches/{id}/scans -- сначала проверяем владение исследованием целиком. */
    public List<ScanDetailResponse> listByResearch(UUID researchId, AuthenticatedUser user) {
        Research research = researchService.findOwnedOrAdmin(researchId, user);
        return scanRepository.findByResearchIdOrderByUploadedAtDesc(research.getId()).stream()
                .map(this::toResponse)
                .toList();
    }

    /** GET /api/scans/{id} -- владение проверяется по цепочке scan -> research -> owner. */
    public ScanDetailResponse getDetail(UUID scanId, AuthenticatedUser user) {
        Scan scan = findOwnedOrAdmin(scanId, user);
        return toResponse(scan);
    }

    private Scan findOwnedOrAdmin(UUID scanId, AuthenticatedUser user) {
        if (user.role() == Role.ADMIN) {
            return scanRepository.findById(scanId)
                    .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "Скан не найден"));
        }
        return scanRepository.findByIdAndResearchOwnerId(scanId, user.id())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "Скан не найден"));
    }

    private ScanDetailResponse toResponse(Scan s) {
        return new ScanDetailResponse(
                s.getId(),
                s.getResearch().getId(),
                s.getJob().getId(),
                s.getOriginalFilename(),
                s.getStudyUid(),
                s.getImageUid(),
                s.getAnatomicalRegion(),
                s.getQualityClass(),
                s.getViolationType(),
                s.getComment(),
                s.getProcessingStatus().name(),
                s.getErrorMessage(),
                s.getTimeOfProcessing(),
                s.getThumbnailPngB64(),
                s.getUploadedAt(),
                s.getProcessedAt()
        );
    }
}
