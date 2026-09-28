package com.dxaplatform.backendapi.controller;

import com.dxaplatform.backendapi.dto.JobStatusResponse;
import com.dxaplatform.backendapi.security.AuthenticatedUser;
import com.dxaplatform.backendapi.service.JobQueryService;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

@RestController
@RequestMapping("/api/jobs")
public class JobController {

    private final JobQueryService jobQueryService;

    public JobController(JobQueryService jobQueryService) {
        this.jobQueryService = jobQueryService;
    }

    @GetMapping("/{jobId}")
    public JobStatusResponse getStatus(@AuthenticationPrincipal AuthenticatedUser user, @PathVariable UUID jobId) {
        return jobQueryService.getStatus(jobId, user);
    }
}
