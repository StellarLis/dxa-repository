package com.dxaplatform.backendapi.controller;

import com.dxaplatform.backendapi.dto.ScanDetailResponse;
import com.dxaplatform.backendapi.security.AuthenticatedUser;
import com.dxaplatform.backendapi.service.ScanQueryService;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

@RestController
@RequestMapping("/api/scans")
public class ScanDetailController {

    private final ScanQueryService scanQueryService;

    public ScanDetailController(ScanQueryService scanQueryService) {
        this.scanQueryService = scanQueryService;
    }

    @GetMapping("/{id}")
    public ScanDetailResponse getOne(@AuthenticationPrincipal AuthenticatedUser user, @PathVariable UUID id) {
        return scanQueryService.getDetail(id, user);
    }
}
