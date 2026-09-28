package com.dxaplatform.backendapi.controller;

import com.dxaplatform.backendapi.dto.ScanDetailResponse;
import com.dxaplatform.backendapi.dto.UploadResponse;
import com.dxaplatform.backendapi.security.AuthenticatedUser;
import com.dxaplatform.backendapi.service.ScanQueryService;
import com.dxaplatform.backendapi.service.ScanUploadService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/researches/{researchId}/scans")
public class ScanController {

    private final ScanUploadService scanUploadService;
    private final ScanQueryService scanQueryService;

    public ScanController(ScanUploadService scanUploadService, ScanQueryService scanQueryService) {
        this.scanUploadService = scanUploadService;
        this.scanQueryService = scanQueryService;
    }

    /**
     * Раздел 4.3 ТЗ: 202 Accepted (не 200/201) -- запрос принят, но обработка
     * ещё не завершена (и даже не начата), она идёт асинхронно через Kafka.
     */
    @PostMapping
    public ResponseEntity<UploadResponse> upload(
            @AuthenticationPrincipal AuthenticatedUser user,
            @PathVariable UUID researchId,
            @RequestParam("files") List<MultipartFile> files
    ) {
        UploadResponse response = scanUploadService.upload(researchId, user, files);
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(response);
    }

    @GetMapping
    public List<ScanDetailResponse> list(
            @AuthenticationPrincipal AuthenticatedUser user,
            @PathVariable UUID researchId
    ) {
        return scanQueryService.listByResearch(researchId, user);
    }
}

