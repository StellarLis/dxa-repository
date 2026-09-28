package com.dxaplatform.backendapi.controller;

import com.dxaplatform.backendapi.dto.CreateResearchRequest;
import com.dxaplatform.backendapi.dto.ResearchResponse;
import com.dxaplatform.backendapi.security.AuthenticatedUser;
import com.dxaplatform.backendapi.service.ResearchReportService;
import com.dxaplatform.backendapi.service.ResearchService;
import jakarta.validation.Valid;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/researches")
public class ResearchController {

    private final ResearchService researchService;
    private final ResearchReportService researchReportService;

    public ResearchController(ResearchService researchService, ResearchReportService researchReportService) {
        this.researchService = researchService;
        this.researchReportService = researchReportService;
    }

    @GetMapping
    public List<ResearchResponse> list(@AuthenticationPrincipal AuthenticatedUser user) {
        return researchService.listForUser(user.id());
    }

    @PostMapping
    public ResponseEntity<ResearchResponse> create(
            @AuthenticationPrincipal AuthenticatedUser user,
            @Valid @RequestBody CreateResearchRequest request
    ) {
        return ResponseEntity.status(HttpStatus.CREATED).body(researchService.create(user.id(), request));
    }

    @GetMapping("/{id}")
    public ResearchResponse getOne(
            @AuthenticationPrincipal AuthenticatedUser user,
            @PathVariable UUID id
    ) {
        return researchService.getDetail(id, user);
    }

    @GetMapping("/{id}/report")
    public ResponseEntity<byte[]> report(
            @AuthenticationPrincipal AuthenticatedUser user,
            @PathVariable UUID id
    ) {
        researchService.getDetail(id, user);
        byte[] report = researchReportService.createReport(id);
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=research-report.xlsx")
                .contentType(MediaType.parseMediaType(
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
                .body(report);
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(
            @AuthenticationPrincipal AuthenticatedUser user,
            @PathVariable UUID id
    ) {
        researchService.delete(id, user);
        return ResponseEntity.noContent().build();
    }
}
