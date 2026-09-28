package com.dxaplatform.backendapi.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record RegisterRequest(
        @NotBlank @Email String email,
        @NotBlank @Size(min = 8, message = "пароль должен быть не короче 8 символов") String password,
        @NotBlank String displayName
) {
}
