package com.dxaplatform.backendapi.dto;

public record AuthResponse(
        String accessToken,
        String tokenType,
        long expiresIn
) {
    public static AuthResponse bearer(String accessToken, long expiresIn) {
        return new AuthResponse(accessToken, "Bearer", expiresIn);
    }
}
